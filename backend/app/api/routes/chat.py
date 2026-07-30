"""Operator chat — talk to the same free models the agents use, and push an
idea from the conversation straight into the opportunity pipeline.

The point is not a general-purpose chatbot: it's that the operator sees what
the agents are working on and usually knows something they don't. Without this,
the only way to inject an idea is to wait for Scout to stumble on it.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.core.model_router import AllModelsFailedError, ModelRouter
from app.core.tools import create_opportunity
from app.db.models import ModelUsageLog
from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

SYSTEM_PROMPT = (
    "You are an operator-facing assistant inside Anvil, an autonomous company "
    "that finds real problems and builds small products for them. The person "
    "talking to you owns the company. Be concrete and brief. If they describe "
    "an idea, pressure-test it: who exactly pays, what already exists, why it "
    "would lose. Say when an idea is weak — an agreeable answer here costs "
    "them real money later."
)

# One router instance: it holds per-model failure counters and cooldowns, and a
# fresh instance per request would forget which models are currently rate
# limited and hammer them again on every message.
_router = ModelRouter()


class Message(BaseModel):
    role: str
    content: str


class ChatIn(BaseModel):
    messages: list[Message]
    # None = whatever the registry ranks first. "coding"/"reasoning" scope to
    # that group (see model_registry.yaml capability field).
    capability: str | None = None
    # Ask several models the same thing and show the answers side by side —
    # cheap here because they're all free, and disagreement between them is
    # itself a signal about how solid an idea is.
    fanout: int = 1

    @field_validator("fanout")
    @classmethod
    def _sane_fanout(cls, v: int) -> int:
        # Above 4 the wall of text stops being comparable and every model in
        # the registry gets burned on one message.
        if not 1 <= v <= 4:
            raise ValueError("fanout must be between 1 and 4")
        return v

    @field_validator("messages")
    @classmethod
    def _not_empty(cls, v: list[Message]) -> list[Message]:
        if not v:
            raise ValueError("messages cannot be empty")
        return v


class IdeaIn(BaseModel):
    problem: str
    target_customer: str | None = None
    possible_product: str | None = None

    @field_validator("problem")
    @classmethod
    def _has_substance(cls, v: str) -> str:
        if len(v.strip()) < 10:
            raise ValueError("problem must be at least 10 characters")
        return v.strip()


def _flatten(messages: list[Message]) -> str:
    """The router's complete() takes a single user string, not a message list —
    it exists to serve agents, which are one-shot. Rather than widen that API
    (and every agent call with it) for one caller, fold the history into one
    prompt here."""
    return "\n\n".join(f"{m.role.upper()}: {m.content}" for m in messages) + "\n\nASSISTANT:"


@router.get("/models")
def available_models():
    """What the operator can pick from — read from the same registry the agents
    route through, so the dropdown can't drift from reality."""
    return [
        {"name": m.name, "display_name": m.display_name or m.name, "capability": m.capability}
        for m in _router.candidates()
    ]


@router.post("")
def chat(body: ChatIn, db: Session = Depends(get_db)):
    prompt = _flatten(body.messages)
    replies: list[dict] = []
    tried: set[str] = set()

    for _ in range(body.fanout):
        def record(*, model_name, success, tokens_in, tokens_out, latency_ms, error, cost_usd):
            # Same ledger the agents write to, so operator chat shows up in
            # spend and success-rate rather than being invisible cost.
            db.add(
                ModelUsageLog(
                    model_name=model_name,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency_ms,
                    success=success,
                    error=error,
                    cost_usd=cost_usd,
                )
            )
            tried.add(model_name)

        try:
            # Excluding models already used is what makes fanout return N
            # different opinions instead of the top model N times.
            result = _router.complete(
                SYSTEM_PROMPT,
                prompt,
                capability=body.capability,
                exclude=set(tried),
                on_attempt=record,
            )
        except AllModelsFailedError as exc:
            if not replies:
                db.commit()
                raise HTTPException(503, str(exc)) from exc
            break  # got at least one answer; a short fanout beats a 503

        replies.append({"model": result.model_used, "content": result.content})

    db.commit()
    return {"replies": replies}


@router.post("/idea")
def submit_idea(body: IdeaIn, db: Session = Depends(get_db)):
    """Push an idea from the conversation into the same table Scout writes to,
    so Research scores it and the CEO decides on it like any other lead —
    rather than it living only in a chat log."""
    opp = create_opportunity(
        db,
        problem=body.problem,
        target_customer=body.target_customer,
        existing_solutions=[],
        pain_level=None,
        possible_product=body.possible_product,
        revenue_potential=None,
        source="operator",
        source_url=None,
        discovered_by_agent_id=None,
    )
    db.commit()
    return {"id": str(opp.id), "status": opp.status}

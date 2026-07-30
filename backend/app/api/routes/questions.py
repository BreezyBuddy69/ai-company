import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import HumanQuestion
from app.db.session import get_db

router = APIRouter(prefix="/api/questions", tags=["questions"])


class QuestionOut(BaseModel):
    """Note what is absent: `answer`. A question can be a request for a
    password or an API key, and this endpoint is what paints the dashboard —
    echoing secrets back into a web page (and into every browser cache and
    log along the way) for no functional gain. The agent reads answers
    straight from the DB, not through here."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    agent: str
    question: str
    context: str | None
    kind: str
    status: str
    created_at: datetime
    answered_at: datetime | None


class AskIn(BaseModel):
    agent: str
    question: str
    context: str | None = None
    kind: str = "text"
    ask_key: str | None = None

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in ("text", "secret"):
            raise ValueError("kind must be 'text' or 'secret'")
        return v


class AnswerIn(BaseModel):
    answer: str

    @field_validator("answer")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        # An empty answer would flip status to "answered" and the agent would
        # act on "". Make the operator say something or leave it open.
        if not v.strip():
            raise ValueError("answer cannot be empty")
        return v


@router.get("", response_model=list[QuestionOut])
def list_questions(status: str | None = "open", limit: int = 50, db: Session = Depends(get_db)):
    stmt = select(HumanQuestion).order_by(HumanQuestion.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(HumanQuestion.status == status)
    return list(db.scalars(stmt))


@router.post("", response_model=QuestionOut)
def ask(body: AskIn, db: Session = Depends(get_db)):
    """Agents post here. Re-asking with the same ask_key returns the existing
    row instead of creating a duplicate, so an agent that runs every 15
    minutes doesn't produce 96 identical questions a day."""
    if body.ask_key:
        existing = db.scalar(select(HumanQuestion).where(HumanQuestion.ask_key == body.ask_key))
        if existing:
            return existing
    q = HumanQuestion(
        agent=body.agent,
        question=body.question,
        context=body.context,
        kind=body.kind,
        ask_key=body.ask_key,
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


@router.post("/{question_id}/answer", response_model=QuestionOut)
def answer(question_id: uuid.UUID, body: AnswerIn, db: Session = Depends(get_db)):
    q = db.get(HumanQuestion, question_id)
    if not q:
        raise HTTPException(404, "question not found")
    q.answer = body.answer
    q.status = "answered"
    q.answered_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(q)
    return q


@router.post("/{question_id}/dismiss", response_model=QuestionOut)
def dismiss(question_id: uuid.UUID, db: Session = Depends(get_db)):
    """Close a question without answering it — the agent then stops waiting
    and proceeds without that input, rather than the question sitting open
    forever."""
    q = db.get(HumanQuestion, question_id)
    if not q:
        raise HTTPException(404, "question not found")
    q.status = "dismissed"
    q.answered_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(q)
    return q

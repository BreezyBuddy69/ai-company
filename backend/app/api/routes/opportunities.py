import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tools import decide_opportunity
from app.db.models import Opportunity
from app.db.session import get_db

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


class OpportunityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    problem: str
    target_customer: str | None
    existing_solutions: list
    pain_level: int | None
    possible_product: str | None
    revenue_potential: str | None
    source: str
    source_url: str | None
    research_score: float | None
    research_notes: str | None
    status: str
    decision_rationale: str | None
    created_at: datetime


class DecisionIn(BaseModel):
    decision: str  # approved | watch | rejected
    decision_rationale: str


@router.get("", response_model=list[OpportunityOut])
def list_opportunities(status: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    stmt = select(Opportunity).order_by(Opportunity.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Opportunity.status == status)
    return list(db.scalars(stmt))


@router.get("/{opportunity_id}", response_model=OpportunityOut)
def get_opportunity(opportunity_id: uuid.UUID, db: Session = Depends(get_db)):
    opp = db.get(Opportunity, opportunity_id)
    if not opp:
        raise HTTPException(404, "opportunity not found")
    return opp


@router.post("/{opportunity_id}/decision", response_model=OpportunityOut)
def decide(opportunity_id: uuid.UUID, body: DecisionIn, db: Session = Depends(get_db)):
    """Human override from the dashboard's Approve/Reject/Launch buttons —
    bypasses the CEO agent entirely, same effect on the row."""
    try:
        opp = decide_opportunity(
            db, opportunity_id, decision=body.decision, decision_rationale=body.decision_rationale
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return opp

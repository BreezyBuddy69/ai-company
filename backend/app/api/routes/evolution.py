import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.evolution import score_agent, score_product
from app.db.models import Agent, EvolutionHistory, Product
from app.db.session import get_db

router = APIRouter(prefix="/api/evolution", tags=["evolution"])


@router.get("/history")
def history(entity_type: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    stmt = select(EvolutionHistory).order_by(EvolutionHistory.created_at.desc()).limit(limit)
    if entity_type:
        stmt = stmt.where(EvolutionHistory.entity_type == entity_type)
    rows = db.scalars(stmt).all()
    return [
        {
            "id": str(r.id), "entity_type": r.entity_type, "entity_id": str(r.entity_id),
            "generation": r.generation, "score": float(r.score) if r.score is not None else None,
            "score_breakdown": r.score_breakdown, "parent_id": str(r.parent_id) if r.parent_id else None,
            "mutation_notes": r.mutation_notes, "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


class ScoreIn(BaseModel):
    # each 0-100, pre-normalized by the caller — see core/evolution.py weights
    values: dict[str, float]
    mutation_notes: str | None = None


@router.post("/score/agent/{agent_id}")
def score_agent_endpoint(agent_id: uuid.UUID, body: ScoreIn, db: Session = Depends(get_db)):
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "agent not found")
    entry = score_agent(db, agent, body.values, mutation_notes=body.mutation_notes)
    db.commit()
    return {"id": str(entry.id), "score": float(entry.score), "breakdown": entry.score_breakdown}


@router.post("/score/product/{product_id}")
def score_product_endpoint(product_id: uuid.UUID, body: ScoreIn, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "product not found")
    entry = score_product(db, product, body.values, mutation_notes=body.mutation_notes)
    db.commit()
    return {"id": str(entry.id), "score": float(entry.score), "breakdown": entry.score_breakdown}

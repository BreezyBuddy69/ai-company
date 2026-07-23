import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.runner import resolve_agent_dirs
from app.config import get_settings
from app.core.evolution import agent_family, family_snapshot, run_role_competition, score_agent, score_product
from app.db.models import Agent, EvolutionHistory, Product
from app.db.session import get_db

router = APIRouter(prefix="/api/evolution", tags=["evolution"])


@router.get("/families")
def families(db: Session = Depends(get_db)):
    """Every role currently running at least one active agent, each with its
    variants and their live scores — the data behind the dashboard's arena
    view ("who's competing against whom, and who's winning")."""
    names = sorted({agent_family(a.name) for a in db.scalars(select(Agent).where(Agent.status == "active"))})
    return [family_snapshot(db, name) for name in names]


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


@router.post("/compete/{family}")
def compete_endpoint(family: str, db: Session = Depends(get_db)):
    """Manual trigger for the clone/retire cycle Celery Beat also runs daily
    (app.tasks.run_evolution_cycle) — mainly for testing without waiting for
    the schedule. See core/evolution.run_role_competition for the policy."""
    config_dir, _, _ = resolve_agent_dirs(get_settings())
    return run_role_competition(db, config_dir, family)

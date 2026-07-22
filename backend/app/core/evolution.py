"""Evolution engine — v1 scope: scoring + history, no automatic mutation yet.

An automatic clone/mutate/archive cycle needs weeks of real revenue/usage
data to make sound decisions on. Faking that data would violate the "never
fake metrics" principle in the project brief, so v1 ships the scoring
formulas, the evolution_history schema (with parent_id, ready for a real
generational tree), and a manually-triggered scoring pass. The automatic
cycle is a Phase-2 follow-up once products have real metrics.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Agent, EvolutionHistory, Product

PRODUCT_WEIGHTS = {
    "revenue": 0.40,
    "user_growth": 0.20,
    "conversion": 0.15,
    "speed": 0.10,
    "satisfaction": 0.10,
    "cost_efficiency": 0.05,
}

AGENT_WEIGHTS = {
    "success_rate": 0.35,
    "quality": 0.30,
    "speed": 0.20,
    "cost": 0.15,
}


@dataclass
class ScoreInput:
    # each value is expected pre-normalized to a 0-100 scale by the caller
    values: dict[str, float]


def _weighted_score(values: dict[str, float], weights: dict[str, float]) -> tuple[float, dict[str, float]]:
    breakdown = {}
    total = 0.0
    for key, weight in weights.items():
        v = max(0.0, min(100.0, values.get(key, 0.0)))
        contribution = v * weight
        breakdown[key] = round(contribution, 3)
        total += contribution
    return round(total, 3), breakdown


def score_product(db: Session, product: Product, values: dict[str, float], *, mutation_notes: str | None = None) -> EvolutionHistory:
    total, breakdown = _weighted_score(values, PRODUCT_WEIGHTS)
    parent = _latest_history(db, "product", product.id)
    entry = EvolutionHistory(
        entity_type="product",
        entity_id=product.id,
        generation=(parent.generation + 1) if parent else 1,
        score=total,
        score_breakdown=breakdown,
        parent_id=parent.id if parent else None,
        mutation_notes=mutation_notes,
    )
    db.add(entry)
    db.flush()
    return entry


def score_agent(db: Session, agent: Agent, values: dict[str, float], *, mutation_notes: str | None = None) -> EvolutionHistory:
    total, breakdown = _weighted_score(values, AGENT_WEIGHTS)
    parent = _latest_history(db, "agent", agent.id)
    entry = EvolutionHistory(
        entity_type="agent",
        entity_id=agent.id,
        generation=(parent.generation + 1) if parent else 1,
        score=total,
        score_breakdown=breakdown,
        parent_id=parent.id if parent else None,
        mutation_notes=mutation_notes,
    )
    db.add(entry)
    db.flush()
    return entry


def _latest_history(db: Session, entity_type: str, entity_id: uuid.UUID) -> EvolutionHistory | None:
    from sqlalchemy import select

    stmt = (
        select(EvolutionHistory)
        .where(EvolutionHistory.entity_type == entity_type, EvolutionHistory.entity_id == entity_id)
        .order_by(EvolutionHistory.generation.desc())
        .limit(1)
    )
    return db.scalar(stmt)

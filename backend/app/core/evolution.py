"""Evolution engine — scoring, plus a real clone/retire cycle for agents.

Same-role agent variants (named "<family>" and "<family>-g<N>") compete on
identical tasks (see app/tasks.py, which now fans each cycle out to every
active variant in a family instead of one hardcoded name). Judged only on
objective app/db/models.AgentRun aggregates (success rate, latency, cost) —
never an LLM's opinion of "quality" — and only once a variant has run enough
times that the numbers mean something (MIN_RUNS_FOR_COMPETITION). Below that
threshold, run_role_competition is a no-op; it never guesses.

Product scoring (score_product) stays manual/caller-supplied — v1 has no
product generating real usage data to auto-score against yet.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Agent, AgentRun, EvolutionHistory, Product

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
    stmt = (
        select(EvolutionHistory)
        .where(EvolutionHistory.entity_type == entity_type, EvolutionHistory.entity_id == entity_id)
        .order_by(EvolutionHistory.generation.desc())
        .limit(1)
    )
    return db.scalar(stmt)


# ============================================================
# Agent clone/retire cycle
# ============================================================

MIN_RUNS_FOR_COMPETITION = 5
_GENERATION_SUFFIX = re.compile(r"-g\d+$")


def agent_family(name: str) -> str:
    """'scout' -> 'scout'; 'scout-g3' -> 'scout' — the name shared by every
    variant competing for the same role."""
    return _GENERATION_SUFFIX.sub("", name)


def active_variant_names(db: Session, family: str) -> list[str]:
    """Every currently-active agent competing under `family`. Falls back to
    [family] itself when no Agent row exists yet (first-ever run, before
    app/agents/runner.get_or_create_agent_row has created one)."""
    rows = db.scalars(select(Agent).where(Agent.status == "active")).all()
    names = [a.name for a in rows if agent_family(a.name) == family]
    return names or [family]


def _runtime_metrics(db: Session, agent_id: uuid.UUID) -> dict[str, float] | None:
    """Objective 0-100 scores from real agent_runs — no LLM judgment call.
    None means "not enough runs yet", never a guessed number.

    ponytail: latency/cost normalization below is a crude fixed scale (10s
    round-trip -> 0, $0.01/call -> 0), fine while every model in
    model_registry.yaml is free-tier. Revisit if paid models enter the mix.
    """
    rows = list(
        db.scalars(
            select(AgentRun).where(AgentRun.agent_id == agent_id).order_by(AgentRun.created_at.desc()).limit(50)
        )
    )
    if len(rows) < MIN_RUNS_FOR_COMPETITION:
        return None

    success_rate = 100.0 * sum(1 for r in rows if r.success) / len(rows)

    latencies = [r.latency_ms for r in rows if r.latency_ms is not None]
    avg_latency_ms = sum(latencies) / len(latencies) if latencies else 0.0
    speed = max(0.0, 100.0 - avg_latency_ms / 100.0)  # 10_000ms -> 0

    avg_cost = sum(float(r.cost_usd) for r in rows) / len(rows)
    cost_score = max(0.0, 100.0 - avg_cost * 10_000)  # $0.01/call -> 0

    # "quality" has no objective signal here (would need an LLM judge, which
    # is itself a guess) — score it 0 rather than fake a neutral midpoint.
    return {"success_rate": success_rate, "speed": speed, "cost": cost_score, "quality": 0.0}


def clone_agent(db: Session, config_dir: Path, parent: Agent, *, mutation_notes: str) -> Agent:
    """Fork `parent` into a new, slightly-mutated sibling variant: copies its
    YAML config, tweaks one knob, registers the new Agent row, and logs the
    fork in evolution_history so the dashboard's Evolution page shows the
    lineage."""
    family = agent_family(parent.name)
    new_generation = parent.generation + 1
    new_name = f"{family}-g{new_generation}"

    raw = yaml.safe_load(Path(parent.config_path).read_text(encoding="utf-8"))
    raw["name"] = new_name
    raw["max_steps"] = max(1, raw.get("max_steps", 5) + (1 if new_generation % 2 else -1))
    dest = config_dir / f"{new_name}.yaml"
    dest.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    clone = Agent(
        name=new_name,
        role=parent.role,
        config_path=str(dest),
        status="active",
        generation=new_generation,
        parent_agent_id=parent.id,
    )
    db.add(clone)
    db.flush()

    parent_history = _latest_history(db, "agent", parent.id)
    db.add(
        EvolutionHistory(
            entity_type="agent",
            entity_id=clone.id,
            generation=new_generation,
            score=parent_history.score if parent_history else None,
            score_breakdown=parent_history.score_breakdown if parent_history else {},
            parent_id=parent_history.id if parent_history else None,
            mutation_notes=mutation_notes,
        )
    )
    db.flush()
    return clone


def retire_agent(db: Session, agent: Agent, *, reason: str) -> None:
    """Stops an agent from being scheduled or run. Soft-delete (status
    change, not a row/file delete) on purpose — evolution_history keeps
    parent_id lineage pointing at it, which a hard delete would orphan."""
    agent.status = "archived"
    db.flush()
    history = _latest_history(db, "agent", agent.id)
    db.add(
        EvolutionHistory(
            entity_type="agent",
            entity_id=agent.id,
            generation=agent.generation,
            score=history.score if history else None,
            score_breakdown=history.score_breakdown if history else {},
            parent_id=history.id if history else None,
            mutation_notes=f"retired: {reason}",
        )
    )
    db.flush()


def family_snapshot(db: Session, family: str) -> dict:
    """Read-only view of a role family for the dashboard's Evolution arena:
    every active variant plus its objective metrics (or None while it's
    still under MIN_RUNS_FOR_COMPETITION) — same numbers run_role_competition
    judges on, just without mutating anything."""
    variants = [a for a in db.scalars(select(Agent).where(Agent.status == "active")) if agent_family(a.name) == family]
    out = []
    for v in variants:
        run_count = db.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.agent_id == v.id)) or 0
        metrics = _runtime_metrics(db, v.id)
        score = _weighted_score(metrics, AGENT_WEIGHTS)[0] if metrics else None
        out.append(
            {
                "id": str(v.id),
                "name": v.name,
                "generation": v.generation,
                "parent_agent_id": str(v.parent_agent_id) if v.parent_agent_id else None,
                "run_count": run_count,
                "runs_needed": max(0, MIN_RUNS_FOR_COMPETITION - run_count),
                "metrics": metrics,
                "score": score,
            }
        )
    out.sort(key=lambda v: (v["score"] is None, -(v["score"] or 0)))
    return {"family": family, "variants": out, "min_runs_for_competition": MIN_RUNS_FOR_COMPETITION}


def run_role_competition(db: Session, config_dir: Path, family: str) -> dict:
    """The actual policy: exactly one active variant -> bootstrap a sibling
    once it's proven itself (>= MIN_RUNS_FOR_COMPETITION runs), so there's
    something to compete against. Two or more -> score all of them, retire
    the worst, clone the best — population stays constant, the roster just
    keeps getting slightly different from its best-performing member."""
    variants = [a for a in db.scalars(select(Agent).where(Agent.status == "active")) if agent_family(a.name) == family]

    if len(variants) == 0:
        return {"family": family, "action": "none", "reason": "no active agent in this family"}

    if len(variants) == 1:
        agent = variants[0]
        metrics = _runtime_metrics(db, agent.id)
        if metrics is None:
            return {"family": family, "action": "none", "reason": f"{agent.name} has fewer than {MIN_RUNS_FOR_COMPETITION} runs — not enough data to bootstrap a competitor yet"}
        clone = clone_agent(db, config_dir, agent, mutation_notes=f"bootstrap: first sibling variant of {agent.name}")
        db.commit()
        return {"family": family, "action": "bootstrapped", "clone": clone.name}

    scored = []
    for variant in variants:
        metrics = _runtime_metrics(db, variant.id)
        if metrics is None:
            return {"family": family, "action": "none", "reason": f"{variant.name} has fewer than {MIN_RUNS_FOR_COMPETITION} runs — waiting before judging this family"}
        total, breakdown = _weighted_score(metrics, AGENT_WEIGHTS)
        scored.append((total, breakdown, variant))

    scored.sort(key=lambda t: t[0], reverse=True)
    winner_score, _, winner = scored[0]
    loser_score, _, loser = scored[-1]

    retire_agent(db, loser, reason=f"scored {loser_score} vs {winner.name}'s {winner_score} after {MIN_RUNS_FOR_COMPETITION}+ runs each")
    clone = clone_agent(
        db, config_dir, winner,
        mutation_notes=f"cloned from {winner.name} (score {winner_score}) after retiring {loser.name} (score {loser_score})",
    )
    db.commit()
    return {"family": family, "action": "cloned", "winner": winner.name, "winner_score": winner_score, "retired": loser.name, "retired_score": loser_score, "clone": clone.name}

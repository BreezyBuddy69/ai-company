from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.evolution import agent_family
from app.db.models import Agent, AgentRun, EvolutionHistory, ModelUsageLog, Opportunity
from app.db.session import get_db

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard/overview")
def overview(db: Session = Depends(get_db)):
    active_agents = db.scalar(select(func.count()).select_from(Agent).where(Agent.status == "active")) or 0
    since = datetime.now(timezone.utc) - timedelta(days=1)
    opportunities_today = db.scalar(
        select(func.count()).select_from(Opportunity).where(Opportunity.created_at >= since)
    ) or 0
    total_calls = db.scalar(select(func.count()).select_from(ModelUsageLog)) or 0
    successful_calls = db.scalar(
        select(func.count()).select_from(ModelUsageLog).where(ModelUsageLog.success.is_(True))
    ) or 0
    model_success_rate = round((successful_calls / total_calls) * 100, 1) if total_calls else None

    runs_today = db.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.created_at >= since)) or 0
    last_run_at = db.scalar(select(func.max(AgentRun.created_at)))
    opportunities_by_status = dict(
        db.execute(select(Opportunity.status, func.count()).group_by(Opportunity.status)).all()
    )
    clones_total = db.scalar(
        select(func.count()).select_from(EvolutionHistory).where(EvolutionHistory.mutation_notes.ilike("cloned from%"))
    ) or 0
    retirees_total = db.scalar(
        select(func.count()).select_from(EvolutionHistory).where(EvolutionHistory.mutation_notes.ilike("retired:%"))
    ) or 0
    families = sorted({agent_family(a.name) for a in db.scalars(select(Agent).where(Agent.status == "active"))})

    return {
        "active_agents": active_agents,
        "opportunities_last_24h": opportunities_today,
        "model_success_rate_pct": model_success_rate,
        "total_model_calls": total_calls,
        "spend_usd": 0.0,  # free-first router enforces this; see model_registry.yaml
        "agent_runs_today": runs_today,
        "last_run_at": last_run_at.isoformat() if last_run_at else None,
        "opportunities_by_status": opportunities_by_status,
        "evolution_clones_total": clones_total,
        "evolution_retirees_total": retirees_total,
        "active_families": families,
    }


@router.get("/logs")
def recent_logs(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.scalars(select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit)).all()
    agents = {a.id: a.name for a in db.scalars(select(Agent))}
    return [
        {
            "id": str(r.id),
            "agent": agents.get(r.agent_id, str(r.agent_id)),
            "task_id": str(r.task_id) if r.task_id else None,
            "model_used": r.model_used,
            "success": r.success,
            "error": r.error,
            "latency_ms": r.latency_ms,
            "tokens_in": r.tokens_in,
            "tokens_out": r.tokens_out,
            "output": r.output,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]

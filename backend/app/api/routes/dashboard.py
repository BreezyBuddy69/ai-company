from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Agent, AgentRun, ModelUsageLog, Opportunity
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

    return {
        "active_agents": active_agents,
        "opportunities_last_24h": opportunities_today,
        "model_success_rate_pct": model_success_rate,
        "total_model_calls": total_calls,
        "spend_usd": 0.0,  # free-first router enforces this; see model_registry.yaml
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

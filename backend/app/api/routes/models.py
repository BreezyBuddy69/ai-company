from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models import ModelUsageLog
from app.db.session import get_db

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("/usage")
def usage_by_model(db: Session = Depends(get_db)):
    stmt = (
        select(
            ModelUsageLog.model_name,
            func.count().label("calls"),
            func.sum(case((ModelUsageLog.success.is_(True), 1), else_=0)).label("successes"),
            func.avg(ModelUsageLog.latency_ms).label("avg_latency_ms"),
            func.sum(ModelUsageLog.tokens_in).label("tokens_in"),
            func.sum(ModelUsageLog.tokens_out).label("tokens_out"),
            func.sum(ModelUsageLog.cost_usd).label("cost_usd"),
        )
        .group_by(ModelUsageLog.model_name)
        .order_by(func.count().desc())
    )
    rows = db.execute(stmt).all()
    return [
        {
            "model_name": r.model_name,
            "calls": r.calls,
            "successes": r.successes,
            "success_rate": round((r.successes / r.calls) * 100, 1) if r.calls else 0.0,
            "avg_latency_ms": round(float(r.avg_latency_ms), 1) if r.avg_latency_ms else None,
            "tokens_in": r.tokens_in or 0,
            "tokens_out": r.tokens_out or 0,
            "cost_usd": float(r.cost_usd or 0),
        }
        for r in rows
    ]

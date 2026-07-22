from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models import FinanceTransaction
from app.db.session import get_db

router = APIRouter(prefix="/api/finance", tags=["finance"])


@router.get("/summary")
def finance_summary(db: Session = Depends(get_db)):
    revenue = db.scalar(
        select(func.coalesce(func.sum(FinanceTransaction.amount_usd), 0)).where(FinanceTransaction.type == "revenue")
    )
    cost = db.scalar(
        select(func.coalesce(func.sum(FinanceTransaction.amount_usd), 0)).where(FinanceTransaction.type == "cost")
    )
    revenue = float(revenue or 0)
    cost = float(cost or 0)
    return {"revenue_usd": revenue, "cost_usd": cost, "profit_usd": round(revenue - cost, 2)}

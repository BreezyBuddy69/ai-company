import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Task
from app.db.session import get_db

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    type: str
    status: str
    payload: dict
    result: dict | None
    created_at: datetime
    updated_at: datetime


@router.get("", response_model=list[TaskOut])
def list_tasks(status: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    stmt = select(Task).order_by(Task.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Task.status == status)
    return list(db.scalars(stmt))

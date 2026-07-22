import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.loader import AgentConfigError
from app.agents.runner import resolve_agent_dirs, run_agent
from app.config import get_settings
from app.db.models import Agent, AgentRun
from app.db.session import get_db

router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    role: str
    status: str
    generation: int
    created_at: datetime


class AgentDetailOut(AgentOut):
    total_runs: int
    successful_runs: int
    last_run_at: datetime | None


class RunAgentIn(BaseModel):
    goal: str
    task_type: str | None = None


@router.get("", response_model=list[AgentOut])
def list_agents(db: Session = Depends(get_db)):
    return list(db.scalars(select(Agent).order_by(Agent.name)))


@router.get("/{name}", response_model=AgentDetailOut)
def get_agent(name: str, db: Session = Depends(get_db)):
    agent = db.scalar(select(Agent).where(Agent.name == name))
    if not agent:
        raise HTTPException(404, f"unknown agent '{name}'")

    total = db.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.agent_id == agent.id)) or 0
    ok = db.scalar(
        select(func.count()).select_from(AgentRun).where(AgentRun.agent_id == agent.id, AgentRun.success.is_(True))
    ) or 0
    last_run = db.scalar(
        select(AgentRun.created_at).where(AgentRun.agent_id == agent.id).order_by(AgentRun.created_at.desc()).limit(1)
    )
    return AgentDetailOut(
        **AgentOut.model_validate(agent).model_dump(),
        total_runs=total,
        successful_runs=ok,
        last_run_at=last_run,
    )


@router.post("/{name}/run")
def trigger_agent(name: str, body: RunAgentIn, db: Session = Depends(get_db)):
    """Synchronous manual trigger — used for admin/testing and dashboard
    actions. The scheduled Scout->Research->CEO loop runs via Celery Beat
    independently of this endpoint."""
    settings = get_settings()
    try:
        result = run_agent(db, name, body.goal, task_type=body.task_type)
    except AgentConfigError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:  # model failures, tool errors etc. surface as 502
        raise HTTPException(502, f"agent run failed: {exc}") from exc
    return {"agent": name, "result": result}


@router.get("/{name}/config")
def get_agent_config(name: str):
    settings = get_settings()
    config_dir, _, _ = resolve_agent_dirs(settings)
    try:
        from app.agents.loader import load_all_agent_configs

        configs = load_all_agent_configs(config_dir)
    except AgentConfigError as exc:
        raise HTTPException(500, str(exc)) from exc
    if name not in configs:
        raise HTTPException(404, f"unknown agent '{name}'")
    cfg = configs[name]
    return {
        "name": cfg.name, "role": cfg.role, "skills": cfg.skills, "tools": cfg.tools,
        "permissions": cfg.permissions, "model_capability": cfg.model_capability,
        "max_steps": cfg.max_steps, "schedule": cfg.schedule,
    }

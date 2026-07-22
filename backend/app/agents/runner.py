"""Wires together config loading + DB + the Agent execution loop.

This is the single entry point used by both Celery tasks (app/tasks.py) and
the API's manual-trigger endpoint (POST /api/agents/{name}/run), so the two
can never drift apart in behavior.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import Agent
from app.agents.loader import AgentConfigError, load_all_agent_configs
from app.config import Settings, get_settings, local_repo_paths
from app.core.context_manager import ContextManager
from app.core.model_router import ModelRouter
from app.db.models import Agent as AgentRow
from app.db.models import Task


def resolve_agent_dirs(settings: Settings) -> tuple[Path, Path, Path]:
    config_dir = Path(settings.agents_config_dir)
    prompts_dir = Path(settings.agents_prompts_dir)
    skills_dir = Path(settings.skills_dir)
    if config_dir.exists():
        return config_dir, prompts_dir, skills_dir
    return local_repo_paths(settings)  # dev fallback outside Docker


def get_or_create_agent_row(db: Session, name: str, role: str, config_path: str) -> AgentRow:
    row = db.scalar(select(AgentRow).where(AgentRow.name == name))
    if row:
        return row
    row = AgentRow(name=name, role=role, config_path=config_path, status="active")
    db.add(row)
    db.flush()
    return row


def run_agent(
    db: Session,
    agent_name: str,
    goal: str,
    *,
    task_type: str | None = None,
    router: ModelRouter | None = None,
    context_manager: ContextManager | None = None,
) -> dict:
    settings = get_settings()
    config_dir, prompts_dir, skills_dir = resolve_agent_dirs(settings)

    configs = load_all_agent_configs(config_dir)
    if agent_name not in configs:
        raise AgentConfigError(f"no such agent '{agent_name}'. known agents: {sorted(configs)}")
    config = configs[agent_name]

    agent_row = get_or_create_agent_row(db, config.name, config.role, str(config_dir / f"{config.name}.yaml"))

    task = Task(type=task_type or f"{agent_name}_run", status="running", payload={"goal": goal}, created_by_agent_id=agent_row.id)
    db.add(task)
    db.flush()

    router = router or ModelRouter()
    context_manager = context_manager or ContextManager(router=router)
    agent = Agent(config, settings=settings, router=router, context_manager=context_manager)

    try:
        result = agent.run(
            db, agent_row=agent_row, task_id=task.id, goal=goal, prompts_dir=prompts_dir, skills_dir=skills_dir,
        )
        task.status = "done"
        task.result = result
        db.commit()
        return result
    except Exception as exc:
        task.status = "failed"
        task.result = {"error": str(exc)}
        db.commit()
        raise

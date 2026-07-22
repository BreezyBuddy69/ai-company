"""Celery tasks — the scheduled heartbeat of the first agent loop:
Scout (finds opportunities) -> Research (scores them) -> CEO (decides).

Celery Beat triggers run_scout_cycle on the schedule in celery_app.py; each
stage chains into the next only when there's real work to do.
"""

from __future__ import annotations

import logging

from app.celery_app import celery_app
from app.config import get_settings
from app.core.tools import read_opportunities
from app.db.session import SessionLocal

logger = logging.getLogger("tasks")


@celery_app.task(name="app.tasks.run_agent_task")
def run_agent_task(agent_name: str, goal: str, task_type: str | None = None) -> dict:
    from app.agents.runner import run_agent  # deferred: avoids import cycles at worker boot

    db = SessionLocal()
    try:
        return run_agent(db, agent_name, goal, task_type=task_type)
    finally:
        db.close()


@celery_app.task(name="app.tasks.run_scout_cycle")
def run_scout_cycle() -> dict:
    settings = get_settings()
    processed = 0
    for keyword in settings.scout_keyword_list:
        goal = (
            f"Search Hacker News and GitHub issues for the keyword '{keyword}' to find one real, "
            "underserved customer pain point that could become a product. If you find a credible one, "
            "call create_opportunity with what you found, citing the source URL. If nothing credible "
            "turns up, just finish."
        )
        try:
            run_agent_task.run(agent_name="scout", goal=goal, task_type="scout_cycle")
            processed += 1
        except Exception:
            logger.exception("scout cycle failed for keyword %s", keyword)

    run_research_cycle.delay()
    return {"keywords_processed": processed}


@celery_app.task(name="app.tasks.run_research_cycle")
def run_research_cycle() -> dict:
    db = SessionLocal()
    try:
        ids = [str(o.id) for o in read_opportunities(db, status="new", limit=10)]
    finally:
        db.close()

    researched = 0
    for opp_id in ids:
        goal = (
            f"Research the opportunity with id {opp_id} (use read_opportunities to see its details). "
            "Assess demand, existing competition, and realistic pricing, then call score_opportunity "
            "with a 0-100 research_score and concise research_notes."
        )
        try:
            run_agent_task.run(agent_name="research", goal=goal, task_type="research_opportunity")
            researched += 1
        except Exception:
            logger.exception("research failed for opportunity %s", opp_id)

    if researched:
        run_ceo_review.delay()
    return {"researched": researched}


@celery_app.task(name="app.tasks.run_ceo_review")
def run_ceo_review() -> dict:
    goal = (
        "Use read_opportunities with status='researched' to see recently scored opportunities. "
        "For each one worth a decision, call decide_opportunity with approved, watch, or rejected "
        "and a short rationale grounded in its research_score and research_notes."
    )
    return run_agent_task.run(agent_name="ceo", goal=goal, task_type="ceo_review")

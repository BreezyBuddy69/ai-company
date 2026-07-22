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

# Every scheduled family competing under core/evolution.py's clone/retire
# cycle. Add a role here once it moves off `status=paused` in db/init.sql.
EVOLVING_FAMILIES = ("scout", "research", "ceo")


def _active_variants(family: str) -> list[str]:
    from app.core.evolution import active_variant_names

    db = SessionLocal()
    try:
        return active_variant_names(db, family)
    finally:
        db.close()


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
    variants = _active_variants("scout")
    processed = 0
    for keyword in settings.scout_keyword_list:
        goal = (
            f"Search Hacker News and GitHub issues for the keyword '{keyword}' to find one real, "
            "underserved customer pain point that could become a product. If you find a credible one, "
            "call create_opportunity with what you found, citing the source URL. If nothing credible "
            "turns up, just finish."
        )
        for variant in variants:
            try:
                run_agent_task.run(agent_name=variant, goal=goal, task_type="scout_cycle")
                processed += 1
            except Exception:
                logger.exception("scout cycle failed for keyword %s variant %s", keyword, variant)

    run_research_cycle.delay()
    return {"keywords_processed": processed, "variants": variants}


@celery_app.task(name="app.tasks.run_research_cycle")
def run_research_cycle() -> dict:
    db = SessionLocal()
    try:
        ids = [str(o.id) for o in read_opportunities(db, status="new", limit=10)]
    finally:
        db.close()

    variants = _active_variants("research")
    researched = 0
    for opp_id in ids:
        goal = (
            f"Research the opportunity with id {opp_id} (use read_opportunities to see its details). "
            "Assess demand, existing competition, and realistic pricing, then call score_opportunity "
            "with a 0-100 research_score and concise research_notes."
        )
        for variant in variants:
            try:
                run_agent_task.run(agent_name=variant, goal=goal, task_type="research_opportunity")
                researched += 1
            except Exception:
                logger.exception("research failed for opportunity %s variant %s", opp_id, variant)

    if researched:
        run_ceo_review.delay()
    return {"researched": researched, "variants": variants}


@celery_app.task(name="app.tasks.run_ceo_review")
def run_ceo_review() -> dict:
    goal = (
        "Use read_opportunities with status='researched' to see recently scored opportunities. "
        "For each one worth a decision, call decide_opportunity with approved, watch, or rejected "
        "and a short rationale grounded in its research_score and research_notes."
    )
    results = []
    for variant in _active_variants("ceo"):
        results.append(run_agent_task.run(agent_name=variant, goal=goal, task_type="ceo_review"))
    return {"results": results}


@celery_app.task(name="app.tasks.run_evolution_cycle")
def run_evolution_cycle() -> dict:
    from app.agents.runner import resolve_agent_dirs
    from app.core.evolution import run_role_competition

    config_dir, _, _ = resolve_agent_dirs(get_settings())
    db = SessionLocal()
    try:
        return {family: run_role_competition(db, config_dir, family) for family in EVOLVING_FAMILIES}
    finally:
        db.close()

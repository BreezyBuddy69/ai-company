"""Celery tasks — the autonomous heartbeat.

Two design choices worth knowing before changing anything here:

**Every agent run is its own queued task.** The cycle tasks dispatch with
`.delay()` and return immediately. They used to call `run_agent_task.run()`,
which executes synchronously in the calling process — so an entire scout cycle
(every keyword × every variant) ran end to end inside one task, occupying one
worker slot. `--concurrency` was therefore decorative: there was never more
than one thing in flight. Dispatching means the worker pool is actually used.

**The pipeline is state-driven, not chained.** Nothing calls "the next stage"
on completion. `run_supervisor` runs on a short beat, reads what the database
actually needs (opportunities without research, research without a decision,
approvals without a spec), and dispatches that. A chained pipeline loses the
rest of the run whenever one link fails; here a failure just means the next
tick sees the same unfinished work and picks it up. Self-healing falls out of
the design instead of being a special case.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.celery_app import celery_app
from app.config import get_settings
from app.core.tools import read_opportunities
from app.db.session import SessionLocal

logger = logging.getLogger("tasks")

# Every scheduled family competing under core/evolution.py's clone/retire
# cycle. Add a role here once it moves off `status=paused` in db/init.sql.
EVOLVING_FAMILIES = ("scout", "research", "ceo", "product")

# How much work the supervisor aims to keep in flight. Below TARGET it tops up;
# it never dispatches past CEILING. These are about the free-model rate limits
# far more than about CPU — an agent run is one HTTP call and a wait, so the
# box is idle either way. Raising CEILING mostly buys more 429s and more
# fallbacks down model_registry.yaml, not more throughput.
TARGET_INFLIGHT = 6
CEILING_INFLIGHT = 16

# Per-stage dispatch caps, so one enormous backlog can't crowd out every other
# stage on a single tick.
MAX_PER_STAGE = 8


def _active_variants(family: str) -> list[str]:
    from app.core.evolution import active_variant_names

    db = SessionLocal()
    try:
        return active_variant_names(db, family)
    finally:
        db.close()


def _inflight() -> int:
    """Tasks currently running or reserved across all workers.

    Celery's inspect talks to workers over the broker and returns None when
    none answer (worker restarting, broker hiccup). Treating that as "0 in
    flight" would dispatch a full batch into a system whose state is unknown,
    so it's treated as "assume busy" instead — a skipped tick costs 10 minutes,
    a stampede costs the day's rate limit."""
    try:
        inspector = celery_app.control.inspect(timeout=2)
        active = inspector.active() or {}
        reserved = inspector.reserved() or {}
    except Exception:
        logger.warning("could not inspect workers; assuming busy this tick")
        return CEILING_INFLIGHT

    if not active and not reserved:
        return CEILING_INFLIGHT

    return sum(len(v) for v in active.values()) + sum(len(v) for v in reserved.values())


def _dispatch(agent_name: str, goal: str, task_type: str) -> bool:
    try:
        run_agent_task.delay(agent_name=agent_name, goal=goal, task_type=task_type)
        return True
    except Exception:
        logger.exception("dispatch failed for %s (%s)", agent_name, task_type)
        return False


@celery_app.task(name="app.tasks.run_agent_task")
def run_agent_task(agent_name: str, goal: str, task_type: str | None = None) -> dict:
    from app.agents.runner import run_agent  # deferred: avoids import cycles at worker boot

    db = SessionLocal()
    try:
        return run_agent(db, agent_name, goal, task_type=task_type)
    finally:
        db.close()


@celery_app.task(name="app.tasks.run_scout_cycle")
def run_scout_cycle(limit: int = MAX_PER_STAGE) -> dict:
    settings = get_settings()
    variants = _active_variants("scout")
    dispatched = 0

    for keyword in settings.scout_keyword_list:
        for variant in variants:
            if dispatched >= limit:
                # Keywords rotate naturally: the supervisor calls this again on
                # the next tick and the loop starts over, so a long keyword list
                # is covered over time instead of dumped at once.
                return {"dispatched": dispatched, "variants": variants, "capped": True}
            goal = (
                f"Search Hacker News, GitHub issues, and Reddit for the keyword '{keyword}' to find one real, "
                "underserved customer pain point that could become a product. If you find a credible one, "
                "call create_opportunity with what you found, citing the source URL. If nothing credible "
                "turns up, just finish."
            )
            if _dispatch(variant, goal, "scout_cycle"):
                dispatched += 1

    return {"dispatched": dispatched, "variants": variants, "capped": False}


@celery_app.task(name="app.tasks.run_research_cycle")
def run_research_cycle(limit: int = MAX_PER_STAGE) -> dict:
    db = SessionLocal()
    try:
        ids = [str(o.id) for o in read_opportunities(db, status="new", limit=limit)]
    finally:
        db.close()

    variants = _active_variants("research")
    dispatched = 0
    for opp_id in ids:
        for variant in variants:
            goal = (
                f"Research the opportunity with id {opp_id} (use read_opportunities to see its details). "
                "Assess demand, existing competition, and realistic pricing, then call score_opportunity "
                "with a 0-100 research_score and concise research_notes."
            )
            if _dispatch(variant, goal, "research_opportunity"):
                dispatched += 1

    return {"dispatched": dispatched, "opportunities": len(ids), "variants": variants}


@celery_app.task(name="app.tasks.run_ceo_review")
def run_ceo_review() -> dict:
    goal = (
        "Use read_opportunities with status='researched' to see recently scored opportunities. "
        "For each one worth a decision, call decide_opportunity with approved, watch, or rejected "
        "and a short rationale grounded in its research_score and research_notes."
    )
    dispatched = sum(_dispatch(v, goal, "ceo_review") for v in _active_variants("ceo"))
    return {"dispatched": dispatched}


@celery_app.task(name="app.tasks.run_product_cycle")
def run_product_cycle(limit: int = MAX_PER_STAGE) -> dict:
    """Turns each approved-but-not-yet-specced opportunity into a Product row.
    No-ops cheaply when nothing new was approved."""
    from app.db.models import Product

    db = SessionLocal()
    try:
        specced = {p.opportunity_id for p in db.scalars(select(Product)) if p.opportunity_id}
        ids = [
            str(o.id)
            for o in read_opportunities(db, status="approved", limit=limit)
            if o.id not in specced
        ]
    finally:
        db.close()

    variants = _active_variants("product")
    dispatched = 0
    for opp_id in ids:
        for variant in variants:
            goal = (
                f"The opportunity with id {opp_id} was approved (use read_opportunities to see its details). "
                "Define an MVP: core features, a rough roadmap, a pricing approach, and a validation plan. Then "
                "call create_product with a name, spec, and pricing capturing all of that."
            )
            if _dispatch(variant, goal, "product_spec"):
                dispatched += 1

    return {"dispatched": dispatched, "opportunities": len(ids), "variants": variants}


@celery_app.task(name="app.tasks.run_supervisor")
def run_supervisor() -> dict:
    """The thing that makes this autonomous: runs on a short beat, works out
    what the company is missing, and fills the worker pool with it.

    Order matters. Work already in the pipeline is finished before new work is
    started — an opportunity nobody researched is worth more than a tenth
    unresearched one. Scout only runs when the later stages are satisfied, or
    the queue fills with leads that never get looked at.
    """
    inflight = _inflight()
    if inflight >= TARGET_INFLIGHT:
        return {"skipped": "busy", "inflight": inflight}

    budget = min(TARGET_INFLIGHT - inflight, CEILING_INFLIGHT - inflight)
    from app.db.models import Product

    db = SessionLocal()
    try:
        pending_research = len(read_opportunities(db, status="new", limit=50))
        pending_decision = len(read_opportunities(db, status="researched", limit=50))
        specced = {p.opportunity_id for p in db.scalars(select(Product)) if p.opportunity_id}
        pending_spec = len([o for o in read_opportunities(db, status="approved", limit=50) if o.id not in specced])
    finally:
        db.close()

    started: dict[str, int] = {}
    if pending_research and budget > 0:
        started["research"] = run_research_cycle(limit=min(budget, MAX_PER_STAGE))["dispatched"]
        budget -= started["research"]
    if pending_decision and budget > 0:
        started["ceo"] = run_ceo_review()["dispatched"]
        budget -= started["ceo"]
    if pending_spec and budget > 0:
        started["product"] = run_product_cycle(limit=min(budget, MAX_PER_STAGE))["dispatched"]
        budget -= started["product"]
    if budget > 0:
        # Nothing downstream is waiting — go find more. This is also what keeps
        # the system moving from a cold start, with an empty database.
        started["scout"] = run_scout_cycle(limit=min(budget, MAX_PER_STAGE))["dispatched"]

    return {
        "inflight_before": inflight,
        "backlog": {
            "awaiting_research": pending_research,
            "awaiting_decision": pending_decision,
            "awaiting_spec": pending_spec,
        },
        "started": started,
    }


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

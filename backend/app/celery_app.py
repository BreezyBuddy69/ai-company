from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery("factory", broker=settings.redis_url, backend=settings.redis_url, include=["app.tasks"])

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_default_queue="default",
)

celery_app.conf.beat_schedule = {
    # The autonomy loop. Every 10 minutes the supervisor reads what the company
    # is short of and tops the worker pool back up to TARGET_INFLIGHT — so the
    # system keeps working without anyone pressing "Run now", and recovers on
    # its own from a worker restart, a broker blip or a stage that died
    # halfway. It is deliberately the only thing driving normal operation:
    # nothing chains stage-to-stage, so no single failure can end a run.
    "supervisor": {
        "task": "app.tasks.run_supervisor",
        "schedule": 600.0,
    },
    # A floor under the supervisor, not the main driver. If the supervisor were
    # ever wedged, this alone still produces new opportunities — a stuck
    # company that keeps looking beats a stuck company that goes quiet.
    "scout-floor": {
        "task": "app.tasks.run_scout_cycle",
        "schedule": crontab(minute=0),
    },
    # Judges each family's active variants on real agent_runs data (see
    # core/evolution.py) — no-ops on any family without enough runs yet, so
    # this is safe to leave on from day one rather than gated on real data
    # existing first.
    "evolution-cycle-daily": {
        "task": "app.tasks.run_evolution_cycle",
        "schedule": crontab(minute=0, hour=3),
    },
}

# Without this a worker prefetches a large batch of tasks up front, so a few
# workers hold the whole queue and the rest idle — which looks exactly like the
# serial behaviour this scheduling was meant to fix. One at a time keeps work
# spread across the pool.
celery_app.conf.worker_prefetch_multiplier = 1
# Agent runs are long HTTP waits, not CPU work, and are safe to redeliver: a
# duplicate run costs one free-model call. Acking late means a worker killed
# mid-run returns its task to the queue instead of silently dropping it.
celery_app.conf.task_acks_late = True
# A hung provider call must not hold a slot forever.
celery_app.conf.task_time_limit = 600
celery_app.conf.task_soft_time_limit = 540

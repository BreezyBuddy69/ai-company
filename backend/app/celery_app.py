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

# Only the first working loop is scheduled automatically in v1. Product/
# Builder/Tester/Marketing/Finance are registered as agents but stay
# `status=paused` (see db/init.sql) until their real logic lands.
celery_app.conf.beat_schedule = {
    "scout-cycle-every-6-hours": {
        "task": "app.tasks.run_scout_cycle",
        "schedule": crontab(minute=0, hour="*/6"),
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

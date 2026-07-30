import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    agents,
    chat,
    dashboard,
    evolution,
    finance,
    health,
    models,
    opportunities,
    questions,
    tasks,
)
from app.config import get_settings
from app.core.auth import require_api_key
from app.db.models import Base
from app.db.session import engine

settings = get_settings()

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="Anvil",
    description="Internal control plane for the agent company — v1 (foundation + CEO/Scout/Research loop).",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    # CORS itself is not the security boundary — the dashboard calls this API
    # cross-origin, so a fixed origin list wouldn't add anything a browser
    # enforces. Actual auth is X-API-Key below (see app/core/auth.py).
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def create_missing_tables() -> None:
    """The schema normally comes from db/init.sql, which Postgres only runs on
    an EMPTY data directory. Every existing deploy already has a populated
    postgres_data volume, so a table added to init.sql would never appear
    there — it would 500 on first use and look like a code bug.

    create_all only issues CREATE for tables that don't exist, so this is a
    no-op on a fresh volume (init.sql got there first) and fills the gap on an
    existing one. Not a migration tool: it will not alter a table that already
    exists with a different shape. Reach for Alembic when a column needs to
    change, rather than growing this."""
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        # A DB that isn't up yet must not stop the API from booting — /health
        # stays reachable so the failure is diagnosable from outside.
        logging.getLogger(__name__).exception("create_all failed; continuing without it")


protected = [Depends(require_api_key)]

app.include_router(health.router)  # unauthenticated on purpose — used for curl/uptime checks
app.include_router(agents.router, dependencies=protected)
app.include_router(opportunities.router, dependencies=protected)
app.include_router(tasks.router, dependencies=protected)
app.include_router(models.router, dependencies=protected)
app.include_router(finance.router, dependencies=protected)
app.include_router(evolution.router, dependencies=protected)
app.include_router(dashboard.router, dependencies=protected)
app.include_router(questions.router, dependencies=protected)
app.include_router(chat.router, dependencies=protected)

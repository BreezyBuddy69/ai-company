import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import agents, dashboard, evolution, finance, health, models, opportunities, tasks
from app.config import get_settings
from app.core.auth import require_api_key

settings = get_settings()

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="Autonomous AI Software Factory",
    description="Internal control plane for the agent company — v1 (foundation + CEO/Scout/Research loop).",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    # No auth exists on this API yet (see DEPLOY.md) — CORS is not a real
    # security boundary here regardless of origin list, so we don't pretend
    # otherwise. The actual boundary is the VPS firewall.
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

protected = [Depends(require_api_key)]

app.include_router(health.router)  # unauthenticated on purpose — used for curl/uptime checks
app.include_router(agents.router, dependencies=protected)
app.include_router(opportunities.router, dependencies=protected)
app.include_router(tasks.router, dependencies=protected)
app.include_router(models.router, dependencies=protected)
app.include_router(finance.router, dependencies=protected)
app.include_router(evolution.router, dependencies=protected)
app.include_router(dashboard.router, dependencies=protected)

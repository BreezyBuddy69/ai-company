import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import agents, dashboard, evolution, finance, health, models, opportunities, tasks
from app.config import get_settings

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

app.include_router(health.router)
app.include_router(agents.router)
app.include_router(opportunities.router)
app.include_router(tasks.router)
app.include_router(models.router)
app.include_router(finance.router)
app.include_router(evolution.router)
app.include_router(dashboard.router)

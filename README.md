# Autonomous AI Software Factory — v1

An autonomous AI company that runs on a single Ubuntu VPS: it finds real
customer problems, validates them, and (starting from v1) decides whether
they're worth building — powered entirely by free OpenRouter models. See
`ARCHITECTURE.md` for the full design and `DEPLOY.md` for going live on a
real VPS. This document is the fast path to running it.

## What's actually running in v1

A working **Scout → Research → CEO** loop:

1. **Scout** searches Hacker News + GitHub Issues (both free, keyless) for
   pain-point keywords and records credible findings as opportunities.
2. **Research** skeptically scores each opportunity (demand, competition,
   pricing).
3. **CEO** approves/watches/rejects each researched opportunity with a
   rationale, respecting the company's non-negotiable rules (never spam,
   scam, manipulate, or fake metrics).

Everything is visible and human-overridable from the dashboard. Five more
agents (Product, Builder, Tester, Marketing, Finance) are registered and
config-ready but intentionally stubbed — see `ARCHITECTURE.md`.

## Quickstart

There are two compose files — pick based on where you're running this:

**Deploying on the shared halovisionai.cloud VPS** (the real target — same
Traefik pattern as every other site in this repo): use `docker-compose.yml`
as-is. Full walkthrough, port/subdomain assignments, and the security
hardening step in `DEPLOY.md`.

**Testing locally** (laptop/dev machine with Docker Desktop, no Traefik):

```bash
cd ai-company
cp .env.example .env
# edit .env: at minimum set OPENROUTER_API_KEY (free, no card needed —
# https://openrouter.ai/keys)

docker compose -f docker-compose.local.yml up -d --build
```

Then:
- Dashboard: http://localhost:3000
- API docs (Swagger): http://localhost:8000/docs
- n8n: http://localhost:5678

The Scout cycle runs automatically every 6 hours via Celery Beat. To trigger
it immediately instead of waiting:

```bash
docker compose -f docker-compose.local.yml exec backend python -c "from app.tasks import run_scout_cycle; run_scout_cycle.run()"
```

## Quickstart without Docker (this repo's dev machine has none installed)

Proves the real, external parts of the Scout step — live Hacker News /
GitHub calls, and a live free-model call if you have a key — without
needing Postgres/Redis running at all:

```bash
cd ai-company/backend
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate on Linux/Mac
pip install -r requirements.txt
cd ..
python scripts/dev_dry_run.py "expensive manual spreadsheet"
```

## Running the test suite

```bash
cd ai-company/backend
pip install -r requirements.txt
pytest
```

Covers: the model router's free-first enforcement and failure-fallback
chain, the context manager's short-term/long-term/compression logic, the
agent config loader (including validating every config actually checked
into `agents/configs/`), the agent loop's JSON-action parsing, and one live
integration test against the real Hacker News API (skips gracefully if this
environment has no network access).

## Project layout

See `ARCHITECTURE.md` for the full breakdown. Quick map:

- `docker-compose.yml` — the whole stack, wired for the shared
  halovisionai.cloud VPS (Traefik routing, see `DEPLOY.md`)
- `docker-compose.local.yml` — same stack, plain localhost ports, no
  Traefik — for testing on a machine without it
- `model_registry.yaml` — the free-first model routing table
- `db/init.sql` — full schema
- `backend/app/` — FastAPI + Celery + the agent framework
- `agents/configs/` + `agents/prompts/` — every agent, config-driven
- `skills/` — reusable skill files agents load selectively
- `dashboard/` — Next.js control-plane UI
- `scripts/` — backup + local dry-run tooling

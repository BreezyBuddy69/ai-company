# Architecture — Autonomous AI Software Factory (v1)

v1 scope: the full infrastructure foundation + one real, working agent loop
(Scout → Research → CEO). See "Deliberately not in v1" at the bottom for
what's intentionally deferred, and why.

## System diagram

```
                    ┌─────────────────────────┐
                    │        Dashboard         │  Next.js, dark, DESIGN.md tokens
                    │  (browser, client-side)  │  polls the API — no WebSocket
                    └────────────┬─────────────┘
                                 │ HTTP
                    ┌────────────▼─────────────┐
                    │      FastAPI backend      │  /api/agents /api/opportunities
                    │                           │  /api/tasks /api/models/usage
                    └───┬───────────────────┬───┘  /api/finance /api/evolution
                        │                   │
              ┌─────────▼───────┐   ┌───────▼────────┐
              │  Celery worker   │   │   Celery beat   │  schedules run_scout_cycle
              │  (runs agents)   │◄──┤  (cron trigger) │  every 6h; chains into
              └─────────┬────────┘   └────────────────┘  research → ceo
                        │
        ┌───────────────┼───────────────────┐
        │               │                   │
┌───────▼──────┐ ┌───────▼────────┐ ┌────────▼───────┐
│ agents/base.py│ │ context_manager │ │  model_router   │
│  (ReAct loop) │ │ (token budget)  │ │ (free-first,    │
└───────┬───────┘ └───────┬────────┘ │  fallback chain)│
        │                 │          └────────┬────────┘
        │         ┌───────▼────────┐          │
        │         │  memory.py      │          │ HTTPS
        │         │  (pgvector +    │          ▼
        │         │  local embed)   │   OpenRouter (free models only)
        │                 │
        └────────►┌───────▼────────────────────────┐
                   │  PostgreSQL 16 + pgvector        │
                   │  agents, tasks, agent_runs,       │
                   │  memories, knowledge_*, opportu-  │
                   │  nities, products, evolution_*,   │
                   │  model_usage_log, finance_*        │
                   └────────────────────────────────────┘

              n8n (notifications/webhooks — v1: provisioned, not yet wired)
```

## Why these choices

**FastAPI + Celery + Postgres/pgvector + Redis**, per the original brief.
Nothing swapped — these are the right tools for a small, self-hosted,
always-on backend with background agent work.

**Local embeddings via `fastembed` (ONNX runtime), not `sentence-transformers`
(PyTorch).** Same model — `sentence-transformers/all-MiniLM-L6-v2` — but
fastembed avoids pulling in PyTorch (multi-GB even CPU-only), which matters
on a resource-constrained single VPS. Zero-cost either way; this is purely a
footprint decision.

**No Prometheus/Grafana stack in v1.** Two more always-on containers is real
RAM on a small VPS, and the project brief explicitly prioritizes minimal
resource use. `/health` endpoints + Docker healthchecks + structured JSON
logs cover v1. If/when real monitoring is needed, Uptime-Kuma (a single
lightweight container) is the natural next step — not the full stack.

**A single generic agent loop (`agents/base.py`), not one Python module per
agent.** The brief's requirement is explicit: "adding 100 agents should
require only adding configuration files." `base.Agent` runs a bounded
ReAct-style loop (think → pick a tool from the YAML allow-list → act →
repeat, up to `max_steps`) driven entirely by each agent's YAML config +
prompt file. CEO, Scout, and Research differ only in their config/prompt —
proving the framework, not hand-rolled orchestration per agent.

**Model router is free-first by construction, not by convention.**
`model_registry.yaml`'s `router.max_cost_per_1k_tokens_usd: 0.0` is enforced
in `ModelRouter.candidates()` — a model with `cost > 0` is filtered out
before it can ever be called, regardless of its priority. See
`test_paid_model_never_selected_even_though_highest_priority` in
`backend/tests/test_model_router.py`.

**Evolution engine ships scoring + schema, not automatic mutation.** An
automatic clone/archive/mutate cycle needs real weeks of revenue and usage
data to make sound decisions on. Faking that data to make the demo look more
finished would violate the brief's own "never fake metrics" rule. v1 ships
the weighted scoring formulas (`core/evolution.py`), the `evolution_history`
table with `parent_id` (ready for a real generational tree), and a
manually-triggered scoring endpoint. The automatic cycle is a real Phase-2
feature once there's real data to evolve against.

## The first agent loop, concretely

1. **Scout** (`agents/scout.yaml` + `prompts/scout_system.md`) searches
   Hacker News (Algolia API, free, keyless) and GitHub Issues (free,
   keyless — optionally higher rate limit with `GITHUB_TOKEN`) for
   configured pain-point keywords, and calls `create_opportunity` for
   anything credible it finds.
2. **Research** re-examines each new opportunity skeptically (most should
   score 30-60, not 90+), and calls `score_opportunity`.
3. **CEO** reviews researched opportunities against the company's
   non-negotiable rules (never spam/scam/manipulate/fake metrics) and calls
   `decide_opportunity` with approved/watch/rejected + rationale.

Celery Beat triggers step 1 every 6 hours; each stage chains into the next
only when there's real work. A human can also override any decision from
the dashboard's Opportunities page — that calls the same
`decide_opportunity` function directly, bypassing the CEO agent.

## Token optimization (`core/context_manager.py`)

Three layers, matching the brief exactly:
- **Short-term**: last N agent_runs for the active task, in Redis (24h TTL).
- **Long-term**: pgvector cosine-similarity search over `memories`.
- **Compressed summaries**: once the short-term buffer exceeds
  `SHORT_TERM_BUFFER_MAX_RUNS` (default 8), it's summarized by a free model
  into one dense paragraph, stored as a `summary` memory, and the raw buffer
  is cleared. No agent call ever sends an unbounded history.

## Agent framework (`agents/loader.py`, `agents/base.py`)

An agent config (`agents/configs/<name>.yaml`) declares: `name`, `role`,
`system_prompt` (path), `skills` (which `/skills/*/SKILL.md` files get
injected), `tools` (allow-list from `core/tools.TOOL_REGISTRY`),
`permissions`, `memory_scope`, and `max_steps`. `loader.py` scans the whole
directory at call time — there is no agent registry to update in code.
Dropping a new YAML + prompt file is the entire integration surface for a
new agent.

## Deliberately not in v1

- **Product/Builder/Tester/Marketing/Finance real logic** — registered as
  agents with config+prompt stubs and `status=paused`, but not wired into
  the Celery schedule. Their prompts say so explicitly if manually
  triggered. Phase 2: wire Product to fire when an opportunity is
  `approved`, Builder when Product finishes a spec, etc.
- **Stripe/PayPal integration** — `finance_transactions` table and
  `/api/finance/summary` exist; nothing writes to that table yet because
  there's no product generating real transactions yet.
- **Real n8n workflows** — the service is in `docker-compose.yml` and ready
  to use; no workflow JSON is deployed into it yet.
- **Automatic evolution mutation cycle** — see above.
- **Actual VPS deployment** — this repo was built without VPS access; see
  `DEPLOY.md` for the exact steps to run it on the shared halovisionai.cloud
  Hostinger VPS, matching the Traefik pattern the rest of this repo's sites
  already use (`docker-compose.yml` has the routing/port assignment).
- **API authentication** — the FastAPI backend and dashboard have none yet.
  `docker-compose.yml` ships commented-out Traefik basicauth middleware for
  both, ready to enable with one `htpasswd` command — see `DEPLOY.md` step 5.
  Not enabled by default because it needs a password only you should set.

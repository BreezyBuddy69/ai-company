# Architecture — Anvil (v1)

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

**Evolution engine runs a real clone/retire cycle, judged only on objective
data.** Same-role agents compete under a shared name family (`scout`,
`scout-g2`, `scout-g3`, ...) — `app/tasks.py`'s scheduled cycles now run
every active variant in a family, not one hardcoded name, so variants
actually accumulate their own `agent_runs`. Daily (`run_evolution_cycle`,
also triggerable via `POST /api/evolution/compete/{family}`),
`core/evolution.run_role_competition` scores each variant purely from
`agent_runs` aggregates (success rate, latency, cost — never an LLM's
opinion of "quality", which would just be a guess dressed up as a metric):
exactly one variant bootstraps a mutated sibling once it's proven itself;
two or more retires the worst and clones the best, keeping the population
size constant. Below `MIN_RUNS_FOR_COMPETITION` (5) runs, it's a no-op —
the "never fake metrics" rule holds by refusing to judge on too little data,
not by refusing to judge automatically at all. `record_revenue`
(`core/tools.py`) clones a product's originating agent (`Product.
created_by_agent_id`) the moment its first revenue lands. Product scoring
(`score_product`) stays manual/caller-supplied — there's still no product
live to generate that data from.

## The first agent loop, concretely

1. **Scout** (`agents/scout.yaml` + `prompts/scout_system.md`) searches
   Hacker News (Algolia API, free, keyless), GitHub Issues (free,
   keyless — optionally higher rate limit with `GITHUB_TOKEN`), and Reddit
   (public `search.json`, free, keyless) for configured pain-point keywords,
   and calls `create_opportunity` for anything credible it finds. For the
   rare source that's JS-only or bot-walled and worth reading in full, it
   also has `scrape_url` — a self-hosted headless-Chrome tool (see
   docker-compose.yml's opt-in `browserless` service) rather than a paid
   scraping API.
2. **Research** re-examines each new opportunity skeptically (most should
   score 30-60, not 90+), and calls `score_opportunity`.
3. **CEO** reviews researched opportunities against the company's
   non-negotiable rules (never spam/scam/manipulate/fake metrics) and calls
   `decide_opportunity` with approved/watch/rejected + rationale.
4. **Product** picks up each newly-approved opportunity and calls
   `create_product` with an MVP spec (core features, roadmap, pricing,
   validation plan) — a real `products` row, not just a memory note. Runs
   automatically right after every CEO review (`run_product_cycle`).

Celery Beat triggers step 1 every hour; each stage chains into the next
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

- ~~**Product real logic**~~ — done: wired into the automatic pipeline (see
  above), `EVOLVING_FAMILIES` now includes it, and it has a real tool
  (`create_product`) instead of a memory-only stub.
- **Builder/Tester/Marketing/Finance real logic** — still registered as
  agents with config+prompt stubs and `status=paused`. Deliberately not
  built yet: Builder in particular implies real external side effects
  (pushing code somewhere, most likely a new GitHub repo per product) that
  need their own scoping conversation, not a default. Their prompts say so
  explicitly if manually triggered.
- **Stripe/PayPal integration** — `finance_transactions` table and
  `/api/finance/summary` exist; nothing writes to that table yet because
  there's no product generating real transactions yet.
- **Real n8n workflows** — the service is in `docker-compose.yml` and ready
  to use; no workflow JSON is deployed into it yet.
- ~~**Automatic evolution mutation cycle**~~ — done, see above. Only wired
  for `scout`/`research`/`ceo` (`app/tasks.EVOLVING_FAMILIES`) since those are
  the only roles actually running; add a role there once it leaves
  `status=paused`.
- **Actual VPS deployment** — this repo was built without VPS access; see
  `DEPLOY.md` for the exact steps to run it on the shared halovisionai.cloud
  Hostinger VPS, matching the Traefik pattern the rest of this repo's sites
  already use (`docker-compose.yml` has the routing/port assignment).
- ~~**API authentication**~~ — done: backend requires `X-API-Key`
  (`app/core/auth.py`), dashboard requires HTTP Basic Auth
  (`dashboard/middleware.ts`), plus an optional third layer,
  `ALLOWED_IPS` — a comma-separated IP allowlist checked before the API key,
  for pinning access to a known static IP. See `DEPLOY.md` step 5.
- ~~**Dashboard: activity visibility + evolution UI**~~ — done: the Overview
  page now polls `/api/logs` every 5s into a live activity feed (with a
  pulsing "is anything actually running right now" indicator), and the
  Evolution page renders each competing family as a head-to-head arena
  (`GET /api/evolution/families` / `core/evolution.family_snapshot`) instead
  of a bare history table — two variants, their live scores, and which one
  is currently ahead.

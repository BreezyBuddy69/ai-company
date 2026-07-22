-- Autonomous AI Software Factory — initial schema
-- Runs automatically via postgres docker-entrypoint-initdb.d on first container start.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto; -- gen_random_uuid()

-- ============================================================
-- Agents & execution log
-- ============================================================

CREATE TABLE agents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT UNIQUE NOT NULL,         -- matches agents/configs/<name>.yaml
    role            TEXT NOT NULL,
    config_path     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'archived')),
    generation      INT NOT NULL DEFAULT 1,
    parent_agent_id UUID REFERENCES agents(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tasks (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type                TEXT NOT NULL,             -- e.g. 'scout_cycle', 'research_opportunity', 'ceo_review'
    status              TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'done', 'failed')),
    payload             JSONB NOT NULL DEFAULT '{}',
    result              JSONB,
    created_by_agent_id UUID REFERENCES agents(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE agent_runs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id     UUID NOT NULL REFERENCES agents(id),
    task_id      UUID REFERENCES tasks(id),
    input        JSONB NOT NULL DEFAULT '{}',
    output       JSONB,
    model_used   TEXT,
    tokens_in    INT DEFAULT 0,
    tokens_out   INT DEFAULT 0,
    latency_ms   INT,
    cost_usd     NUMERIC(10, 6) DEFAULT 0,
    success      BOOLEAN NOT NULL DEFAULT true,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_agent_runs_agent_id ON agent_runs(agent_id);
CREATE INDEX idx_agent_runs_task_id ON agent_runs(task_id);
CREATE INDEX idx_agent_runs_created_at ON agent_runs(created_at DESC);

-- ============================================================
-- Memory (long-term, pgvector) — dim 384 = sentence-transformers/all-MiniLM-L6-v2
-- ============================================================

CREATE TABLE memories (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content          TEXT NOT NULL,
    embedding        vector(384),
    memory_type      TEXT NOT NULL CHECK (memory_type IN ('decision', 'failure', 'success', 'experiment', 'summary', 'fact')),
    source_agent_id  UUID REFERENCES agents(id),
    metadata         JSONB NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_memories_embedding ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_memories_type ON memories(memory_type);

-- ============================================================
-- Knowledge graph
-- ============================================================

CREATE TABLE knowledge_nodes (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type       TEXT NOT NULL CHECK (type IN ('problem', 'market', 'product', 'strategy', 'company', 'failure', 'success')),
    name       TEXT NOT NULL,
    metadata   JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (type, name)
);

CREATE TABLE knowledge_edges (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_node_id UUID NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    to_node_id   UUID NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    relation     TEXT NOT NULL,               -- e.g. 'related_market', 'competitor', 'suggested_strategy'
    weight       REAL NOT NULL DEFAULT 1.0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_knowledge_edges_from ON knowledge_edges(from_node_id);
CREATE INDEX idx_knowledge_edges_to ON knowledge_edges(to_node_id);

-- ============================================================
-- Opportunities (Scout/Research/CEO output)
-- ============================================================

CREATE TABLE opportunities (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    problem               TEXT NOT NULL,
    target_customer       TEXT,
    existing_solutions    JSONB NOT NULL DEFAULT '[]',
    pain_level            INT CHECK (pain_level BETWEEN 1 AND 10),
    possible_product      TEXT,
    revenue_potential     TEXT,
    source                TEXT NOT NULL,       -- 'hackernews' | 'github_issues' | 'reddit' | 'producthunt' | ...
    source_url            TEXT,
    research_score        NUMERIC(5, 2),       -- filled in by Research agent
    research_notes        TEXT,
    status                TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'researched', 'watch', 'approved', 'rejected', 'launched')),
    decision_rationale     TEXT,
    discovered_by_agent_id UUID REFERENCES agents(id),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_opportunities_status ON opportunities(status);

-- ============================================================
-- Products & experiments
-- ============================================================

CREATE TABLE products (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id      UUID REFERENCES opportunities(id),
    name                TEXT NOT NULL,
    spec                JSONB NOT NULL DEFAULT '{}',
    status              TEXT NOT NULL DEFAULT 'idea' CHECK (status IN ('idea', 'mvp', 'launched', 'paused', 'archived')),
    pricing             JSONB NOT NULL DEFAULT '{}',
    repo_url            TEXT,
    -- Agent cloned the moment this product records its first revenue —
    -- see core/evolution.py's clone-on-revenue trigger.
    created_by_agent_id UUID REFERENCES agents(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE experiments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id  UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    hypothesis  TEXT NOT NULL,
    result      TEXT,
    metric      TEXT,
    metric_value NUMERIC,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- Evolution engine
-- ============================================================

CREATE TABLE evolution_history (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type    TEXT NOT NULL CHECK (entity_type IN ('agent', 'product')),
    entity_id      UUID NOT NULL,
    generation     INT NOT NULL DEFAULT 1,
    score          NUMERIC(6, 3),
    score_breakdown JSONB NOT NULL DEFAULT '{}',
    parent_id      UUID REFERENCES evolution_history(id),
    mutation_notes TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_evolution_history_entity ON evolution_history(entity_type, entity_id);

-- ============================================================
-- Model usage & finance
-- ============================================================

CREATE TABLE model_usage_log (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name TEXT NOT NULL,
    provider   TEXT NOT NULL DEFAULT 'openrouter',
    agent_id   UUID REFERENCES agents(id),
    tokens_in  INT DEFAULT 0,
    tokens_out INT DEFAULT 0,
    latency_ms INT,
    success    BOOLEAN NOT NULL,
    cost_usd   NUMERIC(10, 6) DEFAULT 0,
    error      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_model_usage_model ON model_usage_log(model_name);
CREATE INDEX idx_model_usage_created_at ON model_usage_log(created_at DESC);

CREATE TABLE finance_transactions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id  UUID REFERENCES products(id),
    type        TEXT NOT NULL CHECK (type IN ('revenue', 'cost')),
    amount_usd  NUMERIC(12, 2) NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- Seed: register the v1 agents (idempotent)
-- ============================================================

INSERT INTO agents (name, role, config_path, status) VALUES
    ('ceo', 'CEO Brain — strategy, priorities, resource allocation', 'agents/configs/ceo.yaml', 'active'),
    ('scout', 'Scout — finds real-world opportunities', 'agents/configs/scout.yaml', 'active'),
    ('research', 'Research — validates and ranks opportunities', 'agents/configs/research.yaml', 'active'),
    ('product', 'Product — MVP specs, roadmap, pricing', 'agents/configs/product.yaml', 'paused'),
    ('builder', 'Builder — ships websites/SaaS/APIs', 'agents/configs/builder.yaml', 'paused'),
    ('tester', 'Tester — bugs, security, usability, performance', 'agents/configs/tester.yaml', 'paused'),
    ('marketing', 'Marketing — SEO, landing pages, acquisition', 'agents/configs/marketing.yaml', 'paused'),
    ('finance', 'Finance — revenue, cost, CAC, LTV', 'agents/configs/finance.yaml', 'paused')
ON CONFLICT (name) DO NOTHING;

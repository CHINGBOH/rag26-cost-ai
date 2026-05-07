-- Canonical event ledger foundation for Phase 6.

CREATE TABLE IF NOT EXISTS event_ledger (
    event_id           BIGSERIAL PRIMARY KEY,
    aggregate_type     TEXT NOT NULL,
    aggregate_id       TEXT NOT NULL,
    event_type         TEXT NOT NULL,
    run_id             TEXT,
    session_id         TEXT,
    request_id         TEXT,
    trace_id           TEXT,
    channel            TEXT NOT NULL,
    actor_service      TEXT NOT NULL,
    actor_kind         TEXT NOT NULL,
    outcome_family     TEXT,
    outcome_code       TEXT,
    quality            TEXT,
    learning_eligible  BOOLEAN NOT NULL DEFAULT FALSE,
    payload            JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    idempotency_key    TEXT,
    schema_version     TEXT NOT NULL DEFAULT 'phase6.v1',
    topology_version   TEXT NOT NULL DEFAULT 'phase6.v1',
    policy_version     TEXT NOT NULL DEFAULT 'phase6.v1',
    prompt_version     TEXT NOT NULL DEFAULT 'phase6.v1',
    CONSTRAINT event_ledger_idempotency_unique UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_event_ledger_aggregate
    ON event_ledger(aggregate_type, aggregate_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_event_ledger_run_id
    ON event_ledger(run_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_event_ledger_session_id
    ON event_ledger(session_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_event_ledger_event_type
    ON event_ledger(event_type, occurred_at DESC);

CREATE TABLE IF NOT EXISTS agent_run_projection (
    run_id             TEXT PRIMARY KEY,
    session_id         TEXT,
    query              TEXT NOT NULL,
    query_type         TEXT,
    channel            TEXT NOT NULL,
    status             TEXT NOT NULL,
    outcome_family     TEXT NOT NULL,
    outcome_code       TEXT NOT NULL,
    quality            TEXT NOT NULL,
    learning_eligible  BOOLEAN NOT NULL DEFAULT FALSE,
    early_exit         BOOLEAN NOT NULL DEFAULT FALSE,
    refused            BOOLEAN NOT NULL DEFAULT FALSE,
    iterations         INTEGER NOT NULL DEFAULT 0,
    chunks_count       INTEGER NOT NULL DEFAULT 0,
    tools_used         JSONB NOT NULL DEFAULT '[]'::jsonb,
    evaluation         JSONB NOT NULL DEFAULT '{}'::jsonb,
    runtime            JSONB NOT NULL DEFAULT '{}'::jsonb,
    answer_preview     TEXT,
    request_id         TEXT,
    trace_id           TEXT,
    started_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    latency_ms         INTEGER NOT NULL DEFAULT 0,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_run_projection_completed
    ON agent_run_projection(completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_run_projection_quality
    ON agent_run_projection(quality, completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_run_projection_learning
    ON agent_run_projection(learning_eligible, completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_run_projection_session
    ON agent_run_projection(session_id, completed_at DESC);

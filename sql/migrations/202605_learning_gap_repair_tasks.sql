-- DB-backed repair tasks for repeated live-retest knowledge gaps.

CREATE TABLE IF NOT EXISTS knowledge_gap_repair_tasks (
    id BIGSERIAL PRIMARY KEY,
    gap_key TEXT NOT NULL REFERENCES knowledge_gaps(gap_key) ON DELETE CASCADE,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'in_progress', 'blocked', 'resolved', 'cancelled')),
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    latest_evidence_ids BIGINT[] NOT NULL DEFAULT '{}',
    issue_number INT,
    issue_url TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_gap_repair_tasks_gap_status
    ON knowledge_gap_repair_tasks(gap_key, status);

CREATE INDEX IF NOT EXISTS idx_gap_repair_tasks_status_created
    ON knowledge_gap_repair_tasks(status, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_gap_repair_tasks_active_gap_type
    ON knowledge_gap_repair_tasks(gap_key, task_type)
    WHERE status IN ('open', 'in_progress');

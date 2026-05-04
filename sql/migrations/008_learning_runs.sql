-- Learning runs tracking table — Issue #96 Layer 2
-- Tracks all learning loop executions (scheduled, manual, auto-threshold, feedback-analysis)

CREATE TABLE IF NOT EXISTS learning_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    run_type TEXT NOT NULL,    -- 'scheduled' | 'manual' | 'auto_threshold' | 'feedback_analysis'
    result JSONB,              -- {signals_count, severity_score, problems_count, status, error}
    status TEXT NOT NULL,      -- 'running' | 'completed' | 'failed'
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT learning_runs_run_type_valid CHECK (run_type IN ('scheduled', 'manual', 'auto_threshold', 'feedback_analysis'))
);

CREATE INDEX IF NOT EXISTS idx_learning_runs_ts ON learning_runs(ts DESC);
CREATE INDEX IF NOT EXISTS idx_learning_runs_run_type ON learning_runs(run_type);
CREATE INDEX IF NOT EXISTS idx_learning_runs_status ON learning_runs(status);
CREATE INDEX IF NOT EXISTS idx_learning_runs_run_id ON learning_runs(run_id);

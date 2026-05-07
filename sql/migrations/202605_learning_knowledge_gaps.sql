-- Persisted knowledge gap state for Issue #96 learning loop.

CREATE TABLE IF NOT EXISTS knowledge_gaps (
  id                BIGSERIAL PRIMARY KEY,
  gap_key           TEXT NOT NULL UNIQUE,
  problem_id        TEXT,
  description       TEXT NOT NULL,
  source            TEXT NOT NULL
                      CHECK (source IN (
                        'run', 'problem', 'feedback', 'failure',
                        'repeat_question', 'contract_violation', 'topology'
                      )),
  affected_route    TEXT,
  query_text        TEXT,
  status            TEXT NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open', 'in_progress', 'resolved', 'blocked')),
  quality           TEXT,
  resolution_plan   TEXT,
  related_issue_url TEXT,
  confidence        REAL NOT NULL DEFAULT 0.0,
  metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_status ON knowledge_gaps(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_updated_at ON knowledge_gaps(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_problem_id ON knowledge_gaps(problem_id);

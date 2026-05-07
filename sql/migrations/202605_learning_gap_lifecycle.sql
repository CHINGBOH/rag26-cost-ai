-- Extend knowledge_gaps into a first-class lifecycle entity.

ALTER TABLE knowledge_gaps
  ADD COLUMN IF NOT EXISTS scope_type TEXT NOT NULL DEFAULT 'project'
    CHECK (scope_type IN ('user', 'agent', 'project', 'global')),
  ADD COLUMN IF NOT EXISTS scope_id TEXT NOT NULL DEFAULT 'project',
  ADD COLUMN IF NOT EXISTS cluster_id TEXT,
  ADD COLUMN IF NOT EXISTS cause_type TEXT,
  ADD COLUMN IF NOT EXISTS priority INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS owner TEXT,
  ADD COLUMN IF NOT EXISTS linked_event_id BIGINT REFERENCES improvement_events(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS reopen_count INT NOT NULL DEFAULT 0;

UPDATE knowledge_gaps
SET scope_type = COALESCE(scope_type, 'project'),
    scope_id = COALESCE(NULLIF(scope_id, ''), 'project'),
    cluster_id = COALESCE(cluster_id, gap_key),
    first_seen_at = COALESCE(first_seen_at, created_at, NOW()),
    last_seen_at = COALESCE(last_seen_at, updated_at, created_at, NOW()),
    priority = COALESCE(priority, 0),
    reopen_count = COALESCE(reopen_count, 0)
WHERE TRUE;

CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_scope ON knowledge_gaps(scope_type, scope_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_cluster ON knowledge_gaps(cluster_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_priority ON knowledge_gaps(priority DESC, last_seen_at DESC);

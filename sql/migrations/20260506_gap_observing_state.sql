-- Add observing lifecycle semantics to knowledge_gaps.

ALTER TABLE knowledge_gaps
  DROP CONSTRAINT IF EXISTS knowledge_gaps_status_check;

ALTER TABLE knowledge_gaps
  ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS observation_until TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS last_reopened_at TIMESTAMPTZ;

ALTER TABLE knowledge_gaps
  ADD CONSTRAINT knowledge_gaps_status_check
  CHECK (status IN ('open', 'in_progress', 'observing', 'resolved', 'blocked'));

UPDATE knowledge_gaps
SET verified_at = COALESCE(verified_at, resolved_at)
WHERE TRUE;

CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_observation_until
  ON knowledge_gaps(observation_until)
  WHERE status = 'observing';

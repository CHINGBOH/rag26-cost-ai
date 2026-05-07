-- Projection contract extensions for Phase 6 canonical interaction runs.

ALTER TABLE conversation_turns
  ADD COLUMN IF NOT EXISTS run_id TEXT,
  ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'sync',
  ADD COLUMN IF NOT EXISTS outcome_code TEXT,
  ADD COLUMN IF NOT EXISTS quality TEXT,
  ADD COLUMN IF NOT EXISTS early_exit BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_conv_run_id ON conversation_turns(run_id);
CREATE INDEX IF NOT EXISTS idx_conv_channel ON conversation_turns(channel, ts DESC);

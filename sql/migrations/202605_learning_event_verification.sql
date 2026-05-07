-- Learning improvement event verification metadata
-- Keeps improvement_events aligned with executor/history APIs.

ALTER TABLE improvement_events
  ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS verification_result JSONB;

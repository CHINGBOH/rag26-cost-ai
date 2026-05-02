-- Migration 004: conversation_turns + rag_feedback extensions
-- Run: psql $DATABASE_URL -f sql/migrations/004_conversation_turns.sql

-- ── Conversation turns (paired user+assistant per turn) ─────────────────────
CREATE TABLE IF NOT EXISTS conversation_turns (
    id              BIGSERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL,
    turn_index      INTEGER NOT NULL,
    user_content    TEXT NOT NULL,
    assistant_content TEXT,
    message_id      TEXT,
    source          TEXT DEFAULT 'agent',   -- 'agent' | 'guide'
    status          TEXT DEFAULT 'completed' CHECK (status IN ('completed','cancelled','error')),
    latency_ms      INTEGER,
    ts              DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (session_id, turn_index)
);

CREATE INDEX IF NOT EXISTS idx_conv_session ON conversation_turns(session_id, turn_index DESC);
CREATE INDEX IF NOT EXISTS idx_conv_ts      ON conversation_turns(ts DESC);

-- ── Extend rag_feedback with detailed rating fields ──────────────────────────
ALTER TABLE rag_feedback ADD COLUMN IF NOT EXISTS overall_rating    SMALLINT CHECK (overall_rating BETWEEN 1 AND 5);
ALTER TABLE rag_feedback ADD COLUMN IF NOT EXISTS rating_relevance  SMALLINT CHECK (rating_relevance BETWEEN 1 AND 5);
ALTER TABLE rag_feedback ADD COLUMN IF NOT EXISTS rating_accuracy   SMALLINT CHECK (rating_accuracy BETWEEN 1 AND 5);
ALTER TABLE rag_feedback ADD COLUMN IF NOT EXISTS rating_completeness SMALLINT CHECK (rating_completeness BETWEEN 1 AND 5);
ALTER TABLE rag_feedback ADD COLUMN IF NOT EXISTS praise            TEXT;
ALTER TABLE rag_feedback ADD COLUMN IF NOT EXISTS criticism         TEXT;
ALTER TABLE rag_feedback ADD COLUMN IF NOT EXISTS suggestion        TEXT;
ALTER TABLE rag_feedback ADD COLUMN IF NOT EXISTS tags              TEXT[];  -- e.g. ['数据过时','缺少依据']

-- Prevent duplicate feedback for same message (upsert-safe)
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'rag_feedback_session_message_unique'
  ) THEN
    ALTER TABLE rag_feedback ADD CONSTRAINT rag_feedback_session_message_unique
      UNIQUE (session_id, message_id);
  END IF;
END $$;

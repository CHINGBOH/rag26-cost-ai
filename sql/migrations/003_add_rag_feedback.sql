-- Migration 003: rag_feedback table for learning loop persistence
-- Run: psql $DATABASE_URL -f sql/migrations/003_add_rag_feedback.sql

CREATE TABLE IF NOT EXISTS rag_feedback (
    id          BIGSERIAL PRIMARY KEY,
    ts          DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    session_id  TEXT NOT NULL,
    message_id  TEXT NOT NULL,
    rating      SMALLINT NOT NULL CHECK (rating IN (-1, 1)),
    comment     TEXT,
    query       TEXT,
    answer_summary TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rag_feedback_session ON rag_feedback(session_id);
CREATE INDEX IF NOT EXISTS idx_rag_feedback_rating  ON rag_feedback(rating);
CREATE INDEX IF NOT EXISTS idx_rag_feedback_ts      ON rag_feedback(ts DESC);

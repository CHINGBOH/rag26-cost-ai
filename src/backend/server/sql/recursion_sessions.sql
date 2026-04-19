-- PostgreSQL schema for XState session persistence
-- Phase 4: XState Persistence

CREATE TABLE IF NOT EXISTS recursion_sessions (
    session_id UUID PRIMARY KEY,
    original_query TEXT NOT NULL,
    current_state VARCHAR(50) NOT NULL,
    current_depth INTEGER DEFAULT 0,
    session_data JSONB NOT NULL,
    snapshot JSONB,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recursion_sessions_state
    ON recursion_sessions(current_state);

CREATE INDEX IF NOT EXISTS idx_recursion_sessions_updated_at
    ON recursion_sessions(updated_at DESC);

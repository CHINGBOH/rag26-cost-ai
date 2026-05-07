-- First-class evidence and transition records for DB-driven learning gap workbench.

CREATE TABLE IF NOT EXISTS knowledge_gap_evidence (
    id BIGSERIAL PRIMARY KEY,
    gap_key TEXT NOT NULL REFERENCES knowledge_gaps(gap_key) ON DELETE CASCADE,
    evidence_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    source_run_id TEXT,
    consultation_run_id TEXT,
    session_id TEXT,
    endpoint TEXT,
    query_text TEXT,
    answer_preview TEXT,
    chunks_count INT,
    refused BOOLEAN,
    generic_answer BOOLEAN,
    quality TEXT,
    outcome_code TEXT,
    confidence NUMERIC,
    decision TEXT,
    decision_reason TEXT,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gap_evidence_gap_created
    ON knowledge_gap_evidence(gap_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_gap_evidence_type_created
    ON knowledge_gap_evidence(evidence_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_gap_evidence_consultation_run
    ON knowledge_gap_evidence(consultation_run_id);

CREATE TABLE IF NOT EXISTS knowledge_gap_transitions (
    id BIGSERIAL PRIMARY KEY,
    gap_key TEXT NOT NULL REFERENCES knowledge_gaps(gap_key) ON DELETE CASCADE,
    from_status TEXT,
    to_status TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT,
    evidence_id BIGINT REFERENCES knowledge_gap_evidence(id) ON DELETE SET NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gap_transitions_gap_time
    ON knowledge_gap_transitions(gap_key, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_gap_transitions_status_time
    ON knowledge_gap_transitions(to_status, occurred_at DESC);

INSERT INTO knowledge_gap_evidence (
    gap_key, evidence_type, actor, source_run_id, consultation_run_id, session_id,
    endpoint, query_text, answer_preview, chunks_count, refused, generic_answer,
    quality, outcome_code, confidence, decision, decision_reason, raw_payload, created_at
)
SELECT
    kg.gap_key,
    CASE
        WHEN COALESCE(kg.metadata->>'triage_mode', '') = 'live_consultation'
        THEN 'live_retest'
        ELSE 'legacy_metadata'
    END,
    COALESCE(NULLIF(kg.metadata->>'triage_actor', ''), kg.owner, 'migration'),
    kg.problem_id,
    kg.metadata->'triage_evidence'->>'run_id',
    kg.metadata->'triage_evidence'->>'session_id',
    kg.metadata->'triage_evidence'->>'endpoint',
    COALESCE(kg.metadata->'triage_evidence'->>'query', kg.query_text),
    COALESCE(kg.metadata->'triage_evidence'->>'answer_preview', kg.metadata->>'answer_preview'),
    CASE
        WHEN COALESCE(kg.metadata->'triage_evidence'->>'chunks_count', kg.metadata->>'chunks_count') ~ '^[0-9]+$'
        THEN COALESCE(kg.metadata->'triage_evidence'->>'chunks_count', kg.metadata->>'chunks_count')::INT
        ELSE NULL
    END,
    COALESCE(
        CASE
            WHEN lower(COALESCE(kg.metadata->'triage_evidence'->>'refused', '')) IN ('true', 'false')
            THEN (kg.metadata->'triage_evidence'->>'refused')::BOOLEAN
            ELSE NULL
        END,
        CASE
            WHEN lower(COALESCE(kg.metadata->>'refused', '')) IN ('true', 'false')
            THEN (kg.metadata->>'refused')::BOOLEAN
            ELSE NULL
        END
    ),
    CASE
        WHEN lower(COALESCE(kg.metadata->'triage_evidence'->>'generic_answer', '')) IN ('true', 'false')
        THEN (kg.metadata->'triage_evidence'->>'generic_answer')::BOOLEAN
        ELSE NULL
    END,
    COALESCE(kg.metadata->'triage_evidence'->>'quality', kg.quality),
    kg.metadata->'triage_evidence'->>'outcome_code',
    CASE
        WHEN COALESCE(kg.metadata->'triage_evidence'->>'confidence', '') ~ '^-?[0-9]+(\.[0-9]+)?$'
        THEN (kg.metadata->'triage_evidence'->>'confidence')::NUMERIC
        ELSE NULL
    END,
    kg.metadata->>'triage_action',
    kg.metadata->>'triage_reason',
    jsonb_build_object('legacy_metadata', kg.metadata #- '{runtime,api_key}'),
    COALESCE(kg.verified_at, kg.updated_at, NOW())
FROM knowledge_gaps kg
WHERE (
        kg.metadata ? 'triage_evidence'
        OR kg.metadata ? 'triage_action'
        OR kg.verified_at IS NOT NULL
      )
  AND NOT EXISTS (
        SELECT 1
        FROM knowledge_gap_evidence e
        WHERE e.gap_key = kg.gap_key
          AND e.evidence_type IN ('legacy_metadata', 'live_retest')
      );

INSERT INTO knowledge_gap_transitions (
    gap_key, from_status, to_status, action, actor, reason, evidence_id, occurred_at
)
SELECT
    kg.gap_key,
    NULL,
    kg.status,
    COALESCE(kg.metadata->>'triage_action', 'legacy_import'),
    COALESCE(NULLIF(kg.metadata->>'triage_actor', ''), kg.owner, 'migration'),
    COALESCE(kg.metadata->>'triage_reason', kg.resolution_plan, 'Imported current gap lifecycle state'),
    e.id,
    COALESCE(kg.verified_at, kg.updated_at, NOW())
FROM knowledge_gaps kg
LEFT JOIN LATERAL (
    SELECT id
    FROM knowledge_gap_evidence
    WHERE gap_key = kg.gap_key
    ORDER BY created_at DESC, id DESC
    LIMIT 1
) e ON TRUE
WHERE kg.status IN ('in_progress', 'observing', 'resolved', 'blocked')
  AND NOT EXISTS (
        SELECT 1
        FROM knowledge_gap_transitions t
        WHERE t.gap_key = kg.gap_key
      );

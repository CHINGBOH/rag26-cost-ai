-- Issue #69 Phase A: PG-backed ingest job state machine
-- Replaces the fragile JSON-file state with queryable, concurrent-safe tables.

CREATE TABLE IF NOT EXISTS ingest_jobs (
    job_id          VARCHAR(64)  PRIMARY KEY,
    doc_id          VARCHAR(255),
    file_name       VARCHAR(500),
    file_path       VARCHAR(1000),
    file_size       BIGINT,
    mime            VARCHAR(120),
    status          VARCHAR(40)  NOT NULL DEFAULT 'queued',
        -- queued | extracting | chunking | embedding | indexing | done | failed
    phase           VARCHAR(60),
    progress_pct    SMALLINT     DEFAULT 0,
    error           TEXT,
    -- counters (per phase, written incrementally)
    blocks_total    INTEGER      DEFAULT 0,
    chunks_pg       INTEGER      DEFAULT 0,
    vectors_qdrant  INTEGER      DEFAULT 0,
    triples_neo4j   INTEGER      DEFAULT 0,
    ocr_pages       INTEGER      DEFAULT 0,
    text_chars      INTEGER      DEFAULT 0,
    extractor       VARCHAR(40),  -- pymupdf | pdfplumber | ocr_paddle | pandas | text
    duration_ms     INTEGER,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP,
    metadata        JSONB        DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_status   ON ingest_jobs(status);
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_created  ON ingest_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_doc      ON ingest_jobs(doc_id);

-- Idempotency / resumability log: each successful write inserts one row.
-- Worker restart skips rows already present.
CREATE TABLE IF NOT EXISTS ingest_write_log (
    job_id   VARCHAR(64)  NOT NULL,
    phase    VARCHAR(60)  NOT NULL,        -- e.g. 'pg_chunk' | 'qdrant_vec' | 'neo4j_tri'
    key      VARCHAR(255) NOT NULL,        -- e.g. chunk_index as text, or qdrant point id
    written_at TIMESTAMP  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (job_id, phase, key)
);
CREATE INDEX IF NOT EXISTS idx_ingest_write_log_job ON ingest_write_log(job_id);

-- updated_at trigger
CREATE OR REPLACE FUNCTION ingest_jobs_touch_updated()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ingest_jobs_updated ON ingest_jobs;
CREATE TRIGGER trg_ingest_jobs_updated
    BEFORE UPDATE ON ingest_jobs
    FOR EACH ROW EXECUTE FUNCTION ingest_jobs_touch_updated();

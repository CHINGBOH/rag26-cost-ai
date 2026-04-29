-- Issue #69 Phase D: blindspot table.
-- Tracks pages where the extractor saw images/charts but couldn't read
-- the textual content (sparse text, no OCR available, table extraction
-- failed, etc). Used by the agent to honestly disclose data gaps.

CREATE TABLE IF NOT EXISTS ingest_blindspots (
    id           BIGSERIAL PRIMARY KEY,
    job_id       VARCHAR(64) REFERENCES ingest_jobs(job_id) ON DELETE CASCADE,
    doc_id       VARCHAR(64) NOT NULL,
    file_name    VARCHAR(512) NOT NULL,
    page         INTEGER NOT NULL,
    kind         VARCHAR(32) NOT NULL,    -- chart | figure | table | scanned
    reason       VARCHAR(256),
    bbox         JSONB,                   -- {x0,y0,x1,y1} when known
    image_count  INTEGER DEFAULT 0,
    text_chars   INTEGER DEFAULT 0,
    detected_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (doc_id, page, kind)
);

CREATE INDEX IF NOT EXISTS idx_blindspots_doc ON ingest_blindspots (doc_id);
CREATE INDEX IF NOT EXISTS idx_blindspots_job ON ingest_blindspots (job_id);

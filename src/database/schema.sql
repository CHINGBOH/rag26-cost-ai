-- RAG Dashboard — 权威 PostgreSQL Schema（基于实际运行状态 2026-04）
-- 注意：sql/migrations/001_pgvector_single_db.sql 定义了 document_id INT FK，
--       但实际运行表由 ocr_text_to_pg.py 建立，使用 doc_id TEXT。
--       本文件以实际运行版为准。

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── document_registry ──────────────────────────────────────────────
-- 注意：实际表名为 document_registry（不是 documents）
CREATE TABLE IF NOT EXISTS document_registry (
    id          SERIAL PRIMARY KEY,
    file_name   VARCHAR(500) NOT NULL,
    file_path   VARCHAR(1000),
    doc_type    VARCHAR(50) DEFAULT 'general',
    doc_code    VARCHAR(64) UNIQUE,
    period      VARCHAR(7),
    total_pages INTEGER,
    status      VARCHAR(50) DEFAULT 'imported',
    created_at  TIMESTAMP DEFAULT NOW()
);

-- ── text_chunks ──────────────────────────────────────────────────────
-- 实际运行版：doc_id TEXT + file_name TEXT（非 document_id INT FK）
CREATE TABLE IF NOT EXISTS text_chunks (
    id          SERIAL PRIMARY KEY,
    doc_id      TEXT NOT NULL,
    file_name   TEXT,
    chunk_index INTEGER,
    content     TEXT NOT NULL,
    page_number INTEGER,
    section     TEXT,
    chunk_type  VARCHAR(30) DEFAULT 'article',
    doc_type    VARCHAR(50),
    metadata    JSONB DEFAULT '{}',
    embedding   vector(1024),
    tsv         tsvector GENERATED ALWAYS AS (
                    to_tsvector('simple', content)
                ) STORED,
    confidence  FLOAT DEFAULT 1.0,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tc_doc_id    ON text_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_tc_file      ON text_chunks(file_name);
CREATE INDEX IF NOT EXISTS idx_tc_embedding ON text_chunks USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tc_tsv       ON text_chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS idx_tc_content   ON text_chunks USING gin (content gin_trgm_ops);

-- ── price_records ─────────────────────────────────────────────────
-- 注意：实际列名与 sql/migrations/001_pgvector_single_db.sql 不同，
--       以下是运行中的实际列名（由 ocr_json_to_pg.py 创建）
CREATE TABLE IF NOT EXISTS price_records (
    id                  SERIAL PRIMARY KEY,
    doc_id              TEXT,
    file_name           TEXT,
    material_name       VARCHAR(200) NOT NULL,
    specification       VARCHAR(200),          -- 旧名: spec
    unit                VARCHAR(20),
    price_tax_included  DECIMAL(12,2),         -- 旧名: price
    price_tax_excluded  DECIMAL(12,2),
    region              VARCHAR(50) DEFAULT '深圳',
    year_month          VARCHAR(7) NOT NULL,   -- 旧名: period，格式 'YYYY-MM'
    page_number         INTEGER,
    category            VARCHAR(100),
    metadata            JSONB,                 -- 旧名: source_row
    embedding           vector(1024),
    confidence          FLOAT DEFAULT 1.0,
    -- 以下字段由 002_full_schema.sql 添加
    price_formula       TEXT,
    agency_code         VARCHAR(50),
    seq_no              INTEGER,
    source_doc          VARCHAR(500),
    created_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pr_period    ON price_records(year_month);
CREATE INDEX IF NOT EXISTS idx_pr_category  ON price_records(category);
CREATE INDEX IF NOT EXISTS idx_pr_name_trgm ON price_records USING gin (material_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_pr_spec_trgm ON price_records USING gin (specification gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_pr_embedding ON price_records USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_pr_period    ON price_records(period);
CREATE INDEX IF NOT EXISTS idx_pr_category  ON price_records(category);
CREATE INDEX IF NOT EXISTS idx_pr_name_trgm ON price_records USING gin (material_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_pr_embedding ON price_records USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

-- ── fee_rates ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fee_rates (
    id               SERIAL PRIMARY KEY,
    doc_id           TEXT,
    doc_code         VARCHAR(64),
    document_id      INTEGER,
    standard_year    VARCHAR(4),
    fee_name         TEXT NOT NULL,
    fee_category     VARCHAR(50),
    base_formula     TEXT,
    rate_min         NUMERIC(8,4),
    rate_max         NUMERIC(8,4),
    rate_recommended NUMERIC(8,4),
    calc_base        TEXT,
    applicable_scope TEXT,
    page_number      INTEGER,
    source_text      TEXT,
    embedding        vector(1024),
    confidence       FLOAT DEFAULT 1.0,
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fr_year      ON fee_rates(standard_year);
CREATE INDEX IF NOT EXISTS idx_fr_category  ON fee_rates(fee_category);
CREATE INDEX IF NOT EXISTS idx_fr_name_trgm ON fee_rates USING gin (fee_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_fr_embedding ON fee_rates USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

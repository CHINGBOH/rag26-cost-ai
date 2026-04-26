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

-- ── trend_points / trend_relations ──────────────────────────────────
-- 用于存储走势图恢复后的时序点与相邻月关系，PostgreSQL 作为主存。
CREATE TABLE IF NOT EXISTS trend_points (
    id                    SERIAL PRIMARY KEY,
    series_key            TEXT NOT NULL,
    material_name         VARCHAR(200) NOT NULL,
    normalized_material   VARCHAR(200) NOT NULL,
    year_month            VARCHAR(7) NOT NULL,
    unit                  VARCHAR(20),
    value                 NUMERIC(12,4) NOT NULL,
    source_doc_id         TEXT,
    source_file_name      TEXT,
    source_chart_page     INTEGER,
    source_table_page     INTEGER,
    source_price_record_id INTEGER,
    source_method         VARCHAR(50) DEFAULT 'derived_from_price_records',
    metadata              JSONB DEFAULT '{}',
    created_at            TIMESTAMP DEFAULT NOW(),
    UNIQUE (series_key, year_month)
);

CREATE INDEX IF NOT EXISTS idx_tp_series     ON trend_points(series_key, year_month);
CREATE INDEX IF NOT EXISTS idx_tp_material   ON trend_points(normalized_material, year_month);
CREATE INDEX IF NOT EXISTS idx_tp_doc        ON trend_points(source_doc_id);

CREATE TABLE IF NOT EXISTS trend_relations (
    id                    SERIAL PRIMARY KEY,
    series_key            TEXT NOT NULL,
    from_point_id         INTEGER NOT NULL REFERENCES trend_points(id) ON DELETE CASCADE,
    to_point_id           INTEGER NOT NULL REFERENCES trend_points(id) ON DELETE CASCADE,
    from_year_month       VARCHAR(7) NOT NULL,
    to_year_month         VARCHAR(7) NOT NULL,
    unit                  VARCHAR(20),
    delta_value           NUMERIC(12,4) NOT NULL,
    delta_percent         NUMERIC(12,4),
    trend_direction       VARCHAR(10) NOT NULL,
    months_apart          INTEGER NOT NULL DEFAULT 1,
    metadata              JSONB DEFAULT '{}',
    created_at            TIMESTAMP DEFAULT NOW(),
    UNIQUE (from_point_id, to_point_id)
);

CREATE INDEX IF NOT EXISTS idx_tr_series     ON trend_relations(series_key, from_year_month, to_year_month);
CREATE INDEX IF NOT EXISTS idx_tr_from_point ON trend_relations(from_point_id);
CREATE INDEX IF NOT EXISTS idx_tr_to_point   ON trend_relations(to_point_id);

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

-- ── concept graph + parent/multi-vector ─────────────────────────────
CREATE TABLE IF NOT EXISTS canonical_concepts (
    id              SERIAL PRIMARY KEY,
    concept_type    VARCHAR(50) NOT NULL,
    concept_name    TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    aliases         TEXT[] DEFAULT '{}',
    preferred_route VARCHAR(50) DEFAULT 'hybrid_search',
    metadata        JSONB DEFAULT '{}',
    embedding       vector(1024),
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE (concept_type, normalized_name)
);

CREATE INDEX IF NOT EXISTS idx_cc_type_name ON canonical_concepts(concept_type, concept_name);
CREATE INDEX IF NOT EXISTS idx_cc_name_trgm ON canonical_concepts USING gin (concept_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_cc_embedding ON canonical_concepts USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

CREATE TABLE IF NOT EXISTS concept_relations (
    id                SERIAL PRIMARY KEY,
    source_concept_id INTEGER NOT NULL REFERENCES canonical_concepts(id) ON DELETE CASCADE,
    target_concept_id INTEGER NOT NULL REFERENCES canonical_concepts(id) ON DELETE CASCADE,
    relation_kind     VARCHAR(50) NOT NULL,
    relation_weight   NUMERIC(8,4) DEFAULT 1.0,
    metadata          JSONB DEFAULT '{}',
    created_at        TIMESTAMP DEFAULT NOW(),
    UNIQUE (source_concept_id, target_concept_id, relation_kind)
);

CREATE INDEX IF NOT EXISTS idx_cr_source ON concept_relations(source_concept_id);
CREATE INDEX IF NOT EXISTS idx_cr_target ON concept_relations(target_concept_id);

CREATE TABLE IF NOT EXISTS concept_evidence_links (
    id                 SERIAL PRIMARY KEY,
    concept_id         INTEGER NOT NULL REFERENCES canonical_concepts(id) ON DELETE CASCADE,
    evidence_kind      VARCHAR(40) NOT NULL,
    source_table       VARCHAR(40) NOT NULL,
    source_id          BIGINT NOT NULL DEFAULT 0,
    doc_id             TEXT NOT NULL DEFAULT '',
    file_name          TEXT NOT NULL DEFAULT '',
    page_number        INTEGER NOT NULL DEFAULT 0,
    parent_doc_id      TEXT NOT NULL DEFAULT '',
    parent_page_number INTEGER NOT NULL DEFAULT 0,
    chunk_id           INTEGER NOT NULL DEFAULT 0,
    link_score         NUMERIC(8,4) DEFAULT 1.0,
    metadata           JSONB DEFAULT '{}',
    created_at         TIMESTAMP DEFAULT NOW(),
    UNIQUE (concept_id, evidence_kind, source_table, source_id, doc_id, page_number, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_cel_concept ON concept_evidence_links(concept_id, evidence_kind);
CREATE INDEX IF NOT EXISTS idx_cel_doc_page ON concept_evidence_links(doc_id, page_number);
CREATE INDEX IF NOT EXISTS idx_cel_source ON concept_evidence_links(source_table, source_id);

CREATE TABLE IF NOT EXISTS chunk_vector_views (
    id          SERIAL PRIMARY KEY,
    chunk_id    INTEGER NOT NULL REFERENCES text_chunks(id) ON DELETE CASCADE,
    view_type   VARCHAR(40) NOT NULL,
    view_text   TEXT NOT NULL,
    embedding   vector(1024),
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (chunk_id, view_type)
);

CREATE INDEX IF NOT EXISTS idx_cvv_chunk ON chunk_vector_views(chunk_id, view_type);
CREATE INDEX IF NOT EXISTS idx_cvv_view_text_trgm ON chunk_vector_views USING gin (view_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_cvv_embedding ON chunk_vector_views USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

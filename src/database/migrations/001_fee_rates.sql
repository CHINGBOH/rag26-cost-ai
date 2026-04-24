-- Migration 001: 创建 fee_rates 表
-- 此前从未创建，导致每次 agent 请求都报 relation "fee_rates" does not exist
-- 幂等，可重复执行

-- 确保扩展存在（需 superuser 或 pg_extension 权限）
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS fee_rates (
    id               SERIAL PRIMARY KEY,
    doc_id           TEXT,               -- tools.py _query_structured_tables 查此列
    doc_code         VARCHAR(64),        -- 如 'fee_rate_2023'
    document_id      INTEGER,            -- 可空，与 documents.id 对应
    standard_year    VARCHAR(4),         -- '2023' | '2025'
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

CREATE INDEX IF NOT EXISTS idx_fr_year
    ON fee_rates(standard_year);
CREATE INDEX IF NOT EXISTS idx_fr_category
    ON fee_rates(fee_category);
CREATE INDEX IF NOT EXISTS idx_fr_name_trgm
    ON fee_rates USING gin (fee_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_fr_embedding
    ON fee_rates USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

DO $$ BEGIN
  RAISE NOTICE 'fee_rates ready. cols: %',
    (SELECT string_agg(column_name, ', ' ORDER BY ordinal_position)
     FROM information_schema.columns WHERE table_name='fee_rates');
END $$;

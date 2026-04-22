-- ============================================================================
-- 001_pgvector_single_db.sql
-- PG 单库改造：pgvector + 结构化价格表 + 文本 chunks
-- ============================================================================

-- 1. 启用扩展
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. 创建 documents 表（如果不存在）
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    file_name VARCHAR(500) NOT NULL,
    file_path VARCHAR(1000),
    doc_type VARCHAR(50) DEFAULT 'price_info',
    period VARCHAR(7),  -- '2026-01'
    total_pages INTEGER,
    status VARCHAR(50) DEFAULT 'imported',
    created_at TIMESTAMP DEFAULT NOW()
);

-- 3. 结构化价格记录（核心新表）
CREATE TABLE IF NOT EXISTS price_records (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    period VARCHAR(7) NOT NULL,              -- '2026-01'
    category VARCHAR(100),                   -- '建筑材料'|'安装材料'|'市场劳务'|'装配式构件'
    material_name VARCHAR(200) NOT NULL,
    spec VARCHAR(200),                       -- 'P.O 42.5R袋装'
    unit VARCHAR(20),                        -- 't'|'m³'|'m'|'kg'|'工日'
    price DECIMAL(12,2),
    page_number INTEGER,
    source_row JSONB,                        -- OCR 原始行（零损失保留）
    embedding vector(1024),                  -- bge-m3: material_name + spec 向量
    created_at TIMESTAMP DEFAULT NOW()
);

-- 4. 非结构化文本 chunks（替代 Qdrant 持久化）
CREATE TABLE IF NOT EXISTS text_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER,
    content TEXT NOT NULL,
    page_number INTEGER,
    period VARCHAR(7),
    doc_type VARCHAR(50),
    embedding vector(1024),                  -- bge-m3 文本向量
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('simple', content)
    ) STORED,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 5. 索引
CREATE INDEX IF NOT EXISTS idx_pr_period ON price_records(period);
CREATE INDEX IF NOT EXISTS idx_pr_category ON price_records(category);
CREATE INDEX IF NOT EXISTS idx_pr_material_trgm ON price_records USING gin(material_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_pr_spec_trgm ON price_records USING gin(spec gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_pr_embedding ON price_records USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_tc_period ON text_chunks(period);
CREATE INDEX IF NOT EXISTS idx_tc_doc_type ON text_chunks(doc_type);
CREATE INDEX IF NOT EXISTS idx_tc_embedding ON text_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_tc_tsv ON text_chunks USING GIN (tsv);

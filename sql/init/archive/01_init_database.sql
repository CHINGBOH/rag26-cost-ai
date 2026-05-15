-- RAG系统数据库初始化脚本 - 单库改造后
-- PostgreSQL + pgvector 作为唯一数据库

-- 启用必要的扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================
-- 文档管理相关表
-- ============================================

-- 文档表
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    file_name VARCHAR(500) NOT NULL,
    file_path VARCHAR(1000),
    doc_type VARCHAR(50) DEFAULT 'general',
    period VARCHAR(7),
    total_pages INTEGER,
    status VARCHAR(50) DEFAULT 'imported',
    created_at TIMESTAMP DEFAULT NOW()
);

-- 文本块表（替代 Qdrant 持久化 + 全文检索）
CREATE TABLE IF NOT EXISTS text_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER,
    content TEXT NOT NULL,
    page_number INTEGER,
    period VARCHAR(7),
    doc_type VARCHAR(50),
    embedding vector(1024),
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('simple', content)
    ) STORED,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 结构化价格记录表
CREATE TABLE IF NOT EXISTS price_records (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    period VARCHAR(7) NOT NULL,
    category VARCHAR(100),
    material_name VARCHAR(200) NOT NULL,
    spec VARCHAR(200),
    unit VARCHAR(20),
    price DECIMAL(12,2),
    page_number INTEGER,
    source_row JSONB,
    embedding vector(1024),
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- 知识实体相关表（替代 Neo4j）
-- ============================================

-- 知识实体表
CREATE TABLE IF NOT EXISTS knowledge_entities (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    entity_name VARCHAR(255) NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    entity_category VARCHAR(100),
    description TEXT,
    properties JSONB DEFAULT '{}',
    source_type VARCHAR(50),
    source_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    confidence FLOAT,
    related_entities TEXT[],
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uk_entity_name_type UNIQUE (entity_name, entity_type)
);

-- 实体关系表
CREATE TABLE IF NOT EXISTS entity_relations (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    source_entity_id INTEGER NOT NULL REFERENCES knowledge_entities(id) ON DELETE CASCADE,
    target_entity_id INTEGER NOT NULL REFERENCES knowledge_entities(id) ON DELETE CASCADE,
    relation_type VARCHAR(100) NOT NULL,
    relation_strength FLOAT DEFAULT 1.0,
    properties JSONB DEFAULT '{}',
    source_type VARCHAR(50),
    source_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    confidence FLOAT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT chk_relation_strength CHECK (relation_strength >= 0 AND relation_strength <= 1),
    CONSTRAINT uq_source_target_relation UNIQUE (source_entity_id, target_entity_id, relation_type)
);

-- ============================================
-- 查询与系统相关表
-- ============================================

-- 查询历史表
CREATE TABLE IF NOT EXISTS query_history (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    query_text TEXT NOT NULL,
    query_type VARCHAR(50) DEFAULT 'text',
    query_embedding JSONB,
    top_k INTEGER DEFAULT 10,
    filters JSONB DEFAULT '{}',
    rerank_enabled BOOLEAN DEFAULT FALSE,
    results JSONB,
    result_count INTEGER,
    execution_time_ms INTEGER,
    vector_search_time_ms INTEGER,
    rerank_time_ms INTEGER,
    user_id VARCHAR(255),
    session_id VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT chk_query_type CHECK (query_type IN ('text', 'table', 'hybrid'))
);

-- 向量化任务表
CREATE TABLE IF NOT EXISTS embedding_tasks (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    task_type VARCHAR(50) NOT NULL,
    entity_type VARCHAR(50),
    entity_id INTEGER,
    model_name VARCHAR(100) NOT NULL,
    model_version VARCHAR(50),
    embedding_dimension INTEGER,
    status VARCHAR(50) DEFAULT 'pending',
    progress INTEGER DEFAULT 0,
    error_message TEXT,
    embedding_id VARCHAR(255),
    vector_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT chk_task_status CHECK (status IN ('pending', 'processing', 'completed', 'failed'))
);

-- 系统配置表
CREATE TABLE IF NOT EXISTS system_config (
    id SERIAL PRIMARY KEY,
    config_key VARCHAR(255) UNIQUE NOT NULL,
    config_value TEXT NOT NULL,
    config_type VARCHAR(50) DEFAULT 'string',
    description TEXT,
    is_secret BOOLEAN DEFAULT FALSE,
    is_readonly BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 创建索引
-- ============================================

-- documents 索引
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(doc_type);
CREATE INDEX IF NOT EXISTS idx_documents_created ON documents(created_at);

-- text_chunks 索引
CREATE INDEX IF NOT EXISTS idx_tc_document ON text_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_tc_period ON text_chunks(period);
CREATE INDEX IF NOT EXISTS idx_tc_doc_type ON text_chunks(doc_type);
CREATE INDEX IF NOT EXISTS idx_tc_embedding ON text_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_tc_tsv ON text_chunks USING GIN (tsv);

-- price_records 索引
CREATE INDEX IF NOT EXISTS idx_pr_period ON price_records(period);
CREATE INDEX IF NOT EXISTS idx_pr_category ON price_records(category);
CREATE INDEX IF NOT EXISTS idx_pr_material_trgm ON price_records USING gin(material_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_pr_spec_trgm ON price_records USING gin(spec gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_pr_embedding ON price_records USING hnsw (embedding vector_cosine_ops);

-- knowledge_entities 索引
CREATE INDEX IF NOT EXISTS idx_entities_type ON knowledge_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_category ON knowledge_entities(entity_category);
CREATE INDEX IF NOT EXISTS idx_entities_source ON knowledge_entities(source_document_id);

-- entity_relations 索引
CREATE INDEX IF NOT EXISTS idx_relations_source ON entity_relations(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON entity_relations(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_relations_type ON entity_relations(relation_type);

-- query_history 索引
CREATE INDEX IF NOT EXISTS idx_queries_user ON query_history(user_id);
CREATE INDEX IF NOT EXISTS idx_queries_session ON query_history(session_id);
CREATE INDEX IF NOT EXISTS idx_queries_created ON query_history(created_at);

-- embedding_tasks 索引
CREATE INDEX IF NOT EXISTS idx_embedding_tasks_status ON embedding_tasks(status);
CREATE INDEX IF NOT EXISTS idx_embedding_tasks_entity ON embedding_tasks(entity_id, entity_type);

-- ============================================
-- 插入初始配置数据
-- ============================================

INSERT INTO system_config (config_key, config_value, config_type, description) VALUES
('embedding.default_model', 'BAAI/bge-m3', 'string', '默认embedding模型'),
('embedding.dimension', '1024', 'integer', 'embedding向量维度'),
('embedding.batch_size', '32', 'integer', 'embedding批处理大小'),
('rerank.enabled', 'true', 'boolean', '是否启用rerank'),
('rerank.model', 'BAAI/bge-reranker-large', 'string', 'rerank模型'),
('recall.top_k', '20', 'integer', '召回top_k数量'),
('recall.final_top_k', '10', 'integer', '最终返回top_k数量'),
('cache.enabled', 'true', 'boolean', '是否启用缓存'),
('cache.ttl', '3600', 'integer', '缓存TTL（秒）'),
('concurrency.max_workers', '4', 'integer', '最大工作线程数'),
('concurrency.queue_size', '100', 'integer', '任务队列大小')
ON CONFLICT (config_key) DO NOTHING;

-- ============================================
-- 创建触发器函数
-- ============================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 为含 updated_at 的表创建触发器
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'knowledge_entities') THEN
        CREATE TRIGGER update_entities_updated_at BEFORE UPDATE ON knowledge_entities
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'entity_relations') THEN
        CREATE TRIGGER update_entity_relations_updated_at BEFORE UPDATE ON entity_relations
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'embedding_tasks') THEN
        CREATE TRIGGER update_embedding_tasks_updated_at BEFORE UPDATE ON embedding_tasks
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'system_config') THEN
        CREATE TRIGGER update_system_config_updated_at BEFORE UPDATE ON system_config
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

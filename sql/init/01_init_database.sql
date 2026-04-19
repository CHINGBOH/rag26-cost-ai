-- RAG系统数据库初始化脚本
-- PostgreSQL数据库结构设计

-- 启用必要的扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- 中文全文搜索支持

-- ============================================
-- 文档管理相关表
-- ============================================

-- 文档表
CREATE TABLE documents (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    file_name VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    file_size BIGINT,
    file_hash VARCHAR(64),
    page_count INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'pending',
    processing_status VARCHAR(50) DEFAULT 'pending',
    
    -- OCR相关信息
    ocr_completed BOOLEAN DEFAULT FALSE,
    ocr_result_path TEXT,
    ocr_confidence FLOAT,
    
    -- 元数据
    document_type VARCHAR(100),
    language VARCHAR(10) DEFAULT 'zh',
    encoding VARCHAR(20) DEFAULT 'utf-8',
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processed_at TIMESTAMP WITH TIME ZONE,
    
    -- 索引
    CONSTRAINT chk_status CHECK (status IN ('pending', 'processing', 'completed', 'failed'))
);

-- 文档块表
CREATE TABLE document_chunks (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    
    -- 分块信息
    chunk_index INTEGER NOT NULL,
    chunk_type VARCHAR(50) DEFAULT 'text',  -- text, table, image
    
    -- 内容
    content TEXT NOT NULL,
    content_length INTEGER,
    content_hash VARCHAR(64),
    
    -- 位置信息
    page_number INTEGER,
    start_position INTEGER,
    end_position INTEGER,
    
    -- 向量化信息
    embedding_id VARCHAR(255),
    embedding_model VARCHAR(100),
    embedding_dimension INTEGER,
    embedding_created_at TIMESTAMP WITH TIME ZONE,
    
    -- 元数据
    metadata JSONB DEFAULT '{}',
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- 约束
    CONSTRAINT chk_chunk_type CHECK (chunk_type IN ('text', 'table', 'image', 'header', 'footer'))
);

-- 表格数据表
CREATE TABLE tables_data (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id INTEGER REFERENCES document_chunks(id) ON DELETE CASCADE,
    
    -- 表格基本信息
    table_name VARCHAR(255),
    table_caption TEXT,
    row_count INTEGER,
    column_count INTEGER,
    
    -- 表格内容
    html_content TEXT,
    markdown_content TEXT,
    json_data JSONB,
    
    -- 表格识别信息
    confidence FLOAT,
    recognition_method VARCHAR(50),
    
    -- 元数据
    page_number INTEGER,
    bbox JSONB,
    metadata JSONB DEFAULT '{}',
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 知识实体相关表
-- ============================================

-- 知识实体表
CREATE TABLE knowledge_entities (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    
    -- 实体基本信息
    entity_name VARCHAR(255) NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    entity_category VARCHAR(100),
    description TEXT,
    
    -- 实体属性
    properties JSONB DEFAULT '{}',
    
    -- 来源信息
    source_type VARCHAR(50),  -- manual, extracted, inferred
    source_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    source_chunk_id INTEGER REFERENCES document_chunks(id) ON DELETE SET NULL,
    confidence FLOAT,
    
    -- 关联信息
    related_entities TEXT[],  -- 关联实体ID列表
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- 唯一约束
    CONSTRAINT uk_entity_name_type UNIQUE (entity_name, entity_type)
);

-- 实体关系表
CREATE TABLE entity_relations (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    
    -- 关系信息
    source_entity_id INTEGER NOT NULL REFERENCES knowledge_entities(id) ON DELETE CASCADE,
    target_entity_id INTEGER NOT NULL REFERENCES knowledge_entities(id) ON DELETE CASCADE,
    relation_type VARCHAR(100) NOT NULL,
    relation_strength FLOAT DEFAULT 1.0,
    
    -- 关系属性
    properties JSONB DEFAULT '{}',
    
    -- 来源信息
    source_type VARCHAR(50),
    source_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    confidence FLOAT,
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- 约束
    CONSTRAINT chk_relation_strength CHECK (relation_strength >= 0 AND relation_strength <= 1),
    CONSTRAINT uq_source_target_relation UNIQUE (source_entity_id, target_entity_id, relation_type)
);

-- ============================================
-- 问答对相关表
-- ============================================

-- 问答对表
CREATE TABLE qa_pairs (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    
    -- 问答内容
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    question_type VARCHAR(50),
    answer_type VARCHAR(50),
    
    -- 关联信息
    source_chunk_id INTEGER REFERENCES document_chunks(id) ON DELETE SET NULL,
    source_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    
    -- 质量信息
    confidence FLOAT,
    quality_score FLOAT,
    user_feedback INTEGER,
    
    -- 元数据
    metadata JSONB DEFAULT '{}',
    tags TEXT[],
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 向量化相关表
-- ============================================

-- 向量化任务表
CREATE TABLE embedding_tasks (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    
    -- 任务信息
    task_type VARCHAR(50) NOT NULL,  -- document, chunk, query
    entity_type VARCHAR(50),  -- document, chunk, query
    entity_id INTEGER,
    
    -- 向量化信息
    model_name VARCHAR(100) NOT NULL,
    model_version VARCHAR(50),
    embedding_dimension INTEGER,
    
    -- 状态信息
    status VARCHAR(50) DEFAULT 'pending',
    progress INTEGER DEFAULT 0,
    error_message TEXT,
    
    -- 结果信息
    embedding_id VARCHAR(255),
    vector_data JSONB,
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    
    -- 约束
    CONSTRAINT chk_task_status CHECK (status IN ('pending', 'processing', 'completed', 'failed'))
);

-- ============================================
-- 查询相关表
-- ============================================

-- 查询历史表
CREATE TABLE query_history (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    
    -- 查询信息
    query_text TEXT NOT NULL,
    query_type VARCHAR(50) DEFAULT 'text',
    query_embedding JSONB,
    
    -- 查询参数
    top_k INTEGER DEFAULT 10,
    filters JSONB DEFAULT '{}',
    rerank_enabled BOOLEAN DEFAULT FALSE,
    
    -- 查询结果
    results JSONB,
    result_count INTEGER,
    
    -- 性能信息
    execution_time_ms INTEGER,
    vector_search_time_ms INTEGER,
    rerank_time_ms INTEGER,
    
    -- 用户信息
    user_id VARCHAR(255),
    session_id VARCHAR(255),
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- 约束
    CONSTRAINT chk_query_type CHECK (query_type IN ('text', 'table', 'hybrid'))
);

-- 查询反馈表
CREATE TABLE query_feedback (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    query_id INTEGER REFERENCES query_history(id) ON DELETE CASCADE,
    
    -- 反馈信息
    result_index INTEGER,
    relevance_score INTEGER,
    feedback_type VARCHAR(50),  -- positive, negative, skip
    
    -- 反馈内容
    comment TEXT,
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- 约束
    CONSTRAINT chk_feedback_type CHECK (feedback_type IN ('positive', 'negative', 'skip'))
);

-- ============================================
-- 系统配置表
-- ============================================

-- 系统配置表
CREATE TABLE system_config (
    id SERIAL PRIMARY KEY,
    config_key VARCHAR(255) UNIQUE NOT NULL,
    config_value TEXT NOT NULL,
    config_type VARCHAR(50) DEFAULT 'string',
    description TEXT,
    
    -- 元数据
    is_secret BOOLEAN DEFAULT FALSE,
    is_readonly BOOLEAN DEFAULT FALSE,
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 性能监控表
-- ============================================

-- 性能指标表
CREATE TABLE performance_metrics (
    id SERIAL PRIMARY KEY,
    metric_name VARCHAR(100) NOT NULL,
    metric_value FLOAT NOT NULL,
    metric_unit VARCHAR(50),
    
    -- 维度信息
    dimensions JSONB DEFAULT '{}',
    
    -- 时间戳
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 创建索引
-- ============================================

-- 文档表索引
CREATE INDEX idx_documents_status ON documents(status);
CREATE INDEX idx_documents_type ON documents(document_type);
CREATE INDEX idx_documents_created ON documents(created_at);
CREATE INDEX idx_documents_fts ON documents USING GIN(to_tsvector('chinese', file_name));

-- 文档块表索引
CREATE INDEX idx_chunks_document ON document_chunks(document_id);
CREATE INDEX idx_chunks_type ON document_chunks(chunk_type);
CREATE INDEX idx_chunks_page ON document_chunks(page_number);
CREATE INDEX idx_chunks_embedding ON document_chunks(embedding_id);
CREATE INDEX idx_chunks_fts ON document_chunks USING GIN(to_tsvector('chinese', content));

-- 表格数据表索引
CREATE INDEX idx_tables_document ON tables_data(document_id);
CREATE INDEX idx_tables_chunk ON tables_data(chunk_id);
CREATE INDEX idx_tables_page ON tables_data(page_number);

-- 知识实体表索引
CREATE INDEX idx_entities_type ON knowledge_entities(entity_type);
CREATE INDEX idx_entities_category ON knowledge_entities(entity_category);
CREATE INDEX idx_entities_source ON knowledge_entities(source_document_id);

-- 实体关系表索引
CREATE INDEX idx_relations_source ON entity_relations(source_entity_id);
CREATE INDEX idx_relations_target ON entity_relations(target_entity_id);
CREATE INDEX idx_relations_type ON entity_relations(relation_type);

-- 问答对表索引
CREATE INDEX idx_pairs_chunk ON qa_pairs(source_chunk_id);
CREATE INDEX idx_pairs_document ON qa_pairs(source_document_id);
CREATE INDEX idx_pairs_confidence ON qa_pairs(confidence);

-- 向量化任务表索引
CREATE INDEX idx_embedding_tasks_status ON embedding_tasks(status);
CREATE INDEX idx_embedding_tasks_entity ON embedding_tasks(entity_id, entity_type);

-- 查询历史表索引
CREATE INDEX idx_queries_user ON query_history(user_id);
CREATE INDEX idx_queries_session ON query_history(session_id);
CREATE INDEX idx_queries_created ON query_history(created_at);

-- 查询反馈表索引
CREATE INDEX idx_feedback_query ON query_feedback(query_id);

-- 性能指标表索引
CREATE INDEX idx_metrics_name ON performance_metrics(metric_name);
CREATE INDEX idx_metrics_recorded ON performance_metrics(recorded_at);

-- ============================================
-- 插入初始配置数据
-- ============================================

-- 系统配置
INSERT INTO system_config (config_key, config_value, config_type, description) VALUES
('embedding.default_model', 'text-embedding-ada-002', 'string', '默认embedding模型'),
('embedding.dimension', '1536', 'integer', 'embedding向量维度'),
('embedding.batch_size', '32', 'integer', 'embedding批处理大小'),
('rerank.enabled', 'true', 'boolean', '是否启用rerank'),
('rerank.model', 'cross-encoder/ms-marco-MiniLM-L-12-v2', 'string', 'rerank模型'),
('recall.top_k', '20', 'integer', '召回top_k数量'),
('recall.final_top_k', '10', 'integer', '最终返回top_k数量'),
('cache.enabled', 'true', 'boolean', '是否启用缓存'),
('cache.ttl', '3600', 'integer', '缓存TTL（秒）'),
('concurrency.max_workers', '4', 'integer', '最大工作线程数'),
('concurrency.queue_size', '100', 'integer', '任务队列大小');

-- ============================================
-- 创建触发器函数
-- ============================================

-- 自动更新updated_at字段
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 为所有表创建updated_at触发器
CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_chunks_updated_at BEFORE UPDATE ON document_chunks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tables_updated_at BEFORE UPDATE ON tables_data
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_entities_updated_at BEFORE UPDATE ON knowledge_entities
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_entity_relations_updated_at BEFORE UPDATE ON entity_relations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_qa_pairs_updated_at BEFORE UPDATE ON qa_pairs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_embedding_tasks_updated_at BEFORE UPDATE ON embedding_tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- 创建视图
-- ============================================

-- 文档统计视图
CREATE OR REPLACE VIEW document_statistics AS
SELECT 
    d.id,
    d.file_name,
    d.status,
    d.page_count,
    COUNT(DISTINCT dc.id) as total_chunks,
    COUNT(DISTINCT td.id) as total_tables,
    COUNT(DISTINCT ke.id) as total_entities,
    d.created_at,
    d.processed_at
FROM documents d
LEFT JOIN document_chunks dc ON d.id = dc.document_id
LEFT JOIN tables_data td ON d.id = td.document_id
LEFT JOIN knowledge_entities ke ON d.id = ke.source_document_id
GROUP BY d.id, d.file_name, d.status, d.page_count, d.created_at, d.processed_at;

-- 向量化进度视图
CREATE OR REPLACE VIEW embedding_progress AS
SELECT 
    et.entity_type,
    et.status,
    COUNT(*) as total_tasks,
    SUM(CASE WHEN et.status = 'completed' THEN 1 ELSE 0 END) as completed_tasks,
    SUM(CASE WHEN et.status = 'failed' THEN 1 ELSE 0 END) as failed_tasks,
    round(SUM(CASE WHEN et.status = 'completed' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as progress_percentage
FROM embedding_tasks et
GROUP BY et.entity_type, et.status
ORDER BY et.entity_type, et.status;

-- 查询性能统计视图
CREATE OR REPLACE VIEW query_performance_stats AS
SELECT 
    DATE_TRUNC('hour', created_at) as hour,
    COUNT(*) as total_queries,
    AVG(execution_time_ms) as avg_execution_time,
    AVG(vector_search_time_ms) as avg_vector_search_time,
    AVG(rerank_time_ms) as avg_rerank_time,
    AVG(result_count) as avg_result_count
FROM query_history
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY DATE_TRUNC('hour', created_at)
ORDER BY hour DESC;

-- ============================================
-- 初始化完成
-- ============================================

-- 输出初始化信息
DO $$
BEGIN
    RAISE NOTICE 'RAG系统数据库初始化完成';
    RAISE NOTICE '已创建表: documents, document_chunks, tables_data';
    RAISE NOTICE '已创建表: knowledge_entities, entity_relations';
    RAISE NOTICE '已创建表: qa_pairs, embedding_tasks';
    RAISE NOTICE '已创建表: query_history, query_feedback';
    RAISE NOTICE '已创建表: system_config, performance_metrics';
    RAISE NOTICE '已创建视图: document_statistics, embedding_progress, query_performance_stats';
END $$;
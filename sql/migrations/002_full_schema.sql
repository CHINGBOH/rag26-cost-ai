-- Phase 0: 完整 Schema 更新（10张表）
-- 执行时间: 2026-04-21

-- ============================================
-- 1. 扩展现有表
-- ============================================

-- documents: 增加 doc_code 存储原始文件标识
ALTER TABLE documents ADD COLUMN IF NOT EXISTS doc_code VARCHAR(64) UNIQUE;
COMMENT ON COLUMN documents.doc_code IS '原始文件hash或标识，如文件名MD5';

-- price_records: 补充 plan.md 要求的字段
ALTER TABLE price_records 
    ADD COLUMN IF NOT EXISTS price_formula TEXT,
    ADD COLUMN IF NOT EXISTS agency_code VARCHAR(50),
    ADD COLUMN IF NOT EXISTS seq_no INTEGER,
    ADD COLUMN IF NOT EXISTS confidence FLOAT DEFAULT 1.0,
    ADD COLUMN IF NOT EXISTS source_doc VARCHAR(500);

-- price_records 字段重命名对齐（保留旧字段兼容）
-- period -> year_month (逻辑相同，无需改列名)
-- spec -> specification (逻辑相同，无需改列名)
-- price -> price_tax_included (逻辑相同，无需改列名)

COMMENT ON COLUMN price_records.price_formula IS '计算公式，如 D² × 959+50';
COMMENT ON COLUMN price_records.agency_code IS '执行机构代号';
COMMENT ON COLUMN price_records.seq_no IS '原始序号';
COMMENT ON COLUMN price_records.confidence IS 'OCR/提取置信度';

-- text_chunks: 增加 chunk_type 区分内容类型
ALTER TABLE text_chunks 
    ADD COLUMN IF NOT EXISTS chunk_type VARCHAR(30) DEFAULT 'article',
    ADD COLUMN IF NOT EXISTS confidence FLOAT DEFAULT 1.0;
COMMENT ON COLUMN text_chunks.chunk_type IS 'article|price_table|chart|quota_table|division|fee_rate';

-- ============================================
-- 2. 新增表: chart_series（趋势图时间序列）
-- ============================================
CREATE TABLE IF NOT EXISTS chart_series (
    id              SERIAL PRIMARY KEY,
    doc_code        VARCHAR(64) REFERENCES documents(doc_code) ON DELETE CASCADE,
    document_id     INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    page_number     INT NOT NULL,
    chart_title     TEXT,
    series_name     TEXT NOT NULL,           -- 如 "热轧光圆钢筋 HPB300 φ6"
    year_month      CHAR(7),                 -- '2024-01'
    price_value     NUMERIC(10, 2),
    extraction_method VARCHAR(30) DEFAULT 'vector_coord',
    confidence      FLOAT DEFAULT 1.0,
    raw_coords      JSONB,                   -- 原始坐标数据 {x, y, color}
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE (doc_code, series_name, year_month)
);

CREATE INDEX IF NOT EXISTS idx_chart_series_doc ON chart_series(document_id);
CREATE INDEX IF NOT EXISTS idx_chart_series_ym ON chart_series(year_month);
CREATE INDEX IF NOT EXISTS idx_chart_series_name ON chart_series(series_name);

-- ============================================
-- 3. 新增表: quota_items（定额子目）
-- ============================================
CREATE TABLE IF NOT EXISTS quota_items (
    id              SERIAL PRIMARY KEY,
    doc_code        VARCHAR(64) REFERENCES documents(doc_code) ON DELETE CASCADE,
    document_id     INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    quota_code      VARCHAR(50) NOT NULL,    -- 如 "C1-1-1"
    chapter_code    VARCHAR(20),             -- 章编号
    chapter_name    TEXT,                    -- 章名称
    section_code    VARCHAR(20),             -- 节编号
    item_name       TEXT NOT NULL,           -- 子目名称
    spec            TEXT,                    -- 规格
    unit            VARCHAR(20),             -- 计量单位
    work_content    TEXT,                    -- 工作内容
    base_price      NUMERIC(12, 2),          -- 基价
    labor_cost      NUMERIC(12, 2),          -- 人工费
    material_cost   NUMERIC(12, 2),          -- 材料费
    machine_cost    NUMERIC(12, 2),          -- 机械费
    manage_profit   NUMERIC(12, 2),          -- 管理费+利润
    risk_cost       NUMERIC(12, 2),          -- 风险费
    page_number     INT,
    is_continuation BOOLEAN DEFAULT FALSE,   -- 是否续表
    parent_code     VARCHAR(50),             -- 父级子目（续表关联）
    embedding       VECTOR(1024),
    source_row      JSONB,
    confidence      FLOAT DEFAULT 1.0,
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE (doc_code, quota_code)
);

CREATE INDEX IF NOT EXISTS idx_quota_items_doc ON quota_items(document_id);
CREATE INDEX IF NOT EXISTS idx_quota_items_code ON quota_items(quota_code);
CREATE INDEX IF NOT EXISTS idx_quota_items_chapter ON quota_items(chapter_code);
CREATE INDEX IF NOT EXISTS idx_quota_items_embedding ON quota_items USING hnsw (embedding vector_cosine_ops);

-- ============================================
-- 4. 新增表: quota_materials（工料机消耗量明细）
-- ============================================
CREATE TABLE IF NOT EXISTS quota_materials (
    id              SERIAL PRIMARY KEY,
    doc_code        VARCHAR(64) REFERENCES documents(doc_code) ON DELETE CASCADE,
    document_id     INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    quota_code      VARCHAR(50) NOT NULL,    -- 关联 quota_items
    material_name   TEXT NOT NULL,
    spec            TEXT,
    unit            VARCHAR(20),
    consumption     NUMERIC(12, 4),          -- 消耗量
    reference_price NUMERIC(12, 2),          -- 定额参考价（历史基准）
    total_price     NUMERIC(12, 2),          -- 合价
    material_type   VARCHAR(20),             -- '人工'|'材料'|'机械'
    page_number     INT,
    source_row      JSONB,
    confidence      FLOAT DEFAULT 1.0,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quota_materials_doc ON quota_materials(document_id);
CREATE INDEX IF NOT EXISTS idx_quota_materials_quota ON quota_materials(quota_code);
CREATE INDEX IF NOT EXISTS idx_quota_materials_name ON quota_materials(material_name);

-- ============================================
-- 5. 新增表: division_codes（分部分项WBS编码）
-- ============================================
CREATE TABLE IF NOT EXISTS division_codes (
    id              SERIAL PRIMARY KEY,
    doc_code        VARCHAR(64) REFERENCES documents(doc_code) ON DELETE CASCADE,
    document_id     INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    code            VARCHAR(50) NOT NULL,    -- 如 "01-01-01-001-001"
    name            TEXT NOT NULL,
    unit            VARCHAR(20),
    category        VARCHAR(20),             -- '房建'|'市政'
    parent_code     VARCHAR(50),             -- 父编码
    depth           INT,                     -- 层级深度 1=册,2=章,3=节...
    work_content    TEXT,                    -- 工作内容/项目特征
    page_number     INT,
    embedding       VECTOR(1024),
    source_row      JSONB,
    confidence      FLOAT DEFAULT 1.0,
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE (doc_code, code)
);

CREATE INDEX IF NOT EXISTS idx_division_codes_doc ON division_codes(document_id);
CREATE INDEX IF NOT EXISTS idx_division_codes_code ON division_codes(code);
CREATE INDEX IF NOT EXISTS idx_division_codes_parent ON division_codes(parent_code);
CREATE INDEX IF NOT EXISTS idx_division_codes_embedding ON division_codes USING hnsw (embedding vector_cosine_ops);

-- ============================================
-- 6. 新增表: fee_rates（计价费率标准）
-- ============================================
CREATE TABLE IF NOT EXISTS fee_rates (
    id              SERIAL PRIMARY KEY,
    doc_code        VARCHAR(64) REFERENCES documents(doc_code) ON DELETE CASCADE,
    document_id     INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    standard_year   VARCHAR(4),              -- '2023'|'2025'
    fee_name        TEXT NOT NULL,           -- 费率名称
    fee_category    VARCHAR(50),             -- 类别：安全文明施工费|赶工措施费...
    base_formula    TEXT,                    -- 计算公式说明
    rate_min        NUMERIC(8, 4),           -- 下限费率
    rate_max        NUMERIC(8, 4),           -- 上限费率
    rate_recommended NUMERIC(8, 4),          -- 推荐费率
    calc_base       TEXT,                    -- 计算基数说明
    applicable_scope TEXT,                   -- 适用范围
    page_number     INT,
    source_text     TEXT,                    -- 原始条文
    embedding       VECTOR(1024),
    confidence      FLOAT DEFAULT 1.0,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fee_rates_doc ON fee_rates(document_id);
CREATE INDEX IF NOT EXISTS idx_fee_rates_year ON fee_rates(standard_year);
CREATE INDEX IF NOT EXISTS idx_fee_rates_name ON fee_rates(fee_name);
CREATE INDEX IF NOT EXISTS idx_fee_rates_embedding ON fee_rates USING hnsw (embedding vector_cosine_ops);

-- ============================================
-- 7. 新增表: ocr_tasks（分页追踪，断点续传）
-- ============================================
CREATE TABLE IF NOT EXISTS ocr_tasks (
    id              SERIAL PRIMARY KEY,
    file_path       TEXT NOT NULL,
    file_name       VARCHAR(500),
    doc_code        VARCHAR(64),
    total_pages     INT,
    page_number     INT NOT NULL,
    page_type       VARCHAR(30),             -- 'article'|'price_table'|'chart'|'quota_table'|'division'|'fee_text'|'skip'
    status          VARCHAR(20) DEFAULT 'pending',  -- pending|processing|completed|failed|quarantined
    retry_count     INT DEFAULT 0,
    result_json     JSONB,
    error_msg       TEXT,
    processed_at    TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE (file_path, page_number)
);

CREATE INDEX IF NOT EXISTS idx_ocr_tasks_status ON ocr_tasks(status);
CREATE INDEX IF NOT EXISTS idx_ocr_tasks_file ON ocr_tasks(file_path);
CREATE INDEX IF NOT EXISTS idx_ocr_tasks_doc ON ocr_tasks(doc_code);

-- ============================================
-- 8. 新增表: ocr_quarantine（隔离区）
-- ============================================
CREATE TABLE IF NOT EXISTS ocr_quarantine (
    id              SERIAL PRIMARY KEY,
    ocr_task_id     INTEGER REFERENCES ocr_tasks(id),
    file_path       TEXT,
    page_number     INT,
    doc_code        VARCHAR(64),
    quarantine_type VARCHAR(50),             -- 'price_range_error'|'sum_mismatch'|'low_confidence'|'cross_validation_fail'
    target_table    VARCHAR(50),             -- 'price_records'|'quota_items'|...
    raw_data        JSONB,
    error_detail    TEXT,
    suggested_fix   TEXT,
    reviewed        BOOLEAN DEFAULT FALSE,
    reviewed_by     VARCHAR(50),
    reviewed_at     TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quarantine_type ON ocr_quarantine(quarantine_type);
CREATE INDEX IF NOT EXISTS idx_quarantine_reviewed ON ocr_quarantine(reviewed);


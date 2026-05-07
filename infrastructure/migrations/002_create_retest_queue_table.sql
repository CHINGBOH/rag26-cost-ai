-- =====================================================
-- Migration 002: Adaptive Retest Queue Table
-- =====================================================
-- Purpose: 统一调度 Learning 系统的重测请求
-- Issue: #117 - Learning Ghost Triggers
-- Author: AI Agent
-- Date: 2026-05-08
-- =====================================================

-- 创建重测队列表
CREATE TABLE IF NOT EXISTS retest_queue (
    -- 主键
    id SERIAL PRIMARY KEY,
    
    -- 问题信息
    question TEXT NOT NULL,
    question_hash VARCHAR(16) NOT NULL,  -- 用于去重（SHA256前16位）
    
    -- 调度信息
    source VARCHAR(50) NOT NULL,         -- 触发源: timer, followup, feedback, repeated, contract, manual, patch
    priority INTEGER NOT NULL,           -- 优先级: manual=10, feedback=8, repeated=7, followup=6, timer=5
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMP NOT NULL,    -- 下次执行时间
    
    -- 状态
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, scheduled, running, success, failed, cancelled
    last_error TEXT,                     -- 最后一次错误信息
    
    -- 元数据
    metadata JSONB,                      -- 额外信息
    
    -- 时间戳
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP               -- 完成时间
);

-- 索引：加速查询
CREATE INDEX IF NOT EXISTS idx_retest_queue_question_hash 
    ON retest_queue(question_hash);

CREATE INDEX IF NOT EXISTS idx_retest_queue_status 
    ON retest_queue(status);

CREATE INDEX IF NOT EXISTS idx_retest_queue_next_retry 
    ON retest_queue(next_retry_at) 
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_retest_queue_priority_retry 
    ON retest_queue(priority DESC, next_retry_at ASC) 
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_retest_queue_source 
    ON retest_queue(source);

-- 触发器：自动更新 updated_at
CREATE OR REPLACE FUNCTION update_retest_queue_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_retest_queue_updated_at
    BEFORE UPDATE ON retest_queue
    FOR EACH ROW
    EXECUTE FUNCTION update_retest_queue_updated_at();

-- 创建审计日志表（可选，用于追踪重测历史）
CREATE TABLE IF NOT EXISTS retest_history (
    id SERIAL PRIMARY KEY,
    queue_id INTEGER REFERENCES retest_queue(id),
    question_hash VARCHAR(16) NOT NULL,
    status VARCHAR(20) NOT NULL,
    retry_count INTEGER,
    error_message TEXT,
    execution_time_ms INTEGER,         -- 执行耗时（毫秒）
    result_summary JSONB,              -- 执行结果摘要
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_retest_history_queue_id 
    ON retest_history(queue_id);

CREATE INDEX IF NOT EXISTS idx_retest_history_question_hash 
    ON retest_history(question_hash);

CREATE INDEX IF NOT EXISTS idx_retest_history_created_at 
    ON retest_history(created_at DESC);

-- 注释
COMMENT ON TABLE retest_queue IS 'Adaptive Retest Scheduler: 重测任务队列';
COMMENT ON COLUMN retest_queue.question_hash IS '问题哈希，用于去重（SHA256前16位）';
COMMENT ON COLUMN retest_queue.source IS '触发源: timer, followup, feedback, repeated, contract, manual, patch';
COMMENT ON COLUMN retest_queue.priority IS '优先级: manual=10, feedback=8, repeated=7, followup=6, timer=5';
COMMENT ON COLUMN retest_queue.retry_count IS '重试次数，决定退避延迟';
COMMENT ON COLUMN retest_queue.next_retry_at IS '下次执行时间，支持指数退避';
COMMENT ON COLUMN retest_queue.status IS '状态: pending, scheduled, running, success, failed, cancelled';

COMMENT ON TABLE retest_history IS 'Adaptive Retest Scheduler: 重测执行历史';

-- 完成
SELECT 'Migration 002: retest_queue and retest_history tables created successfully' AS message;

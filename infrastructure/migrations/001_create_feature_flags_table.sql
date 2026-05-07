-- Migration: 001_create_feature_flags_table
-- Description: 创建 feature_flags 表用于存储运行时功能开关配置
-- Author: System
-- Date: 2026-05-08

-- ============================================================================
-- Feature Flags Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS feature_flags (
    -- 主键：flag 名称（使用枚举值，如 "FOLLOWUP_STRICT_COVERAGE"）
    flag_name VARCHAR(100) PRIMARY KEY,
    
    -- 是否启用
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- 描述信息
    description TEXT,
    
    -- 灰度发布百分比 (0-100)，100 表示全量发布
    rollout_percentage INT DEFAULT 100 CHECK (rollout_percentage >= 0 AND rollout_percentage <= 100),
    
    -- 目标用户白名单（JSON 数组格式）
    -- 例如: ["user_123", "user_456"]
    target_users JSONB DEFAULT '[]'::jsonb,
    
    -- 目标环境（JSON 数组格式）
    -- 例如: ["production", "staging"]
    target_environments JSONB DEFAULT '["production", "staging", "development"]'::jsonb,
    
    -- 创建时间
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- 最后更新时间
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- 最后更新人
    updated_by VARCHAR(100),
    
    -- 附加元数据（JSON 格式）
    -- 可以存储 A/B 测试相关信息、指标目标等
    metadata JSONB DEFAULT '{}'::jsonb
);

-- ============================================================================
-- Indexes
-- ============================================================================

-- 索引：快速查询启用的 flags
CREATE INDEX IF NOT EXISTS idx_feature_flags_enabled 
    ON feature_flags(enabled);

-- 索引：快速查询特定环境的 flags
CREATE INDEX IF NOT EXISTS idx_feature_flags_environments 
    ON feature_flags USING GIN (target_environments);

-- ============================================================================
-- Feature Flag Change History Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS feature_flag_history (
    id SERIAL PRIMARY KEY,
    
    -- 关联的 flag 名称
    flag_name VARCHAR(100) NOT NULL REFERENCES feature_flags(flag_name) ON DELETE CASCADE,
    
    -- 变更前的状态
    old_enabled BOOLEAN,
    
    -- 变更后的状态
    new_enabled BOOLEAN NOT NULL,
    
    -- 变更原因
    reason TEXT,
    
    -- 变更人
    changed_by VARCHAR(100),
    
    -- 变更时间
    changed_at TIMESTAMP DEFAULT NOW(),
    
    -- 附加信息（如灰度百分比变更等）
    change_details JSONB DEFAULT '{}'::jsonb
);

-- 索引：按 flag 名称查询历史
CREATE INDEX IF NOT EXISTS idx_feature_flag_history_flag_name 
    ON feature_flag_history(flag_name);

-- 索引：按时间查询历史
CREATE INDEX IF NOT EXISTS idx_feature_flag_history_changed_at 
    ON feature_flag_history(changed_at DESC);

-- ============================================================================
-- Triggers
-- ============================================================================

-- 自动更新 updated_at 字段
CREATE OR REPLACE FUNCTION update_feature_flags_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_feature_flags_updated_at
    BEFORE UPDATE ON feature_flags
    FOR EACH ROW
    EXECUTE FUNCTION update_feature_flags_updated_at();

-- 自动记录变更历史
CREATE OR REPLACE FUNCTION log_feature_flag_change()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.enabled != NEW.enabled THEN
        INSERT INTO feature_flag_history (
            flag_name,
            old_enabled,
            new_enabled,
            reason,
            changed_by,
            change_details
        ) VALUES (
            NEW.flag_name,
            OLD.enabled,
            NEW.enabled,
            COALESCE(NEW.description, 'No reason provided'),
            NEW.updated_by,
            jsonb_build_object(
                'old_rollout_percentage', OLD.rollout_percentage,
                'new_rollout_percentage', NEW.rollout_percentage,
                'old_target_users', OLD.target_users,
                'new_target_users', NEW.target_users
            )
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_log_feature_flag_change
    AFTER UPDATE ON feature_flags
    FOR EACH ROW
    EXECUTE FUNCTION log_feature_flag_change();

-- ============================================================================
-- Initial Data
-- ============================================================================

-- 插入初始的 feature flags（与代码中的 DEFAULT_VALUES 保持一致）
INSERT INTO feature_flags (flag_name, enabled, description, rollout_percentage) VALUES
    ('FOLLOWUP_STRICT_COVERAGE', FALSE, '启用严格的 followup 覆盖率检测（阈值提升到 0.65）', 0),
    ('LEARNING_ADAPTIVE_SCHEDULING', FALSE, '启用自适应学习重测调度（防止并发过载）', 0),
    ('LEARNING_GAP_WHITELIST', FALSE, '启用知识缺口白名单过滤（排除低覆盖 followup）', 0),
    ('TOOL_EXPLAINABLE_SELECTION', FALSE, '启用可解释的工具选择（记录推理过程）', 0),
    ('CONTRACT_CONVERGENCE_POLICY', FALSE, '启用新的 Contract 收敛策略（目标导向）', 0),
    ('EVALUATION_STRICT_MODE', FALSE, '启用严格评估模式（LLM 语义验证）', 0),
    ('PRICE_QUERY_TIME_VALIDATION', TRUE, '启用价格查询时间范围验证', 100),
    ('UNIFIED_CONFIG_LOADER', TRUE, '启用统一配置加载器', 100)
ON CONFLICT (flag_name) DO NOTHING;

-- ============================================================================
-- Comments
-- ============================================================================

COMMENT ON TABLE feature_flags IS 'Feature flags for runtime behavior control';
COMMENT ON COLUMN feature_flags.flag_name IS 'Unique feature flag name (enum value)';
COMMENT ON COLUMN feature_flags.enabled IS 'Whether the feature is enabled';
COMMENT ON COLUMN feature_flags.rollout_percentage IS 'Gradual rollout percentage (0-100)';
COMMENT ON COLUMN feature_flags.target_users IS 'User whitelist for A/B testing (JSON array)';
COMMENT ON COLUMN feature_flags.target_environments IS 'Target environments (JSON array)';

COMMENT ON TABLE feature_flag_history IS 'Audit log for feature flag changes';
COMMENT ON COLUMN feature_flag_history.reason IS 'Why this change was made';
COMMENT ON COLUMN feature_flag_history.changed_by IS 'Who made this change';

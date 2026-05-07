# Feature Flag 系统使用指南

## 📋 概述

Feature Flag 系统支持运行时行为动态切换，无需重启服务即可：
- ✅ 灰度发布和 A/B 测试
- ✅ 快速回滚问题功能
- ✅ 三层优先级：运行时覆盖 > 数据库 > 代码默认值

## 🚀 快速开始

### 1. 运行数据库迁移

\`\`\`bash
# 连接到 PostgreSQL 数据库
psql -h localhost -U postgres -d rag_db -f infrastructure/migrations/001_create_feature_flags_table.sql
\`\`\`

### 2. 在代码中使用

\`\`\`python
from config.feature_flags import is_feature_enabled, FeatureFlags

# 方式 1: 使用便捷函数（推荐）
if is_feature_enabled("FOLLOWUP_STRICT_COVERAGE"):
    # 使用严格覆盖率检测
    threshold = 0.65
else:
    # 使用旧的阈值
    threshold = 0.45

# 方式 2: 使用类方法
if FeatureFlags.is_enabled("EVALUATION_STRICT_MODE"):
    evaluator = StrictEvaluator()
else:
    evaluator = LegacyEvaluator()
\`\`\`

### 3. 通过 API 管理

\`\`\`bash
# 查看所有 flags
curl http://localhost:8002/api/v1/feature-flags/

# 查看单个 flag
curl http://localhost:8002/api/v1/feature-flags/FOLLOWUP_STRICT_COVERAGE

# 更新 flag（持久化到数据库）
curl -X PUT http://localhost:8002/api/v1/feature-flags/FOLLOWUP_STRICT_COVERAGE \\
  -H "Content-Type: application/json" \\
  -d '{
    "enabled": true,
    "rollout_percentage": 50,
    "updated_by": "admin"
  }'

# 运行时临时覆盖（紧急热修复）
curl -X POST http://localhost:8002/api/v1/feature-flags/EVALUATION_STRICT_MODE/runtime-override \\
  -H "Content-Type: application/json" \\
  -d '{
    "enabled": false,
    "ttl_seconds": 3600
  }'

# 查看变更历史
curl http://localhost:8002/api/v1/feature-flags/FOLLOWUP_STRICT_COVERAGE/history
\`\`\`

## 📚 可用的 Feature Flags

| Flag 名称 | 默认值 | 说明 | 相关 Issue |
|-----------|--------|------|-----------|
| `FOLLOWUP_STRICT_COVERAGE` | `False` | 启用严格的 followup 覆盖率检测（阈值 0.65） | #116 |
| `LEARNING_ADAPTIVE_SCHEDULING` | `False` | 启用自适应学习重测调度（防止并发过载） | #117 |
| `LEARNING_GAP_WHITELIST` | `False` | 启用知识缺口白名单过滤（排除低覆盖 followup） | #117 |
| `TOOL_EXPLAINABLE_SELECTION` | `False` | 启用可解释的工具选择（记录推理过程） | #123 |
| `CONTRACT_CONVERGENCE_POLICY` | `False` | 启用新的 Contract 收敛策略（目标导向） | #118 |
| `EVALUATION_STRICT_MODE` | `False` | 启用严格评估模式（LLM 语义验证） | #124 |
| `PRICE_QUERY_TIME_VALIDATION` | `True` | 启用价格查询时间范围验证 | #121 |
| `UNIFIED_CONFIG_LOADER` | `True` | 启用统一配置加载器 | #122 |

## 🔧 集成到现有代码

### 示例 1: 在 followup 覆盖率检测中使用

\`\`\`python
# src/backend/retrieval-service/app/agent/graph.py

from config.feature_flags import is_feature_enabled

def _coverage_tier(score: float) -> str:
    \"\"\"判断覆盖率等级\"\"\"
    
    if is_feature_enabled("FOLLOWUP_STRICT_COVERAGE"):
        # ✅ 新逻辑：严格阈值
        if score >= 0.75:
            return "high"
        if score >= 0.55:
            return "med"
        return "low"
    else:
        # 旧逻辑：保持向后兼容
        if score >= 0.65:
            return "high"
        if score >= 0.45:
            return "med"
        return "low"
\`\`\`

### 示例 2: 在学习系统中使用

\`\`\`python
# src/backend/retrieval-service/app/agent/scheduler.py

from config.feature_flags import is_feature_enabled

def schedule_gap_retest(gap_id: str):
    \"\"\"调度知识缺口重测\"\"\"
    
    if is_feature_enabled("LEARNING_ADAPTIVE_SCHEDULING"):
        # ✅ 使用自适应调度器（防止过载）
        from .adaptive_scheduler import AdaptiveRetestScheduler
        scheduler = AdaptiveRetestScheduler()
        scheduler.schedule_retest(gap_id, priority=5, source="timer")
    else:
        # 旧逻辑：直接触发
        asyncio.create_task(retest_gap(gap_id))
\`\`\`

### 示例 3: 在评估系统中使用

\`\`\`python
# src/backend/retrieval-service/app/agent/evaluator.py

from config.feature_flags import is_feature_enabled

def create_evaluator():
    \"\"\"创建评估器实例\"\"\"
    
    if is_feature_enabled("EVALUATION_STRICT_MODE"):
        # ✅ 使用严格评估器（LLM 语义验证）
        return StrictEvaluator()
    else:
        # 旧逻辑：启发式评估
        return HeuristicEvaluator()
\`\`\`

## 🎯 最佳实践

### 1. 灰度发布

\`\`\`python
# 先设置 rollout_percentage = 0（关闭）
# 然后逐步提升：10% → 25% → 50% → 100%

curl -X PUT http://localhost:8002/api/v1/feature-flags/FOLLOWUP_STRICT_COVERAGE \\
  -H "Content-Type: application/json" \\
  -d '{
    "enabled": true,
    "rollout_percentage": 10,
    "updated_by": "admin"
  }'

# 监控指标 1-2 天后，提升到 25%
# 最终达到 100% 全量发布
\`\`\`

### 2. A/B 测试

\`\`\`python
# 设置目标用户白名单
curl -X PUT http://localhost:8002/api/v1/feature-flags/TOOL_EXPLAINABLE_SELECTION \\
  -H "Content-Type: application/json" \\
  -d '{
    "enabled": true,
    "target_users": ["user_123", "user_456"],
    "rollout_percentage": 100,
    "updated_by": "admin"
  }'

# 代码中检查用户是否在白名单
# （需要扩展 is_feature_enabled 支持 user_id 参数）
\`\`\`

### 3. 紧急回滚

\`\`\`bash
# 场景：生产环境发现严格评估模式导致所有答案都低分
# 立即关闭，1小时后自动恢复

curl -X POST http://localhost:8002/api/v1/feature-flags/EVALUATION_STRICT_MODE/runtime-override \\
  -H "Content-Type: application/json" \\
  -d '{
    "enabled": false,
    "ttl_seconds": 3600
  }'

# 1小时后，runtime override 自动过期，回到数据库配置
\`\`\`

### 4. 监控和审计

\`\`\`bash
# 查看 flag 变更历史
curl http://localhost:8002/api/v1/feature-flags/FOLLOWUP_STRICT_COVERAGE/history

# 响应示例
{
  "flag_name": "FOLLOWUP_STRICT_COVERAGE",
  "history": [
    {
      "old_enabled": false,
      "new_enabled": true,
      "reason": "A/B test phase 1",
      "changed_by": "admin",
      "changed_at": "2026-05-08T01:00:00Z",
      "change_details": {
        "old_rollout_percentage": 0,
        "new_rollout_percentage": 10
      }
    }
  ]
}
\`\`\`

## 🔒 安全注意事项

1. **API 访问控制**: 生产环境应该添加认证/授权
2. **审计日志**: 所有变更自动记录到 `feature_flag_history` 表
3. **运行时覆盖**: 仅用于紧急场景，建议设置 TTL
4. **权限管理**: `updated_by` 字段记录操作人

## 📖 扩展阅读

- GitHub Issue: #113
- 架构审计报告: `.copilot/session-state/.../checkpoints/001-rag-ui-deep-architecture-audit.md`
- 相关 Issues: #116 #117 #118 #121 #122 #123 #124

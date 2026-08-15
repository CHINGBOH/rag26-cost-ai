# Layer 3 Executor (执行器) 使用指南

## 概述

执行器是 Issue #96 闭环学习系统的第三层（Layer 3）组件，负责：
1. **应用修复补丁** - 将改进建议应用到系统配置
2. **验证效果** - 运行测试验证补丁是否改进了系统性能
3. **对比优化** - 计算优化前后的成功率差异
4. **自动还原** - 如果改进不足，自动还原补丁
5. **更新状态** - 记录补丁执行过程到数据库

## 架构

```
improvement_events 表
    ↓
PatchExecutor (executor.py)
    ├─ apply_patch()      → 应用补丁到 config.yaml
    ├─ verify_patch()     → 运行 test_agent_16.py
    └─ revert_patch()     → 使用 git 还原
    ↓
HTTP API (/api/v1/executor/*)
```

## 核心类和接口

### PatchExecutor

```python
from app.agent.executor import PatchExecutor, PatchApplication, PatchStatus

executor = PatchExecutor()

# 应用补丁
patch = PatchApplication(
    patch_id="patch_001",
    event_id=1,
    affected_route="R4_rerank_weights",
    patch_type="weight",
    patch_payload={"weights": {"bm25": 0.3, "semantic": 0.7}},
    status=PatchStatus.PENDING
)

patch = await executor.apply_patch(patch)  # 状态 → APPLIED
patch = await executor.verify_patch(patch)  # 状态 → VERIFIED 或 REVERTED
```

### PatchStatus 枚举

```python
class PatchStatus(Enum):
    PENDING = "pending"      # 待应用
    APPLYING = "applying"    # 正在应用
    APPLIED = "applied"      # 已应用，待验证
    VERIFYING = "verifying"  # 正在验证
    VERIFIED = "verified"    # 验证成功，保留
    REVERTED = "reverted"    # 验证失败，已还原
    FAILED = "failed"        # 应用或验证失败
```

## 支持的补丁路由（5 条 Route）

### R1: Navigator Dict (R1_navigator_dict)
修改问题类型判别规则

```python
patch_payload = {
    "navigator_dict": {
        "comparison": 'if "对比" in query or "区别" in query',
        "pricing": 'if "价格" in query or "成本" in query'
    }
}
```

### R2: Path Default (R2_path_default)
修改默认检索路径选择

```python
patch_payload = {
    "path": "semantic+bm25"  # 或 "bm25", "semantic", "graph"
}
```

### R3: Planner Examples (R3_planner_examples)
补充 few-shot examples

```python
patch_payload = {
    "examples": [
        {"input": "Q1 content", "output": "A1 content"},
        {"input": "Q2 content", "output": "A2 content"}
    ]
}
```

### R4: Rerank Weights (R4_rerank_weights)
调整重排权重

```python
patch_payload = {
    "weights": {
        "bm25": 0.3,
        "semantic": 0.5,
        "graph": 0.2
    }
}
```

### R5: Tool Priority (R5_tool_priority)
调整工具优先级

```python
patch_payload = {
    "priority": ["retriever", "planner", "verifier", "synthesizer"]
}
```

## HTTP API 使用

### 执行补丁

```bash
POST /api/v1/executor/execute-event?event_id=1

# 返回
{
  "patch_id": "patch_1",
  "status": "verified",
  "verification_result": {
    "before_rate": 0.5,
    "after_rate": 0.75,
    "delta": 0.25,
    "improvement_pct": 50.0,
    "success": true
  },
  "error": null,
  "success": true
}
```

### 查询补丁状态

```bash
GET /api/v1/executor/event-status/1

# 返回
{
  "id": 1,
  "route": "R4_rerank_weights",
  "payload_type": "weight",
  "applied_at": "2025-05-02T10:30:00Z",
  "verified_at": "2025-05-02T10:35:00Z",
  "verification_result": {
    "before_rate": 0.5,
    "after_rate": 0.75,
    "delta": 0.25,
    "improved": true
  },
  "status": "verified"
}
```

## 使用示例

### Python 脚本

```python
import asyncio
from app.agent.executor import execute_improvement_event

async def main():
    result = await execute_improvement_event(event_id=1)
    print(f"Status: {result['status']}")
    print(f"Success: {result['success']}")
    if result['verification_result']:
        vr = result['verification_result']
        print(f"Improvement: {vr['before_rate']:.1%} → {vr['after_rate']:.1%}")

asyncio.run(main())
```

### 数据库查询

```sql
-- 查询所有已验证的补丁
SELECT id, affected_route, applied_at, verified_at, verification_result
FROM improvement_events
WHERE verified_at IS NOT NULL
ORDER BY verified_at DESC;

-- 查询改进最大的补丁
SELECT id, affected_route, verification_result->>'delta' as delta
FROM improvement_events
WHERE verified_at IS NOT NULL
ORDER BY (verification_result->>'delta')::FLOAT DESC
LIMIT 5;
```

## 改进阈值

- **最小改进阈值**: 2% (0.02)
- 如果补丁的成功率改进 < 2%，自动还原
- 例如：从 50% → 51% 会被还原；从 50% → 52% 才会保留

## 关键数据库表

### improvement_events

```sql
CREATE TABLE improvement_events (
  id                  BIGSERIAL PRIMARY KEY,
  source              TEXT,                    -- 'auto' | 'human' | 'external'
  actor               TEXT,                    -- 'auto_executor' | 用户名
  source_feedback_id  BIGINT,                  -- 关联的反馈 ID
  affected_route      TEXT,                    -- R1-R5 中的一个
  patch_payload       JSONB,                   -- 补丁内容
  rationale           TEXT,                    -- 补丁理由
  applied_at          TIMESTAMPTZ,             -- 应用时间
  reverted_at         TIMESTAMPTZ,             -- 还原时间（如果还原了）
  verification_result JSONB,                   -- 验证结果
  ts                  TIMESTAMPTZ DEFAULT NOW()
);
```

### learning_summary

```sql
SELECT success_rate, created_at
FROM learning_summary
ORDER BY created_at DESC LIMIT 10;
```

## 测试

### 单元测试

```bash
cd src/backend/retrieval-service
pytest tests/test_executor.py -v
```

### 集成测试

```bash
# 创建一个 test improvement_event
# 然后调用 API
curl -X POST "http://localhost:8002/api/v1/executor/execute-event?event_id=1"
```

## 故障排查

### 健康检查失败

```
Error: Health check failed: Config syntax error
```

**解决**: 检查 config.yaml 是否有 YAML 语法错误

```bash
python -c "import yaml; yaml.safe_load(open('config/config.yaml'))"
```

### 测试脚本超时

```
Error: Test suite timeout (>10min)
```

**解决**: 检查检索服务是否正常运行

```bash
curl http://localhost:8002/api/v1/health
```

### 基准无法获取

```
Warning: No baseline found, using default 0.5
```

**解决**: 这是正常的，系统会使用 50% 作为默认基准

## 生产部署建议

1. **异步执行** - 在后台任务队列中执行补丁（Celery/RabbitMQ）
2. **超时处理** - 设置合理的超时时间（默认 600s）
3. **监控告警** - 监控补丁失败率，发出告警
4. **版本控制** - 所有补丁应该在 git 中有记录
5. **审核流程** - 关键补丁需要人工审核

## 性能指标

- **平均补丁应用时间**: < 1s
- **测试脚本执行时间**: 5-10 分钟（包含 16 道题）
- **总执行时间**: 10-15 分钟（应用 + 验证 + 还原）

## 日志

执行器的日志会输出到标准 Python logger：

```python
import logging
logger = logging.getLogger("app.agent.executor")
logger.info("✅ Patch applied successfully: patch_001")
```

## 相关文档

- Issue #96: 闭环学习系统设计
- Layer 1 (Signal Collector): `app/agent/signal_collector.py`
- Layer 2 (Architect): `app/agent/root_cause_analyzer.py`
- Layer 3 (Executor): `app/agent/executor.py` ← 本文档

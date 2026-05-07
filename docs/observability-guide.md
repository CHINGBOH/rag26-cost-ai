# Observability 层使用指南

Observability 层是一个决策追踪系统，用于记录所有关键决策点和参数使用情况，支持事后审计和问题追溯。

## 📋 目录

- [快速开始](#快速开始)
- [核心概念](#核心概念)
- [使用指南](#使用指南)
- [API 文档](#api-文档)
- [最佳实践](#最佳实践)
- [审计和分析](#审计和分析)

---

## 快速开始

### 1. 记录一个决策

```python
from config.observability import log_decision, DecisionType
from config.param_registry import param

# 获取参数
threshold = param("followup_coverage_threshold_high")

# 记录决策
decision_id = log_decision(
    decision_type=DecisionType.FOLLOWUP_FILTER,
    context={"question": "什么是RAG?", "coverage": 0.45},
    params_used={"followup_coverage_threshold_high": threshold},
    outcome="rejected",
    reason=f"coverage 0.45 below threshold {threshold}"
)
```

### 2. 使用装饰器自动记录

```python
from config.observability import observe_decision, DecisionType
from config.param_registry import param

@observe_decision(
    DecisionType.FOLLOWUP_FILTER,
    extract_context=lambda args, kwargs: {
        "question": args[0],
        "coverage": args[1]
    },
    extract_outcome=lambda result: result["accepted"]
)
def filter_followup(question: str, coverage: float):
    threshold = param("followup_coverage_threshold_high")
    
    if coverage < threshold:
        return {
            "accepted": False,
            "reason": f"coverage {coverage} below threshold {threshold}"
        }
    
    return {"accepted": True, "reason": "passed"}
```

### 3. 查询决策记录

```python
from config.observability import query_decisions, DecisionType

# 查询最近的 followup 过滤决策
decisions = query_decisions(
    decision_type=DecisionType.FOLLOWUP_FILTER,
    limit=50
)

for decision in decisions:
    print(f"{decision['timestamp']}: {decision['outcome']} - {decision['reason']}")
```

---

## 核心概念

### 决策类型

| 类型 | 说明 | 示例场景 |
|------|------|----------|
| `FOLLOWUP_FILTER` | 追问过滤 | 拒绝低覆盖率的追问建议 |
| `FOLLOWUP_COVERAGE` | 覆盖检测 | 计算问题在 KB 中的覆盖率 |
| `FOLLOWUP_TIER` | 分层决策 | high/med/low 分层 |
| `LEARNING_TRIGGER` | 学习触发 | 检测到知识缺口 |
| `LEARNING_RETEST` | 重测调度 | 决定何时重新测试 |
| `LEARNING_GAP_CLASSIFICATION` | 缺口分类 | 确定缺口优先级 |
| `TOOL_SELECTION` | 工具选择 | 选择使用哪个 tool |
| `TOOL_TIMEOUT` | 工具超时 | 工具执行超时处理 |
| `CONTRACT_ITERATION` | 合约迭代 | 合约验证迭代 |
| `CONTRACT_CONVERGENCE` | 收敛判断 | 决定是否收敛 |
| `EVALUATION_SCORE` | 评分计算 | 答案质量评分 |
| `EVALUATION_QUALITY` | 质量判断 | good/bad 判断 |
| `RETRIEVAL_STRATEGY` | 检索策略 | 选择检索方法 |
| `RETRIEVAL_RERANK` | 重排序 | 重排序决策 |
| `AGENT_ITERATION` | Agent 迭代 | 每次 Agent 循环 |
| `AGENT_FINAL` | 最终决策 | Agent 最终输出 |

### 决策记录结构

```python
{
    "decision_id": "uuid",
    "decision_type": "followup_filter",
    "timestamp": "2024-01-15T10:30:00Z",
    "context": {
        "question": "什么是RAG?",
        "coverage": 0.45
    },
    "params_used": {
        "followup_coverage_threshold_high": 0.65
    },
    "outcome": "rejected",
    "reason": "coverage 0.45 below threshold 0.65",
    "metadata": {},
    "parent_id": null  # 支持决策链
}
```

### 优先级和性能

- **异步写入**：决策记录先写入内存缓冲区，后台批量flush到文件
- **批量flush**：缓冲区满 100 条或手动调用 `DecisionLogger.flush()` 时写入
- **低开销**：决策记录不阻塞业务逻辑，性能影响极小

---

## 使用指南

### 记录决策的 3 种方式

#### 1. 直接调用（推荐用于简单场景）

```python
from config.observability import log_decision, DecisionType
from config.param_registry import param

def filter_followup(question: str, coverage: float):
    threshold = param("followup_coverage_threshold_high")
    
    if coverage < threshold:
        log_decision(
            decision_type=DecisionType.FOLLOWUP_FILTER,
            context={"question": question, "coverage": coverage},
            params_used={"followup_coverage_threshold_high": threshold},
            outcome="rejected",
            reason=f"coverage {coverage} below threshold {threshold}"
        )
        return False
    
    log_decision(
        decision_type=DecisionType.FOLLOWUP_FILTER,
        context={"question": question, "coverage": coverage},
        params_used={"followup_coverage_threshold_high": threshold},
        outcome="accepted",
        reason="passed"
    )
    return True
```

#### 2. 使用装饰器（推荐用于复杂函数）

```python
from config.observability import observe_decision, DecisionType

@observe_decision(
    DecisionType.TOOL_SELECTION,
    extract_context=lambda args, kwargs: {"query": args[0]},
    extract_params=lambda args, kwargs, result: result.get("params_used", {}),
    extract_outcome=lambda result: result["tool_name"]
)
def select_tool(query: str):
    # 工具选择逻辑...
    selected_tool = "text_search"
    
    return {
        "tool_name": selected_tool,
        "reason": "Query requires KB search",
        "params_used": {"tool_selection_temperature": 0.0}
    }
```

#### 3. 手动构造 Decision 对象

```python
from config.observability import Decision, DecisionLogger, DecisionType

decision = Decision(
    decision_type=DecisionType.LEARNING_RETEST,
    context={"gap_id": "gap_123", "retest_count": 3},
    params_used={
        "learning_retest_interval": 24,
        "learning_retest_backoff_multiplier": 2.0
    },
    outcome="scheduled",
    reason="Backoff to 48 hours after 3rd failure",
    metadata={"next_retest_at": "2024-01-16T10:30:00Z"}
)

DecisionLogger.log(decision)
```

### 查询决策记录

```python
from config.observability import DecisionLogger, DecisionType
from datetime import datetime, timedelta

# 查询所有 followup 过滤决策
decisions = DecisionLogger.query(
    decision_type=DecisionType.FOLLOWUP_FILTER,
    limit=100
)

# 查询最近 24 小时的决策
start_time = datetime.now() - timedelta(hours=24)
decisions = DecisionLogger.query(start_time=start_time, limit=500)

# 查询使用了特定参数的决策
decisions = DecisionLogger.query(
    param_name="followup_coverage_threshold_high",
    limit=100
)

# 获取统计信息
stats = DecisionLogger.get_stats()
print(f"Total logged: {stats['total_logged']}")
print(f"By type: {stats['by_type']}")
```

### Flush 缓冲区

```python
from config.observability import DecisionLogger

# 手动 flush（确保持久化）
DecisionLogger.flush()
```

---

## API 文档

Observability 层提供 REST API 进行查询和审计。

### 1. 查询决策记录

```bash
GET /api/v1/observability/decisions

# 按类型过滤
GET /api/v1/observability/decisions?decision_type=followup_filter

# 按时间范围
GET /api/v1/observability/decisions?start_time=2024-01-01T00:00:00Z&end_time=2024-01-02T00:00:00Z

# 按参数过滤
GET /api/v1/observability/decisions?param_name=followup_coverage_threshold_high

# 限制返回数量
GET /api/v1/observability/decisions?limit=50
```

**响应示例：**

```json
{
  "total": 42,
  "decisions": [
    {
      "decision_id": "123e4567-e89b-12d3-a456-426614174000",
      "decision_type": "followup_filter",
      "timestamp": "2024-01-15T10:30:00Z",
      "context": {
        "question": "什么是RAG?",
        "coverage": 0.45
      },
      "params_used": {
        "followup_coverage_threshold_high": 0.65
      },
      "outcome": "rejected",
      "reason": "coverage 0.45 below threshold 0.65",
      "metadata": {},
      "parent_id": null
    }
  ]
}
```

### 2. 获取统计信息

```bash
GET /api/v1/observability/stats
```

**响应示例：**

```json
{
  "total_logged": 1234,
  "buffer_size": 42,
  "by_type": {
    "followup_filter": 456,
    "learning_trigger": 123,
    "tool_selection": 234
  },
  "by_outcome": {
    "accepted": 600,
    "rejected": 400
  },
  "log_file": "logs/decisions/decisions_2024-01-15.jsonl"
}
```

### 3. 获取单个决策

```bash
GET /api/v1/observability/decision/{decision_id}
```

### 4. 强制 Flush 缓冲区

```bash
POST /api/v1/observability/flush
```

### 5. 生成审计报告

```bash
GET /api/v1/observability/audit

# 指定审计周期
GET /api/v1/observability/audit?period=24h  # 1h, 24h, 7d, 30d
```

**响应示例：**

```json
{
  "period": "24h",
  "total_decisions": 1234,
  "by_type": {
    "followup_filter": 456,
    "learning_trigger": 123,
    "tool_selection": 234
  },
  "param_usage": {
    "followup_coverage_threshold_high": 456,
    "learning_retest_interval": 123
  },
  "top_params": [
    {"param": "followup_coverage_threshold_high", "usage_count": 456},
    {"param": "learning_retest_interval", "usage_count": 123}
  ],
  "decision_patterns": [
    {
      "pattern": "high_followup_rejection_rate",
      "count": 800,
      "percentage": 64.8,
      "severity": "warning"
    }
  ],
  "recommendations": [
    "High followup rejection rate (>70%). Consider lowering coverage thresholds.",
    "Parameter 'followup_coverage_threshold_high' used frequently. Consider A/B testing."
  ]
}
```

---

## 最佳实践

### ✅ DO

1. **记录所有关键决策点**

   ```python
   # ✅ Good - 记录 followup 过滤
   if coverage < threshold:
       log_decision(...)
       return False
   
   # ❌ Bad - 没有记录
   if coverage < threshold:
       return False
   ```

2. **包含足够的上下文**

   ```python
   # ✅ Good - 上下文完整
   context = {
       "question": question,
       "coverage": coverage,
       "chunk_count": len(chunks),
       "source": "graph_neighbor"
   }
   
   # ❌ Bad - 上下文不足
   context = {"coverage": coverage}
   ```

3. **记录使用的参数**

   ```python
   # ✅ Good - 记录所有相关参数
   params_used = {
       "followup_coverage_threshold_high": threshold_high,
       "followup_coverage_threshold_med": threshold_med,
       "followup_min_high_tier_count": min_high_count
   }
   
   # ❌ Bad - 没有记录参数
   params_used = {}
   ```

4. **提供清晰的决策理由**

   ```python
   # ✅ Good - 理由清晰
   reason = f"coverage {coverage:.2f} below med threshold {threshold_med:.2f}"
   
   # ❌ Bad - 理由含糊
   reason = "rejected"
   ```

### ❌ DON'T

1. **不要在高频路径记录过多决策**

   ```python
   # ❌ Bad - 每个 chunk 都记录（每次数百条）
   for chunk in chunks:
       log_decision(...)
   
   # ✅ Good - 只记录汇总决策
   log_decision(
       context={"total_chunks": len(chunks), "filtered_chunks": len(filtered)}
   )
   ```

2. **不要包含敏感信息**

   ```python
   # ❌ Bad - 包含用户隐私
   context = {"user_email": "user@example.com", "query": "..."}
   
   # ✅ Good - 使用匿名 ID
   context = {"user_id": "hashed_id", "query": "..."}
   ```

3. **不要依赖内存查询**

   内存缓冲区只保留最近的决策。历史查询需要读取日志文件。

---

## 审计和分析

### 日常审计

```bash
# 查看过去 24 小时的决策统计
curl http://localhost:8002/api/v1/observability/audit?period=24h

# 检查高频参数使用
curl http://localhost:8002/api/v1/observability/stats | jq '.by_type'
```

### 问题追溯

**场景**：用户报告"追问建议都不能回答"

**步骤 1：查询 followup 决策**

```bash
curl 'http://localhost:8002/api/v1/observability/decisions?decision_type=followup_filter&limit=100' \
  | jq '.decisions[] | select(.outcome == "accepted")'
```

**步骤 2：分析参数使用**

```bash
curl 'http://localhost:8002/api/v1/observability/decisions?param_name=followup_coverage_threshold_high' \
  | jq '.decisions[] | {coverage: .context.coverage, threshold: .params_used.followup_coverage_threshold_high, outcome: .outcome}'
```

**步骤 3：检查决策模式**

```bash
curl 'http://localhost:8002/api/v1/observability/audit?period=7d' \
  | jq '.decision_patterns'
```

### 参数调优

**目标**：优化 `followup_coverage_threshold_high`

**步骤 1：收集当前使用数据**

```python
from config.observability import DecisionLogger, DecisionType

decisions = DecisionLogger.query(decision_type=DecisionType.FOLLOWUP_FILTER, limit=1000)

# 分析 accepted vs rejected
accepted = [d for d in decisions if d.outcome in ("accepted", True)]
rejected = [d for d in decisions if d.outcome in ("rejected", False)]

print(f"Accepted: {len(accepted)} ({len(accepted)/len(decisions)*100:.1f}%)")
print(f"Rejected: {len(rejected)} ({len(rejected)/len(decisions)*100:.1f}%)")

# 分析 coverage 分布
import numpy as np
accepted_coverage = [d.context.get("coverage", 0) for d in accepted]
rejected_coverage = [d.context.get("coverage", 0) for d in rejected]

print(f"Accepted mean coverage: {np.mean(accepted_coverage):.2f}")
print(f"Rejected mean coverage: {np.mean(rejected_coverage):.2f}")
```

**步骤 2：A/B 测试新阈值**

```python
from config.param_registry import ParamRegistry

# 临时覆盖（调试用）
ParamRegistry.set_runtime("followup_coverage_threshold_high", 0.70)

# 运行测试...

# 收集新的决策数据并对比
```

**步骤 3：持久化最优参数**

```bash
# 更新环境变量
export PARAM__FOLLOWUP_COVERAGE_THRESHOLD_HIGH=0.70

# 或更新配置文件
# config/default_params.py
```

### 日志文件分析

决策日志保存在 `logs/decisions/` 目录，每天一个文件：

```bash
# 查看今天的决策日志
cat logs/decisions/decisions_2024-01-15.jsonl | jq .

# 统计决策类型
cat logs/decisions/decisions_2024-01-15.jsonl | jq -r '.decision_type' | sort | uniq -c

# 查找高频拒绝
cat logs/decisions/decisions_2024-01-15.jsonl | jq 'select(.outcome == "rejected")' | jq -r '.reason' | sort | uniq -c

# 分析参数使用
cat logs/decisions/decisions_2024-01-15.jsonl | jq -r '.params_used | keys[]' | sort | uniq -c
```

---

## FAQ

### Q: Observability 和参数注册表有什么区别？

**参数注册表**：
- 管理参数**定义**（默认值、rationale、范围）
- 静态配置

**Observability**：
- 记录参数**使用**（运行时决策）
- 动态追踪

两者配合使用：
1. 参数注册表定义参数
2. Observability 记录参数使用情况
3. 审计报告分析参数效果
4. 参数注册表更新参数定义

### Q: 决策记录会占用多少磁盘空间？

每条决策记录约 **200-500 bytes**（JSON格式）。

估算：
- 每天 10,000 条决策 × 500 bytes = 5 MB/天
- 保留 30 天 = 150 MB

建议：
- 定期清理旧日志（> 30 天）
- 或压缩归档

### Q: 如何在测试中禁用决策记录？

```python
from config.observability import DecisionLogger

# 测试前清空缓冲区
DecisionLogger.clear_buffer()

# 运行测试...

# 测试后再次清空
DecisionLogger.clear_buffer()
```

或者设置环境变量：

```bash
export OBSERVABILITY_ENABLED=false
```

### Q: 决策链（decision chain）是什么？

决策链用于追踪一系列相关的决策。例如：

```
Agent 迭代决策 (parent)
  ├─ Tool 选择决策 (child 1)
  ├─ Retrieval 策略决策 (child 2)
  └─ Evaluation 决策 (child 3)
```

使用 `parent_id` 字段建立父子关系：

```python
# 父决策
parent_id = log_decision(
    decision_type=DecisionType.AGENT_ITERATION,
    ...
)

# 子决策
log_decision(
    decision_type=DecisionType.TOOL_SELECTION,
    parent_id=parent_id,
    ...
)
```

---

## 更多资源

- [参数注册表使用指南](./param-registry-guide.md)
- [Feature Flag 使用指南](./feature-flags-guide.md)
- [GitHub Issue #115](https://github.com/CHINGBOH/RAG26/issues/115) - Observability Layer 实施追踪
- [GitHub Issue #128](https://github.com/CHINGBOH/RAG26/issues/128) - RAG Architecture Quality Audit Epic

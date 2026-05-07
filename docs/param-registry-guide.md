# 参数注册表使用指南

参数注册表是一个中心化的参数管理系统，用于统一管理所有可调参数（阈值、超时、限制等），避免硬编码 magic numbers。

## 📋 目录

- [快速开始](#快速开始)
- [核心概念](#核心概念)
- [使用指南](#使用指南)
- [API 文档](#api-文档)
- [最佳实践](#最佳实践)
- [迁移指南](#迁移指南)
- [审计工具](#审计工具)

---

## 快速开始

### 1. 注册一个参数

```python
from config.param_registry import register_param, ParamCategory

register_param(
    name="followup_coverage_threshold_high",
    value=0.65,
    rationale="A/B test 2024-Q1: 0.65 achieved 75% answerability vs 0.45 at 45%",
    category=ParamCategory.FOLLOWUP,
    source="app/agent/graph.py:3799",
    unit="score",
    min_value=0.5,
    max_value=0.9
)
```

### 2. 使用参数

```python
from config.param_registry import param

# 简单获取
threshold = param("followup_coverage_threshold_high")

# 带默认值
timeout = param("api_timeout", default=60)
```

### 3. 使用预设值（top_k）

```python
from config.retrieval_presets import RetrievalPresets

# 使用语义化的预设值
results = text_search(query, top_k=RetrievalPresets.NARROW)  # 3
results = text_search(query, top_k=RetrievalPresets.STANDARD)  # 8
results = text_search(query, top_k=RetrievalPresets.BROAD)  # 12
```

---

## 核心概念

### 参数分类

| 分类 | 说明 | 示例 |
|------|------|------|
| `RETRIEVAL` | 检索相关参数 | top_k, threshold, multiplier |
| `FOLLOWUP` | 追问生成 | coverage_threshold, max_suggestions |
| `LEARNING` | 学习系统 | retest_interval, backoff_multiplier |
| `EVALUATION` | 评估相关 | confidence_weight, chunk_bonus |
| `CONTRACT` | 合约验证 | max_iterations, convergence_policy |
| `TIMEOUT` | 超时设置 | llm_timeout, tool_timeout |
| `AGENT` | Agent 行为 | max_tool_iterations, temperature |
| `GENERAL` | 通用参数 | 其他未分类参数 |

### 优先级顺序

参数值按以下优先级解析：

```
运行时覆盖 > 环境变量 > 注册的默认值 > fallback default
```

1. **运行时覆盖**（最高优先级）
   - 用于临时调试
   - 不持久化，重启后失效
   - 通过 API 设置

2. **环境变量**
   - 格式：`PARAM__<NAME>`（双下划线）
   - 示例：`PARAM__FOLLOWUP_COVERAGE_THRESHOLD_HIGH=0.70`
   - 在启动时读取

3. **注册的默认值**
   - 代码中通过 `register_param()` 注册
   - 必须提供设定理由（rationale）

4. **fallback default**
   - 调用 `param(name, default=value)` 时提供
   - 仅在参数未注册时使用

---

## 使用指南

### 注册新参数

完整示例：

```python
from config.param_registry import ParamRegistry, ParamCategory

ParamRegistry.register(
    name="learning_retest_interval",
    value=24,
    rationale="Daily retest interval balances resource usage and feedback speed. "
              "Shorter intervals waste resources, longer delays feedback too much.",
    category=ParamCategory.LEARNING,
    source="app/agent/learning_listener.py:89",
    unit="hours",
    min_value=6,
    max_value=72,
    deprecated=False
)
```

**字段说明：**

- `name` (必填): 参数唯一标识，使用 `snake_case`
- `value` (必填): 默认值
- `rationale` (必填): **设定理由**，必须说明为什么选这个值
- `category` (可选): 参数分类，默认 `GENERAL`
- `source` (可选): 定义位置，格式 `file:line`
- `unit` (可选): 单位，如 `seconds`, `percentage`, `count`
- `min_value` (可选): 最小值限制
- `max_value` (可选): 最大值限制
- `deprecated` (可选): 是否废弃
- `replacement` (可选): 如果废弃，指定替代参数

### 获取参数值

```python
from config.param_registry import param, ParamRegistry

# 推荐：使用便捷函数
threshold = param("followup_coverage_threshold_high")

# 或者：使用类方法
threshold = ParamRegistry.get("followup_coverage_threshold_high")

# 带默认值
timeout = param("api_timeout", default=60)

# 获取所有参数
all_params = ParamRegistry.get_all()

# 按分类获取
followup_params = ParamRegistry.get_by_category(ParamCategory.FOLLOWUP)
```

### 运行时覆盖（调试用）

```python
from config.param_registry import ParamRegistry

# 临时覆盖参数
ParamRegistry.set_runtime("followup_coverage_threshold_high", 0.70)

# 清除单个覆盖
ParamRegistry.clear_runtime("followup_coverage_threshold_high")

# 清除所有覆盖
ParamRegistry.clear_runtime()
```

⚠️ **警告**：运行时覆盖不持久化，重启后失效。生产环境慎用。

### 使用环境变量

在 `.env` 或环境中设置：

```bash
# 格式：PARAM__<参数名大写>
PARAM__FOLLOWUP_COVERAGE_THRESHOLD_HIGH=0.70
PARAM__LEARNING_RETEST_INTERVAL=48
PARAM__LLM_TIMEOUT_DEFAULT=180
```

---

## API 文档

参数注册表提供 REST API 进行查询和管理。

### 1. 列出所有参数

```bash
GET /api/v1/params/

# 按分类过滤
GET /api/v1/params/?category=followup

# 搜索参数名
GET /api/v1/params/?search=threshold

# 只显示非废弃参数
GET /api/v1/params/?deprecated=false
```

**响应示例：**

```json
{
  "total": 25,
  "parameters": [
    {
      "name": "followup_coverage_threshold_high",
      "value": 0.65,
      "rationale": "A/B test 2024-Q1: 0.65 achieved 75% answerability",
      "category": "followup",
      "source": "app/agent/graph.py:3799",
      "unit": "score",
      "min_value": 0.5,
      "max_value": 0.9,
      "deprecated": false,
      "replacement": null,
      "registered_at": "2024-01-15T10:30:00Z",
      "last_updated": "2024-01-15T10:30:00Z"
    }
  ]
}
```

### 2. 获取单个参数

```bash
GET /api/v1/params/{name}
```

### 3. 按分类获取

```bash
GET /api/v1/params/category/{category}

# 示例
GET /api/v1/params/category/followup
GET /api/v1/params/category/retrieval
```

### 4. 运行时覆盖

```bash
PUT /api/v1/params/{name}/runtime
Content-Type: application/json

{
  "value": 0.70
}
```

### 5. 清除运行时覆盖

```bash
DELETE /api/v1/params/{name}/runtime
```

### 6. 审计参数注册表

```bash
GET /api/v1/params/audit
```

**响应示例：**

```json
{
  "issues": {
    "missing_rationale": ["param_without_reason"],
    "deprecated": ["old_threshold"],
    "out_of_range": ["invalid_param: 999 > 100"],
    "unknown_source": ["mystery_param"]
  },
  "summary": "⚠️  Found 4 issues across 3 categories."
}
```

### 7. 查看变更历史

```bash
GET /api/v1/params/changes?limit=50
```

---

## 最佳实践

### ✅ DO

1. **必须提供有意义的 rationale**

   ```python
   # ✅ Good
   rationale="A/B test 2024-Q1 showed 0.65 achieved 75% answerability, "
             "while 0.45 only achieved 45%. Raised to reduce unanswerable suggestions."
   
   # ❌ Bad
   rationale="TODO"
   rationale="Good threshold"
   ```

2. **使用预设值代替硬编码**

   ```python
   # ✅ Good
   from config.retrieval_presets import RetrievalPresets
   results = text_search(query, top_k=RetrievalPresets.NARROW)
   
   # ❌ Bad
   results = text_search(query, top_k=3)  # Magic number
   ```

3. **设置合理的范围限制**

   ```python
   # ✅ Good
   ParamRegistry.register(
       name="timeout",
       value=120,
       min_value=30,  # 太短会频繁超时
       max_value=300  # 太长影响用户体验
   )
   ```

4. **废弃参数时提供替代方案**

   ```python
   ParamRegistry.register(
       name="old_threshold",
       deprecated=True,
       replacement="new_threshold_v2"
   )
   ```

### ❌ DON'T

1. **不要在业务代码中硬编码参数**

   ```python
   # ❌ Bad
   if score > 0.65:
       return "high"
   
   # ✅ Good
   threshold = param("followup_coverage_threshold_high")
   if score > threshold:
       return "high"
   ```

2. **不要省略 rationale**

   ```python
   # ❌ Bad
   ParamRegistry.register("threshold", 0.5, rationale="")
   
   # ✅ Good
   ParamRegistry.register(
       "threshold", 0.5,
       rationale="Empirical testing showed 0.5 balances precision and recall"
   )
   ```

3. **不要在生产环境依赖运行时覆盖**

   运行时覆盖是调试工具，不持久化。生产环境请使用：
   - 环境变量
   - 配置文件
   - Feature Flag 系统（持久化配置）

---

## 迁移指南

### 从硬编码迁移到参数注册表

**步骤 1：识别硬编码参数**

```bash
# 运行审计脚本
python scripts/audit_params.py --verbose
```

**步骤 2：注册参数**

在 `config/default_params.py` 中添加：

```python
ParamRegistry.register(
    name="your_param_name",
    value=<current_hardcoded_value>,
    rationale="<why this value>",
    category=ParamCategory.<CATEGORY>,
    source="<file:line>"
)
```

**步骤 3：替换硬编码**

```python
# Before
if coverage >= 0.65:
    tier = "high"

# After
from config.param_registry import param
threshold = param("followup_coverage_threshold_high")
if coverage >= threshold:
    tier = "high"
```

**步骤 4：测试**

```python
# 测试环境变量覆盖
export PARAM__YOUR_PARAM_NAME=<test_value>
python your_script.py

# 测试运行时覆盖
curl -X PUT http://localhost:8002/api/v1/params/your_param_name/runtime \
  -H "Content-Type: application/json" \
  -d '{"value": <test_value>}'
```

### 迁移示例

**Before (硬编码):**

```python
# app/agent/graph.py:3799
def _coverage_tier(score: float) -> str:
    if score >= 0.65:
        return "high"
    if score >= 0.45:
        return "med"
    return "low"
```

**After (参数注册表):**

```python
from config.param_registry import param

def _coverage_tier(score: float) -> str:
    high_threshold = param("followup_coverage_threshold_high")
    med_threshold = param("followup_coverage_threshold_med")
    
    if score >= high_threshold:
        return "high"
    if score >= med_threshold:
        return "med"
    return "low"
```

**注册参数：**

```python
# config/default_params.py
ParamRegistry.register(
    name="followup_coverage_threshold_high",
    value=0.65,
    rationale="A/B test 2024-Q1: 0.65 achieved 75% answerability",
    category=ParamCategory.FOLLOWUP,
    source="app/agent/graph.py:3799",
    unit="score",
    min_value=0.5,
    max_value=0.9
)
```

---

## 审计工具

### 运行参数审计

```bash
# 基础审计
python scripts/audit_params.py

# 详细输出
python scripts/audit_params.py --verbose

# 扫描特定目录
python scripts/audit_params.py --root src/backend/retrieval-service

# 导出审计结果
python scripts/audit_params.py --export audit_result.json
```

### 审计报告示例

```
================================================================================
参数审计报告
================================================================================

## 1. 参数注册表覆盖率

总注册参数: 25

按分类统计:
  - followup: 5
  - learning: 4
  - retrieval: 6
  - evaluation: 3
  - contract: 2
  - timeout: 3
  - agent: 2

## 2. Magic Numbers 检测

发现 47 个 magic numbers

## 3. 硬编码阈值检测

发现 23 个硬编码阈值

类型: threshold (8 个)
  app/agent/graph.py:3799
    if score >= 0.65:

类型: top_k (6 个)
  app/agent/tools.py:123
    raw = _ts.invoke({"query": question, "top_k": 3})

## 4. 改进建议

1. 将所有 magic numbers 注册到参数注册表
2. 为每个参数添加设定理由 (rationale)
3. 使用 RetrievalPresets 替代硬编码 top_k
4. 使用 param() 函数获取参数值
5. 定期运行此审计脚本，确保新参数也被注册
```

---

## FAQ

### Q: 参数注册表和 Feature Flag 有什么区别？

**参数注册表**：
- 管理**数值型**配置（阈值、超时、限制）
- 重点在**可追溯性**（rationale、audit）
- 不需要数据库支持

**Feature Flag**：
- 管理**开关型**配置（功能启用/禁用）
- 重点在**灰度发布**和**紧急回滚**
- 需要数据库持久化

### Q: 运行时覆盖会持久化吗？

**不会**。运行时覆盖仅在当前进程生命周期内有效，重启后失效。

如需持久化，请使用：
- 环境变量（`PARAM__<NAME>`）
- 配置文件
- Feature Flag 系统（for boolean flags）

### Q: 如何在测试中覆盖参数？

```python
from config.param_registry import ParamRegistry

def test_something():
    # 保存原值
    old_value = ParamRegistry.get("param_name")
    
    # 覆盖
    ParamRegistry.set_runtime("param_name", test_value)
    
    try:
        # 运行测试
        result = your_function()
        assert result == expected
    finally:
        # 恢复原值
        ParamRegistry.clear_runtime("param_name")
```

### Q: 如何审计缺少 rationale 的参数？

```bash
# 运行审计脚本
python scripts/audit_params.py --verbose

# 或者使用 API
curl http://localhost:8002/api/v1/params/audit
```

---

## 更多资源

- [Feature Flag 使用指南](./feature-flags-guide.md)
- [配置管理最佳实践](./config-best-practices.md)
- [GitHub Issue #114](https://github.com/CHINGBOH/RAG26/issues/114) - Parameter Registry 实施追踪
- [GitHub Issue #128](https://github.com/CHINGBOH/RAG26/issues/128) - RAG Architecture Quality Audit Epic

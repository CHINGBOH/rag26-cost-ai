# RAG Dashboard — 全量代码检测报告

> 检测日期：2026-04-24
> 检测工具：Python AST 静态分析 + TypeScript 编译检查 + 手动代码审查
> 检测范围：config/, src/, tools/, ocr_tools/, scripts/, tests/, packages/

---

## 目录

1. [🔴 语法错误 (CRITICAL)](#一语法错误-critical)
2. [🔴 安全漏洞 (CRITICAL)](#二安全漏洞-critical)
3. [🟠 代码质量问题 (MAJOR)](#三代码质量问题-major)
4. [🟡 架构与配置问题 (MODERATE)](#四架构与配置问题-moderate)
5. [🟢 轻微问题 (MINOR)](#五轻微问题-minor)
6. [📊 统计摘要与修复建议](#六统计摘要与修复建议)

---

## 一、语法错误 (CRITICAL)

### 1.1 缺少函数调用括号

**文件**: `ocr_tools/generate_report.py` 第 241 行

```python
# ❌ 错误
report.append"- `{文件名}_ocr.json`: 完整OCR结果")

# ✅ 已修复
report.append("- `{文件名}_ocr.json`: 完整OCR结果")
```

### 1.2 路径含非法字符导致语法错误

**文件**: `trash/index_documents.py` 第 13 行

```python
# ❌ Python 变量/模块名不能包含连字符
from src.backend.python-legacy.services.document_processor import DocumentProcessor
```

> **状态**: 该文件已移入 `trash/` 目录，不影响主业务流程。

### 1.3 try 块缺少 except/finally

**文件**: `trash/tei_local_simple.py` 第 52 行

```python
try:
    # ... 代码块
# ❌ 缺少 except 或 finally 子句
```

> **状态**: 该文件已移入 `trash/` 目录，不影响主业务流程。

### 1.4 无效的转义序列

**文件**: `src/backend/python-legacy/services/ocr_quality_validator.py` 第 487 行

```python
# SyntaxWarning: invalid escape sequence '\.'
r'，。！？《》（）【】、：；"''\.\-\[\]·｜│]',
```

> `\.` 和 `\-` 在 Python raw string 中虽不会报错，但会触发 SyntaxWarning，应使用双反斜杠或确认不需要转义。

---

## 二、安全漏洞 (CRITICAL)

### 2.1 硬编码数据库密码

多达 **28 个文件** 中硬编码了 PostgreSQL 密码 `rag_password`，存在严重的安全风险。若代码仓库泄露，数据库将直接暴露。

#### `tools/` 目录（8 个文件）

| 文件 | 行号 | 原文 |
|------|------|------|
| `tools/embed_and_sync_qdrant.py` | 20 | `password='rag_password'` |
| `tools/ingest_qa_excel.py` | 12 | `password='rag_password'` |
| `tools/run_ingest.py` | 36 | `password='rag_password'` |
| `tools/_patch_ingest.py` | 17 | `password='rag_password'` |
| `tools/ocr_ingest_pipeline.py` | 28 | `password='rag_password'` |
| `tools/ocr_2026_01_pipeline.py` | 30 | `password='rag_password'` |
| `tools/ocr_automation/config.py` | 54 | `password=self.cfg.db.password` |
| `tools/ocr_automation/store/pg_store.py` | 25 | `user=user, password=password` |

#### `src/backend/python-legacy/tools/` 目录（15+ 个文件）

| 文件 | 行号 | 原文 |
|------|------|------|
| `enhanced_ocr_processor.py` | 366, 431, 497 | `password=POSTGRES_PASSWORD` |
| `test_real_models.py` | 218, 281 | `password="rag_password"` |
| `quick_processor.py` | 244, 295, 343 | `password=POSTGRES_PASSWORD` |
| `agent_tools.py` | 37 | `password=rag_password` |
| `complete_rag_service.py` | 106 | `password="rag_password"` |
| `simple_ocr_processor.py` | 188, 250, 312 | `password=POSTGRES_PASSWORD` |
| `ocr_import_postgres_tables.py` | - | 硬编码密码 |
| `import_fee_rates.py` | - | 硬编码密码 |
| `ocr_import_postgres.py` | - | 硬编码密码 |
| `ocr_text_to_pg.py` | - | 硬编码密码 |
| `import_shenzhen_price_v2.py` | - | 硬编码密码 |
| `rag_cli.py` | - | 硬编码密码 |
| `ocr_json_to_pg.py` | - | 硬编码密码 |

#### `src/backend/python-legacy/services/` 目录

| 文件 | 行号 | 原文 |
|------|------|------|
| `embedding_service.py` | 91 | `password=POSTGRES_PASSWORD` |

#### `src/backend/retrieval-service/` 目录

| 文件 | 行号 | 原文 |
|------|------|------|
| `app/eval/ragas_pipeline.py` | 33 | `password="rag_password"` |

#### 典型示例

```python
# tools/embed_and_sync_qdrant.py:20
DB_CONFIG = dict(
    host='localhost', dbname='rag_db',
    user='rag_user', password='rag_password'
)

# src/backend/python-legacy/tools/agent_tools.py:37
conn_string = "host=localhost port=5432 dbname=rag_db user=rag_user password=rag_password"
```

**建议**: 全部改为从环境变量或配置中心读取，不要硬编码在任何代码文件中。

---

### 2.2 沙箱代码执行 (`exec()` / `eval()`)

| 文件 | 行号 | 风险等级 | 说明 |
|------|------|----------|------|
| `src/backend/retrieval-service/app/agent/tools.py` | 695 | 🟠 中等 | `eval()` 限制了 `__builtins__` 但仍有被绕过理论风险 |
| `src/backend/retrieval-service/app/agent/tools.py` | 719 | 🟠 中等 | `python_eval` tool 使用受限沙箱执行 |
| `src/backend/retrieval-service/infrastructure/sandbox_entry.py` | 108 | 🟢 较低 | AST 静态检查 + 受限 builtins，但缺少执行超时保护 |

```python
# tools.py:695 - 存在潜在风险的 eval
allowed_names = {"abs": abs, "round": round, "max": max, "min": min, "sum": sum}
result = eval(expression, {"__builtins__": {}}, allowed_names)
```

**建议**: 考虑使用 `ast.literal_eval` 替代简单表达式计算，并为沙箱执行增加超时机制。

---

## 三、代码质量问题 (MAJOR)

### 3.1 裸 `except:` 异常捕获（约 20 处）

裸 `except:` 会误捕获 `KeyboardInterrupt`、`SystemExit` 和 `GeneratorExit` 等系统异常，应改为 `except Exception:`。

| 文件 | 行号 |
|------|------|
| `ocr_tools/process_large_files.py` | 59, 283 |
| `ocr_tools/merge_results.py` | 177 |
| `ocr_tools/generate_report.py` | 58 |
| `tools/ocr_2026_01_pipeline.py` | 130 |
| `tools/ocr_automation/cli.py` | 459 |
| `tools/ocr_automation/parser/table_rebuilder.py` | 465 |
| `tools/ocr_automation/parser/price_normalizer.py` | 22 |
| `tools/ocr_automation/engine/chart_extractor.py` | 332 |
| `tools/ocr_automation/engine/vision_llm.py` | 127 |
| `scripts/check-governance.py` | 452, 462 |
| `src/backend/retrieval-service/infrastructure/vector_store.py` | 56 |

```python
# ❌ 错误 - 会捕获 SystemExit, KeyboardInterrupt
try:
    ...
except:
    pass

# ✅ 正确 - 只捕获异常
try:
    ...
except Exception as e:
    logger.error(f"处理失败: {e}")
```

---

### 3.2 TypeScript 未使用的导入和变量

| 文件 | 行号 | 未使用的符号 |
|------|------|-------------|
| `src/backend/server/src/index.ts` | 56 | `const pump = promisify(pipeline)` — 定义但从未使用 |
| `src/backend/server/src/index.ts` | 49 | `createFourDatabaseTools`, `AgentOptions`, `StructuredOutput` — 从模块导入但未直接使用 |
| `src/backend/server/src/services/PostgresPersistenceService.ts` | 6 | `PoolClient` — 从 `pg` 导入但从未使用 |

---

### 3.3 使用 `console.log` 而非统一 Logger

`src/backend/server/src/` 下多处直接使用 `console.log/warn/error`，而非项目中定义的统一 `logger` 服务。

| 文件 | 行号 |
|------|------|
| `RecursionController.ts` | 40, 75, 112, 140, 143, 151, 210, 228 |
| `AuthService.ts` | 68, 96, 107, 113, 120, 157, 248 |
| `YoloCodeGenerator.ts` | 42, 96, 103 |

```typescript
// ❌ 应使用统一 logger
console.warn('[RecursionController] ...');
console.log('[AuthService] ...');

// ✅ 推荐
logger.warn('...');
logger.info('...');
```

---

### 3.4 Docker Compose YAML 语法错误

**文件**: `docker-compose.modern.yml` 第 47 行

```
# ❌ YAML 解析错误：缩进/格式问题导致无法正常解析
command: python -c "
from rag_llm_pipeline import RerankService
```

> 该文件多行 shell command 的 YAML 缩进不正确，Docker 无法解析该文件。

---

### 3.5 后端 Python 代码重复

`src/backend/python-legacy/` 与 `src/backend/retrieval-service/` 两个目录存在严重的代码重复：

- `domain/models.py` — 几乎相同
- `infrastructure/adapters/unified/` — 高度相似
- `domain_models/` — 多个模型类重复

> 如果修复一个 bug 或添加功能，容易遗漏另一处。建议将公共代码提取到 `packages/shared/`。

---

## 四、架构与配置问题 (MODERATE)

### 4.1 数据库 Schema 不一致

- `src/database/schema.sql` 中已有注释说明与实际运行表结构不一致
- `sql/migrations/` 中有另一个版本的 schema
- 项目同时维护多个 schema 定义，容易产生 drift

### 4.2 缺少 `__init__.py`

**文件**: `src/backend/retrieval-service/app/__init__.py` — 缺失

> 虽然 Python 3.3+ 支持隐式命名空间包，但在 `pytest` 测试发现等场景仍可能引发问题。

### 4.3 配置加载中的路径污染

**文件**: `config/loader.py` 第 16 行

```python
sys.path.insert(0, str(PROJECT_ROOT))
```

> 将项目根目录插入 `sys.path` 最前面可能导致不同模块间的命名冲突。建议仅在需要时临时添加，或使用相对导入。

### 4.4 缺少 `.dockerignore` 文件

> 项目根目录没有 `.dockerignore`。这会导致 Docker build 时发送大量不必要文件到 Docker daemon：
> - `node_modules/`（数万个文件）
> - `data/`（大数据文件）
> - `llama.cpp/`（大模型工具）
> - `.git/`（完整 git 历史）

### 4.5 前端 Zustand Store 使用 `Map` 类型

**文件**: `src/frontend/web/src/stores/chatStore.ts` 第 16 行

```typescript
// ❌ Map 在 JSON 序列化时会丢失所有数据
sessions: Map<string, ChatSession>;

// ✅ 推荐使用 Record
sessions: Record<string, ChatSession>;
```

> Zustand DevTools 使用 `JSON.parse/stringify` 进行序列化，`Map` 会被转为空对象 `{}`，导致调试时所有会话数据不可见。

---

## 五、轻微问题 (MINOR)

### 5.1 TODO 遗留项

| 文件 | 行号 | 说明 |
|------|------|------|
| `src/backend/python-legacy/services/ocr_quality_validator.py` | 538, 549 | 生产环境需要接入真实 LLM 服务 |
| `src/backend/server/src/modules/retrieval/src/index.ts` | 200 | 使用 Elasticsearch 实现关键词搜索 |

### 5.2 Python 依赖未安装

项目 `pyproject.toml` 中声明了以下依赖但在当前环境中未安装：

| 包名 | 用途 |
|------|------|
| `fastapi` | Web 框架 |
| `uvicorn` | ASGI 服务器 |
| `asyncpg` | PostgreSQL 异步驱动 |

> 这可能导致部分服务无法启动。需要注意这些是运行时依赖，建议确认部署环境已安装。

### 5.3 重复的无用变量

**文件**: `src/backend/server/src/index.ts` 第 56 行

```typescript
const pump = promisify(pipeline);  // 未使用，可删除
```

同时在 `PipelineService.ts` 第 12 行有相同的定义并被使用。

### 5.4 流式 LLM 响应处理方式

**文件**: `src/backend/server/src/index.ts` 第 761 行

```typescript
// 流式响应
reply.header('Content-Type', 'text/event-stream');
reply.send(response.body);  // Fastify 对流式响应需特殊处理
```

> 直接 `reply.send(response.body)` 在 Fastify 中可能无法正确处理流式响应，建议改用 `reply.raw` 写入。

---

## 六、统计摘要与修复建议

### 问题数量汇总

| 严重级别 | 数量 | 占比 |
|---------|------|------|
| 🔴 **Critical**（语法错误 + 安全漏洞） | 30+ | ~40% |
| 🟠 **Major**（代码质量） | 25+ | ~33% |
| 🟡 **Moderate**（架构配置） | 5+ | ~7% |
| 🟢 **Minor**（轻微问题） | 15+ | ~20% |

### 优先修复建议

#### P0（高优先级 — 安全与正确性）

1. **清除所有硬编码数据库密码**
   - 涉及 28+ 个文件
   - 统一通过环境变量或配置中心获取数据库凭证
   - 在所有工具脚本和遗留代码中统一替换

2. **修复裸 `except:` 异常处理**
   - 涉及约 20 处代码
   - 改为 `except Exception as e:` 并记录日志

3. **修复 `docker-compose.modern.yml` YAML 语法**
   - 使 Docker 编排生效

#### P1（中优先级 — 可维护性）

4. **清理 python-legacy/ 和 retrieval-service/ 的代码重复**
   - 提取公共代码到 `packages/shared/`

5. **统一数据库 Schema 单一真实来源**
   - 解决 `schema.sql` 与 `migrations/` 不一致问题

6. **修复 LLM 流式响应处理**
   - 改为使用 `reply.raw` 方式正确流式输出

#### P2（低优先级 — 代码整洁）

7. **清理 TypeScript 未使用的导入和变量**（`pump`、`PoolClient` 等）

8. **统一日志输出** — `console.log` 替换为 `logger` 服务

9. **前端 Store 使用 `Record` 替换 `Map`**

10. **删除无用文件**
    - 工作区中一些散落的文件如 `": print(f'  {r[0]}  {r[1]}')"`、`":', cols)` 等需要清理

---

*报告由 OpenCode CLI 自动生成于 2026-04-24*

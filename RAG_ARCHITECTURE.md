# RAG Dashboard — 技术架构与业务逻辑文档

> 生成时间：2026-05-14  
> 分支：`feature/wo-jiao-er-ha-milvus-topology`

---

## 目录

1. [系统定位](#1-系统定位)
2. [整体架构图](#2-整体架构图)
3. [服务层详解](#3-服务层详解)
4. [存储层](#4-存储层)
5. [AI 推理层](#5-ai-推理层)
6. [业务模块与功能](#6-业务模块与功能)
7. [RAG 查询流程](#7-rag-查询流程)
8. [自学习系统](#8-自学习系统)
9. [文档摄入流水线](#9-文档摄入流水线)
10. [Node 状态机编排](#10-node-状态机编排)
11. [API 路由总表](#11-api-路由总表)
12. [可观测性](#12-可观测性)
13. [配置体系](#13-配置体系)
14. [部署模式](#14-部署模式)

---

## 1. 系统定位

RAG Dashboard 是一套**企业级自主学习检索增强生成（RAG）系统**，核心能力：

- 用户提问 → AI Agent 自动从知识库检索 → 多模型推理 → 返回答案
- 系统持续从用户反馈和失败信号中学习，自动生成改进补丁并验证
- 多数据库联合检索（向量 + 关键词 + 图谱 + 结构化 SQL）
- 文档自动摄入：OCR → 分块 → 向量化 → 多库入库
- 实时运维监控：服务健康、QPS、延迟百分位、知识图谱拓扑

---

## 2. 整体架构图

```
┌─────────────────────────────────────────────────────────┐
│                     Browser / Client                     │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTP / WebSocket
                        ▼
┌─────────────────────────────────────────────────────────┐
│              React 18 + Vite  (Port 3000)                │
│  SearchPage │ AgentChat │ Library │ Learning │ Ops │ ... │
└──┬──────────────┬──────────────┬──────────────┬─────────┘
   │ /api/agent   │ /api/v1/*    │ /api/*       │ /ws
   │              │              │              │
   ▼              ▼              ▼              ▼
Node Orch.   Retrieval Svc   Go API GW    Go WS GW
:3001        :8002           :8080        :8081
(Fastify     (FastAPI        (Gin         (Gin +
 XState v5)   LangGraph)      反向代理)    gorilla/ws)
                │                │
                │                ▼
                │          Python Legacy
                │          :8000 (FastAPI)
                │          嵌入 / 文档 / 统计
                │
                ▼
┌──────────────────────────────────────────────────────────┐
│                       存储层                              │
│  PostgreSQL:5432  │  Qdrant:6333   │  ES:9200           │
│  Milvus:19530     │  Neo4j:7474    │  Redis:6379        │
│  MinIO:9000       │                                      │
└──────────────────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│                    AI 推理层                              │
│  HuggingFace TEI (GPU嵌入)  │  sentence-transformers    │
│  DeepSeek / OpenAI / 其他   │  LangGraph ReAct Agent    │
└──────────────────────────────────────────────────────────┘
```

### 前端路由分发规则（Vite Dev Proxy）

| 前缀 | 目标 | 说明 |
|------|------|------|
| `/api/agent` | Node Orchestrator :3001 | Agent 对话、会话管理 |
| `/api/v1/*` | Retrieval Service :8002 | 搜索、RAG、学习、工具 |
| `/api/*` `/health` `/metrics` | Go API Gateway :8080 | 其余 API 统一代理 |
| `/ws` | Go WS Gateway :8081 | 实时推送 |

Go Gateway 内部使用**最长前缀匹配**（`proxy.go → getRouteMapping()`），新增 API 前缀必须在此注册。

---

## 3. 服务层详解

### 3.1 Frontend — `src/frontend/web/`

| 技术 | 版本 | 用途 |
|------|------|------|
| React | 18.2 | UI 框架 |
| Vite | 5.0 | 构建工具 |
| React Router | 7.x | SPA 路由 |
| Zustand | 4.4 | 全局状态管理 |
| Recharts | 2.10 | 数据图表 |
| Mermaid | 11.x | 架构图渲染 |
| TypeScript | 5.3 | 类型安全 |
| `@rag/shared` | workspace | 与 Node 共享类型 |

### 3.2 Node Orchestrator — `src/backend/server/`

核心职责：Agent 会话编排、任务队列、WebSocket 事件转发、认证鉴权。

| 技术 | 版本 | 用途 |
|------|------|------|
| Fastify | 4.24 | HTTP 框架 |
| XState v5 | 5.x | 状态机（递归查询、Pipeline） |
| BullMQ | 4.x | Redis 任务队列 |
| LangChain (JS) | 0.2 | LLM 调用封装 |
| Zod | 3.x | Schema 校验 |
| ioredis | 5.x | Redis 客户端 |
| pg | 8.x | PostgreSQL 客户端 |
| neo4j-driver | 6.x | 图数据库客户端 |
| jose | 6.x | JWT 签发/验证 |
| Pino | 10.x | 结构化日志 |
| OpenTelemetry | 1.9 | 分布式追踪 |

**12 个功能模块：**

| 模块 | 职责 |
|------|------|
| `agent` | ReactAgent、ReAct 循环、工具调用、工厂模式 |
| `retrieval` | 向量/关键词/图搜索、查询分解、重排序 |
| `recursion` | XState 递归查询精炼状态机 |
| `ocr` | PDF 解析、OCR、文本提取、分块 |
| `pipeline` | 任务调度、串/并行组合、状态机 |
| `storage` | 缓存（Redis）、队列、存储（PG） |
| `expert` | 质量评估、边界检测 |
| `llm` | LLM 路由、嵌入、流式输出 |
| `auth` | Token 管理、RBAC、刷新逻辑 |
| `metrics` | Prometheus 计数器/Gauge、告警、延迟追踪 |
| `websocket` | 实时订阅、广播、连接管理 |
| `common` | Pipe 构建器、EventBus、类型系统 |

### 3.3 Go API Gateway — `src/backend/go-services/cmd/gateway/`

| 技术 | 版本 | 用途 |
|------|------|------|
| Go | 1.25 | 运行时 |
| Gin | 1.12 | HTTP 框架 |
| Prometheus client | 1.19 | 指标暴露 |
| OpenTelemetry | 1.43 | 分布式追踪 |
| quic-go | 0.59 | HTTP/3 支持 |

职责：最长前缀路由转发、指标聚合、健康检查端点。

### 3.4 Go WebSocket Gateway — `src/backend/go-services/cmd/websocket/`

| 技术 | 版本 | 用途 |
|------|------|------|
| gorilla/websocket | 1.5 | WS 连接管理 |
| Gin | 1.12 | HTTP 升级 |

职责：Node Orchestrator 通过 HTTP POST 推事件到此服务，由此服务广播给所有订阅的前端客户端。

### 3.5 Python Legacy API — `src/backend/python-legacy/`

| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.10 | 运行时 |
| FastAPI | 0.95+ | HTTP 框架 |
| Pydantic v2 | 2.x | 数据校验 |
| sentence-transformers | 2.2+ | 本地嵌入推理 |
| PyTorch | 2.0+ | 模型推理 |
| Transformers | 4.30+ | HuggingFace 模型加载 |
| psycopg2 | 2.9+ | PostgreSQL |
| qdrant-client | 1.3+ | Qdrant 向量库 |
| elasticsearch-py | 8.x | ES 客户端 |
| neo4j-py | 5.x | 图数据库 |

**拥有的 API 路由：**
`/api/v1/embedding`、`/api/v1/documents`、`/api/stats`、`/api/v1/stats`

### 3.6 Retrieval Service — `src/backend/retrieval-service/`

| 技术 | 版本 | 用途 |
|------|------|------|
| FastAPI | 0.95+ | HTTP 框架 |
| **LangGraph** | 0.2+ | Agent 图执行引擎 |
| LangChain Core | 0.3+ | LLM 调用 |
| langchain-openai | 0.2+ | OpenAI/DeepSeek 适配 |
| pymilvus | 2.4+ | Milvus 客户端 |
| APScheduler | 3.10 | 定时任务（学习循环） |
| OpenTelemetry | 1.41 | 追踪 |
| Prometheus client | 0.19 | 指标 |
| sympy | 1.12+ | 精确数学计算 |

**拥有的 API 路由：**
`/api/search`、`/api/v1/search`、`/api/v1/rag`、`/api/v1/agent`、`/api/v1/learning`、`/api/v1/executor`、`/api/v1/architecture`、`/api/v1/tools`、`/api/v1/sandbox`、`/api/v1/evaluate`、`/api/v1/rerank`

---

## 4. 存储层

| 数据库 | 版本/镜像 | 端口 | 核心用途 |
|--------|----------|------|---------|
| **PostgreSQL 16** + pgvector + zhparser | 自构建镜像 | 5432 | 文档注册表、摄入日志、学习状态、知识缺口、信号收集、向量备用 |
| **Qdrant** | v1.8.0 | 6333 | 主向量库，语义相似度搜索，生产首选 |
| **Elasticsearch** | 8.12 + IK 中文分词 | 9200 | BM25 关键词搜索，中文全文检索 |
| **Milvus** | v2.4.10 | 19530 | 备用向量库，可热切换（rows=7887） |
| **Neo4j** | latest | 7474/7687 | 知识图谱，概念关系，图遍历查询 |
| **Redis** | 7.2-alpine | 6379 | 缓存、会话、BullMQ 任务队列 |
| **MinIO** | 2023-03-20 | 9000 | 对象存储（原始文件、模型权重） |
| **etcd** | v3.5.5 | — | Milvus 元数据存储 |

### 四库联动检索策略

```
用户查询
   ↓
查询分析（意图分类 + 实体提取 + 子查询分解）
   ↓
并行检索：
  ├── Qdrant    → 语义向量召回（dense vectors）
  ├── ES        → BM25 关键词召回（中文IK分词）
  ├── Neo4j     → 概念图谱关联查询
  └── PostgreSQL → 结构化 SQL 查询 / 兜底全文
   ↓
结果融合 + 去重 + 分数归一化
   ↓
Reranker 精排（可选，BAAI/bge-reranker）
   ↓
Token 预算裁剪 → LLM 生成答案
```

---

## 5. AI 推理层

| 组件 | 说明 |
|------|------|
| **HuggingFace TEI** | Text Embeddings Inference，GPU 加速嵌入服务（`ghcr.io/huggingface/text-embeddings-inference:1.5`），生产首选 |
| **sentence-transformers (local)** | CPU 模式备用，设 `EMBEDDING_BACKEND=local` 启用 |
| **LangGraph ReAct Agent** | Retrieval Service 核心 Agent，图状态机驱动工具调用循环 |
| **LangChain** | Python + JS 双端 LLM 封装，支持 OpenAI / DeepSeek |
| **LLM Provider** | 通过 `.env` 配置，支持 DeepSeek、OpenAI、其他兼容 OpenAI 接口的模型 |
| **Reranker** | BAAI/bge-reranker（完整模式）/ BAAI/bge-reranker-base（2G 模式） |

### 嵌入模型选型

| 场景 | 模型 |
|------|------|
| 完整模式（RAM > 8GB） | `BAAI/bge-large-zh-v1.5` via TEI |
| 轻量模式（3–8GB） | `BAAI/bge-base-zh-v1.5` |
| 2G 模式（< 3GB） | `BAAI/bge-small-zh-v1.5` |

---

## 6. 业务模块与功能

### 6.1 页面功能总览

| 页面 | 路径 | 核心功能 |
|------|------|---------|
| **SearchPage** | `/search` | Agent 工具箱沙箱：独立调用每个检索原语（向量、关键词、混合、图谱、分类、PDF、价格、计算器、SQL 等） |
| **AgentChat** | `/agent` | RAG 问答界面：三栏布局（配置 / 对话 / 流程可视化），实时展示 Agent 执行链、工具调用、计算步骤 |
| **LibraryPage** | `/library` | 图书馆模式：极简提问界面，隐藏所有技术参数，自动使用最优默认值 |
| **LearningPage** | `/learning` | 自学习仪表盘：系统状态、待审批改进、学习趋势图（置信度、召回率、F1） |
| **OpsPage** | `/ops` | 运维面板：6 个服务健康状态、实时 QPS、延迟百分位、请求量 |
| **PipelinePage** | `/pipeline` | 数据流水线：一键上传文档 → OCR → 分块 → 嵌入 → 入库，实时进度监控 |
| **AgentManagePage** | `/agents` | Agent 注册表：浏览 `.agent/agents/*.md` 定义文件，展示 frontmatter 和 markdown body |
| **AgentRuntimePage** | `/runtime` | Agent 运行时透明度：实时展示 channel/state/工具调用栈，历史保存到 localStorage |
| **SystemPage** | `/system` | 系统配置：架构元数据（6 数据库实时状态）、配置树、KB 资产、版本信息 |

### 6.2 前端组件架构

```
src/frontend/web/src/
├── pages/              # 9 个页面
├── components/
│   ├── agent/          # AgentFlowPanel（执行流可视化）、GuideHistoryPanel（历史回放）
│   ├── learning/       # DashboardPanel、ImprovementHistoryPanel、ProblemsPanel、
│   │                   # ReviewsPanel、AdvancedDataDrawer、SystemDiagnosticsDrawer
│   └── common/         # FeedbackModal（反馈收集）、PageHeader、SystemAssistant
├── locales/            # 国际化：services.ts（服务标签翻译）、stores.ts（状态翻译）
└── stores/             # Zustand 状态管理
```

**关键 i18n 规则：** 后端/DB 使用英文 key；前端通过 `src/locales/services.ts`（SVC_ICONS, SERVICE_LABELS, translateStatus, statusClass）翻译。组件必须从 locale 层导入，禁止内联硬编码中文标签。

---

## 7. RAG 查询流程

### 7.1 LangGraph Hybrid Agent 执行图

```
query_analysis_node
  │ 意图分类、实体提取、子查询分解
  ▼
forced_rag_node
  │ 向量 + 关键词 + 图谱并行检索
  ▼
retrieval_filter_node
  │ 去重、分数阈值过滤、Token 预算裁剪
  ▼
evaluator_node ──── 质量不达标 ────►  react_loop_node
  │ 质量达标                              │
  ▼                              ┌────────┴────────┐
synthesize_node             tool_call_cache    tool_node
  │ 生成最终答案              （防重复调用）    （执行工具）
  ▼
END
```

**配置参数：**
- `maxDepth`: 3 轮递归
- `minConfidence`: 0.85
- `maxIterations`: 10
- `timeout`: 30,000ms

### 7.2 RAG Pipeline 三阶段（LangGraph 替代 XState）

```
retrieve_node
  │ 调用 UnifiedRetrievalPipeline
  │ 参数化 top_k（vector_top_k / keyword_top_k / graph_top_k）
  ▼
rerank_node（可选）
  │ Reranker 服务精排
  ▼
generate_node
  │ LLM 生成答案
  ▼
返回给用户
```

### 7.3 工具能力清单

Agent 可调用的工具分 4 类：

| 类别 | 工具 |
|------|------|
| **检索** | vector_search、keyword_search、hybrid_search、concept_search、graph_search、topology_search、category_search、text_search、pdf_search |
| **数据** | price_query、sql_query、structured_data_lookup |
| **计算** | calculator（sympy 精确计算）、python_eval |
| **图谱** | graph_traversal、relationship_query |

---

## 8. 自学习系统

系统通过 3 层架构实现持续改进：

```
Layer 1: 信号收集（SignalCollector）
Layer 2: 知识缺口分析（LearningState）
Layer 3: 补丁执行与验证（Executor）
```

### 8.1 Layer 1 — 信号收集

**5 类信号源：**

| 信号类型 | 触发条件 | 关键字段 |
|---------|---------|---------|
| `FeedbackSignal` | 用户评分（1–5星）、标签、文字反馈 | rating, tags, text |
| `FailureSignal` | 错误日志（状态码、延迟、error_code） | status, latency_ms, error_code, route_id |
| `RepeatQuestionSignal` | 时间窗口内重复查询 | query, window_size, count |
| `ContractViolationSignal` | 数据契约违反 | contract_id, field, expected, actual |
| `TopologyAnomalySignal` | 图谱边超过 7 天未更新或流量突刺 | edge_id, age_days, traffic_delta |

**过滤规则：** 慢但成功的请求（`quality='good'` / `outcome_code='ANSWERED_OK'`）不触发失败信号，避免 R2_path_default 产生幻象连续失败。

### 8.2 Layer 2 — 知识缺口管理

**缺口生命周期：**

```
open → in_progress → observing → resolved
                  └──────────────→ blocked
```

**缺口分类：**

| 类别 | 说明 |
|------|------|
| `tool_failure` | 工具调用失败 |
| `low_quality` | 答案质量不达标 |
| `diversity_issue` | 检索结果多样性不足 |
| `contract_violation` | 数据契约违反 |
| `topo_anomaly` | 图谱拓扑异常 |
| `prompt_issue` | Prompt 设计问题 |
| `routing_error` | 路由错误 |

**缺口属性：** scope（user / agent / project / global）、observation_window（默认 7 天）

### 8.3 Layer 3 — 补丁执行

**补丁类型：**

| 类型 | 说明 |
|------|------|
| `prompt` | 修改 Prompt 模板 |
| `weight` | 调整检索权重 |
| `tool_order` | 重排工具调用顺序 |
| `path` | 调整路由路径 |
| `feature` | 启用/禁用功能 |

**补丁生命周期：**

```
pending → applying → applied → verifying → verified
                                         └──────────→ reverted / failed
```

**执行流程：**
1. 应用补丁
2. 运行 `tests/test_agent_16.py`（16 题基准测试）
3. 对比指标（置信度、召回率、F1）
4. 审计 `answer_preview` 排除拒绝回答（含"无法回答"等关键词的题目视为 FAIL）
5. 更新数据库状态

---

## 9. 文档摄入流水线

### 9.1 摄入状态机

```
queued → extracting → chunking → embedding → indexing → done
                                                       └──→ failed（可重试）
```

**幂等性保证：** PostgreSQL `ingest_write_log` 以 PK 防止重启导致的重复写入。

### 9.2 提取器类型

| 提取器 | 适用场景 |
|--------|---------|
| `pymupdf` | 文本型 PDF |
| `paddleocr` | 扫描版 PDF / 图片 |
| `pdfplumber` | 表格型 PDF |
| `csv` / `xlsx` | 结构化数据 |
| `mixed` | 混合内容 |

### 9.3 数据契约（IngestDocument）

```python
IngestDocument {
  doc_id: str
  file_name: str
  extractor: str
  pages: List[IngestPage {
    page: int
    blocks: List[IngestBlock {
      block_id: str
      type: str       # text | table | figure | formula | caption
      text: str       # 嵌入友好的文本表示
      bbox: Optional[Tuple]
      confidence: Optional[float]
      table: Optional[IngestTable]
      figure: Optional[IngestFigure]
      metadata: dict
    }]
  }]
  blindspots: List[IngestBlindspot]   # 图表、扫描盲区、OCR 缺口
  metadata: dict
}
```

### 9.4 写入目标

| 数据库 | 写入内容 |
|--------|---------|
| PostgreSQL | 文档注册表、分块文本、摄入日志 |
| Qdrant | 分块向量嵌入（ingest_collection） |
| Elasticsearch | 分块文本关键词索引 |
| Neo4j | 概念关系、知识图谱节点 |

### 9.5 前端接口

- `POST /api/v1/ingest/upload` — 异步创建摄入任务
- `GET /api/v1/ingest/jobs` — 查询任务进度
- WebSocket channel `ingest-jobs` — 实时状态推送

---

## 10. Node 状态机编排

### 递归查询精炼状态机（XState v5）

**Context：**
```typescript
RecursionContext {
  session: RecursionSession
  query: string
  currentRound: number
  eventBus?: EventBus
}
```

**事件类型：**
```typescript
| { type: 'START'; query: string }
| { type: 'DECOMPOSE' }
| { type: 'RETRIEVE' }
| { type: 'EVALUATE' }
| { type: 'JUDGE' }
| { type: 'GENERATE' }
| { type: 'COMPLETE' }
| { type: 'FAILED'; error: string }
| { type: 'HUMAN_REVIEW'; approved: boolean }
```

**Actors（fromPromise）：**
- `decomposeQuery` — 子查询分解
- `retrieveChunks` — 多源检索
- `evaluateRound` — 质量指标评估（完整性、一致性、置信度、覆盖率）
- `expertJudgment` — 决定继续迭代或终止

**XState v5 强制规范：**
- 使用 `createActor()` 而非 `interpret()`
- Guard 必须写成函数 `guard: ({ context }) => ...`
- 每个 `invoke` 必须有 `onError` 路径
- 生命周期结束后必须 `stop()` spawned actors

---

## 11. API 路由总表

### Retrieval Service (:8002)

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/v1/search` | 混合检索 |
| POST | `/api/v1/rag` | 完整 RAG 流程 |
| POST | `/api/v1/agent` | Agent 执行（阻塞） |
| POST | `/api/v1/agent/stream` | Agent 执行（SSE 流式） |
| POST | `/api/v1/rerank` | 重排序 |
| POST | `/api/v1/evaluate` | 响应质量评估 |
| POST | `/api/v1/decompose` | 查询分解 |
| POST | `/api/v1/feedback` | 提交反馈信号 |
| GET | `/api/v1/tools` | 列出所有工具 |
| GET | `/api/v1/tools/{name}` | 工具元数据 |
| POST | `/api/v1/tools/{name}/invoke` | 执行工具 |
| GET | `/api/v1/learning/runs` | 历史学习迭代 |
| GET | `/api/v1/learning/gaps` | 知识缺口列表 |
| POST | `/api/v1/learning/gaps/triage` | 缺口分类 |
| POST | `/api/v1/learning/gaps/{key}/retest` | 自适应测试 |
| GET | `/api/v1/learning/summary` | 学习仪表盘摘要 |
| GET | `/api/v1/architecture/live` | 实时架构元数据（数据库健康度） |

### Node Orchestrator (:3001)

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/agent` | Agent 对话入口 |
| GET/POST | `/api/sessions` | 会话管理 |
| GET | `/api/activity` | 活动日志 |
| POST | `/api/heartbeat` | 心跳检测 |
| POST | `/api/auth/login` | 登录 |
| POST | `/api/auth/refresh` | Token 刷新 |
| GET/POST | `/api/pipeline` | Pipeline 任务 |
| GET | `/api/cache` | 缓存状态 |
| GET | `/api/queue` | 队列状态 |
| GET | `/api/system` | 系统信息 |

### Python Legacy (:8000)

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/v1/embedding` | 文本嵌入 |
| GET/POST | `/api/v1/documents` | 文档管理 |
| GET | `/api/stats` | 系统统计 |
| GET | `/api/v1/stats` | 详细统计 |

---

## 12. 可观测性

| 工具 | 覆盖范围 | 说明 |
|------|---------|------|
| **OpenTelemetry** | Python + Node + Go 全栈 | 分布式追踪，OTLP HTTP 导出 |
| **Prometheus** | Go Gateway + Retrieval Service | 指标暴露，`/metrics` 端点 |
| **Pino** | Node Orchestrator | 结构化 JSON 日志 |
| **Langfuse**（可选） | LLM 调用链 | `infrastructure/docker-compose.langfuse.yml` |

### 审计规则

所有行为变更操作（切换、迁移、重启、删除、降级）必须在以下审计面留下带时间戳的记录：
- 结构化日志（Pino / Python logging）
- 事件状态表（PostgreSQL）
- 改进事件台账（learning_events 表）

---

## 13. 配置体系

### 优先级链（低 → 高）

```
YAML 默认值（config/config.yaml）
    ↓
.env 文件
    ↓
环境变量（RAG__SECTION__KEY 双下划线嵌套）
    ↓
CLI 参数
    ↓
运行时动态输入
```

### 各端入口

| 服务 | 配置入口 |
|------|---------|
| Python（所有服务） | `config/loader.py` → `get_config()` / `reload_config()` |
| Node Orchestrator | 域内 config 模块；`src/backend/server/src/index.ts` 有遗留 `.env` 解析（勿复制此模式） |
| Go Gateway | `gateway.LoadConfig(os.Args[1:])` |

### 关键环境变量

| 变量 | 说明 |
|------|------|
| `SECRET_KEY` | 应用密钥（32 字节 hex） |
| `JWT_SECRET` | JWT 签名密钥 |
| `POSTGRES_PASSWORD` | PG 密码 |
| `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` | LLM API 密钥 |
| `EMBEDDING_BACKEND` | `local`（CPU）或 `tei`（GPU 服务） |
| `EMBEDDING_MODEL_NAME` | 嵌入模型名称 |
| `RERANKER_MODEL_NAME` | 重排模型名称 |

---

## 14. 部署模式

| 模式 | RAM 条件 | 启动命令 | 排除服务 |
|------|---------|---------|---------|
| **2G 模式** | < 3 GB | `docker compose -f docker-compose.yml -f docker-compose.2g.yml up -d` | OCR、ES、TEI；使用小模型 |
| **轻量模式** | 3–8 GB | `docker compose up -d` | TEI（用本地推理） |
| **完整模式** | > 8 GB | `docker compose --profile full up -d` | 无（全服务包含 ES + TEI GPU） |

### 健康检查端点

```bash
curl http://localhost:8000/health   # Python Legacy
curl http://localhost:8002/health   # Retrieval Service
curl http://localhost:3001/health   # Node Orchestrator
curl http://localhost:8080/health   # Go Gateway
curl http://localhost:80            # Frontend (nginx)
```

### 运维常用命令

```bash
docker compose logs -f                          # 实时日志
docker compose restart <service>                # 重启单个服务
docker stats --no-stream                        # 内存用量快照
git pull && docker compose up -d --build        # 更新到最新代码
docker compose down -v                          # 停止并清空数据（破坏性！）
```

---

*本文档由 GitHub Copilot CLI 根据代码库自动生成，引用路径均为真实文件。*

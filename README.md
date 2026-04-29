# RAG26 — 深圳建设工程造价 RAG 系统

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5.x-3178C6?logo=typescript&logoColor=white)
![Go](https://img.shields.io/badge/Go-1.21+-00ADD8?logo=go&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-green)
![Milvus](https://img.shields.io/badge/Milvus-2.4+-00A1EA?logo=milvus&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow)

**面向深圳市建设工程计价标准的企业级 RAG 系统**  
向量后端可热切换（Milvus ↔ pgvector）· LangGraph 编排 · 混合召回 + Rerank · PaddleOCR GPU

[架构设计](#-核心架构) • [向量拓扑](#-向量存储拓扑switching) • [检索流程](#-检索流程) • [快速开始](#-快速开始) • [配置说明](#-配置说明)

</div>

---

## 📖 项目简介

RAG26 是一套**专为建设工程造价场景**定制的检索增强生成（RAG）系统。核心目标是从深圳市建设工程计价标准文件（PDF）中准确检索费率、公式、附录数据，并通过 LLM 生成带计算过程的结构化回答。

系统的技术核心是**可插拔的向量存储拓扑**：运行时通过配置在 **Milvus**（分布式高性能）和 **pgvector**（嵌入式零依赖）之间无缝切换，切换对上层 RAG pipeline 完全透明。

---

## 🏗️ 核心架构

```
┌──────────────────────────────────────────────────────────────────┐
│                        客户端 / 前端                              │
│              src/frontend/web  (TypeScript + React)              │
└────────────────────────┬─────────────────────────────────────────┘
                         │ HTTP / WebSocket
┌────────────────────────▼─────────────────────────────────────────┐
│                     Go 网关层                                     │
│   src/backend/go-services/  (gateway + websocket)                │
│   · 路由转发  · 连接管理  · 会话保活                              │
└────────────┬──────────────────────────┬───────────────────────────┘
             │                          │
┌────────────▼──────────┐  ┌────────────▼──────────────────────────┐
│  TypeScript 编排服务   │  │       Python 检索服务                  │
│  src/backend/server/  │  │  src/backend/retrieval-service/       │
│  · OCR 调度管理        │  │  · LangGraph RAG pipeline             │
│  · 任务队列            │  │  · LangGraph Agent（tools.py）        │
│  · 会话持久化          │  │  · 混合召回 + Rerank + RRF 融合       │
│  · LLM 代理路由        │  │  · 向量存储适配器（可切换拓扑）        │
└───────────────────────┘  └────────────┬──────────────────────────┘
                                        │
             ┌──────────────────────────▼──────────────────────┐
             │               存储层                             │
             │  PostgreSQL + pgvector  ←→  Milvus              │
             │  (主数据库 / fallback)      (可选高性能后端)      │
             │                                                  │
             │  Qdrant  ──  session_context 短期向量缓存        │
             │  Redis   ──  查询结果缓存                        │
             └─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        OCR 流水线                                │
│  ocr_web_service/   ·  ocr_tools/   ·  src/backend/ocr-service/ │
│  PaddleOCR PP-OCRv4 + PPStructure  (NVIDIA RTX 4070 / GPU)      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔀 向量存储拓扑 Switching

**这是本系统的核心技术设计。** 向量检索后端通过单一配置字段驱动，运行时自动路由：

```yaml
# config/config.yaml
vector_store:
  type: milvus          # 可选: milvus | qdrant | pgvector | chroma | memory
  uri: http://localhost:19530
  collection_name: document_chunks
  vector_size: 1024
  metric_type: COSINE
```

### 切换逻辑

```
vector_search() / hybrid_search()
        │
        ├─ type == "milvus"
        │       └─ MilvusVectorStoreAdapter.search()
        │               └─ 不可用 / 空结果 → 自动 fallback ↓
        │
        └─ pgvector (PostgreSQL)
                └─ SELECT ... embedding <=> $1::vector ... FROM text_chunks
```

### 适配器接口（Ports & Adapters 模式）

```python
# domain/ports.py — 上层 pipeline 只依赖这个接口
class VectorStorePort(Protocol):
    async def search(query_vector, top_k, score_threshold) -> List[Tuple[Document, float]]: ...
    async def upsert(documents, vectors) -> bool: ...
    async def delete(doc_ids) -> bool: ...
    def is_available(self) -> bool: ...
```

两个具体实现：

| 适配器 | 后端 | 适用场景 |
|--------|------|---------|
| `MilvusVectorStoreAdapter` | Milvus 2.4+ | 生产环境、大规模向量集合、高并发 |
| `QdrantVectorStoreAdapter` | Qdrant | session_context 短期缓存 |
| pgvector（内联 SQL） | PostgreSQL | 零额外依赖、开发/轻量部署 |

### Fallback 保障

```python
if not adapter.is_available():
    logger.warning("milvus adapter unavailable, falling back to pgvector")
    return []   # vector_search() 继续走 pgvector 路径
```

降级对调用方完全透明，`source_db` 字段会标记实际来源（`milvus` / `pgvector`）。

---

## 🔍 检索流程

RAG pipeline 由 **LangGraph** 编排，三节点线性图：

```
retrieve ──► rerank ──► generate ──► END
```

### 1. retrieve — 混合召回

```
hybrid_search(query)
    ├── 向量召回  →  Milvus / pgvector cosine similarity (top_k=30)
    ├── 全文召回  →  PostgreSQL ts_rank / plainto_tsquery (top_k=20)
    ├── 结构化表查询  →  fee_rates / 附录标准表 直接 SQL
    └── RRF 融合  →  Reciprocal Rank Fusion 合并去重
```

### 2. rerank — 精排

```python
reranker.rerank(query, [chunk.content for chunk in candidates])
# 按 rerank_score 降序，保留 top_10
```

支持本地 cross-encoder 模型（sentence-transformers），不可用时降级为 `vector×0.6 + keyword×0.4` 线性融合。

### 3. generate — 生成

- LLM：DeepSeek Chat（可通过 `LLM_BASE_URL` / `LLM_MODEL` 换为任意 OpenAI 兼容接口）
- System prompt 内嵌深圳市建设工程计价费率标准（2025版）核心公式
- 后处理：LaTeX → 纯文本（`_strip_latex`）+ 自动注入 Python 验证代码块

---

## 🤖 LangGraph Agent

`app/agent/graph.py` 中定义了完整的 ReAct Agent，通过 `tools.py` 暴露以下工具：

| 工具 | 作用 |
|------|------|
| `vector_search` | 向量语义检索，优先 Milvus，fallback pgvector |
| `hybrid_search` | 向量 + 全文 + 结构化表三路混合召回 |
| `query_fee_rates` | 直查 `fee_rates` 结构化费率表 |
| `query_appendix_standards` | 查附录标准表 |
| `sandbox_execute` | 沙箱执行 Python 验证代码，返回计算结果 |

Agent 的 `query_analyzer.py` 会对查询进行意图分类，决定走 RAG pipeline 还是直接结构化查询。

---

## 🔎 OCR 流水线

三层结构，共同完成 PDF → 可检索文本 的转换：

| 层 | 路径 | 作用 |
|----|------|------|
| OCR 核心引擎 | `src/backend/ocr-service/` | PaddleOCR PP-OCRv4 + PPStructure，Docker GPU 部署，端口 8001 |
| Web UI 服务 | `ocr_web_service/` | FastAPI 封装，拖拽上传，三档处理策略（同步/异步/分块），端口 8002 |
| 批量扫描工具 | `ocr_tools/` | 断点续扫，路由统计（native/ocr/hybrid），RTX 4070 实测性能参考 |

页级路由策略：`native`（原生文字层）→ `hybrid`（图文混合）→ `ocr`（纯扫描图）

---

## 📁 项目结构

```
RAG26/
├── src/
│   ├── backend/
│   │   ├── retrieval-service/          # Python 检索服务（核心）
│   │   │   ├── app/
│   │   │   │   ├── agent/              # LangGraph Agent
│   │   │   │   │   ├── graph.py        # ReAct Agent 图定义
│   │   │   │   │   ├── tools.py        # 检索工具集（含 Milvus 路由）
│   │   │   │   │   ├── query_analyzer.py
│   │   │   │   │   └── state.py
│   │   │   │   ├── rag_pipeline.py     # LangGraph RAG pipeline
│   │   │   │   ├── api.py              # FastAPI 路由
│   │   │   │   └── pipeline.py
│   │   │   ├── domain/
│   │   │   │   ├── models.py           # 领域模型
│   │   │   │   └── ports.py            # VectorStorePort / RerankModelPort 等接口
│   │   │   ├── infrastructure/
│   │   │   │   ├── adapters/unified/
│   │   │   │   │   └── unified_store.py  # PG 主库 + Qdrant session_context
│   │   │   │   ├── vector_store.py       # Milvus / Qdrant 适配器 + 工厂函数
│   │   │   │   ├── embedding_service.py
│   │   │   │   ├── reranker_service.py
│   │   │   │   └── cache.py
│   │   │   ├── config/
│   │   │   │   ├── settings.py         # VectorStoreConfig（type 字段驱动切换）
│   │   │   │   └── loader.py
│   │   │   └── tests/                  # Milvus / pgvector fallback 单元测试
│   │   ├── go-services/                # Go 网关 + WebSocket 服务
│   │   │   ├── cmd/
│   │   │   ├── internal/
│   │   │   ├── Dockerfile.gateway
│   │   │   └── Dockerfile.websocket
│   │   ├── server/                     # TypeScript 编排服务
│   │   │   └── src/
│   │   │       ├── services/           # OCRPipelineManager, RetrievalService, LLMService ...
│   │   │       ├── modules/
│   │   │       └── tools/
│   │   ├── langgraph/                  # LangGraph 独立实验模块
│   │   ├── ocr-service/                # PaddleOCR GPU 核心服务
│   │   └── python-legacy/             # 历史遗留代码（仅参考）
│   ├── frontend/web/                   # React 前端
│   ├── database/                       # DB schema / migrations
│   └── generated/                      # 代码生成产物
├── ocr_tools/                          # PDF 批量扫描工具
├── ocr_web_service/                    # OCR Web UI 封装
├── config/                             # 全局配置
│   ├── config.yaml
│   ├── settings.py
│   └── .env.example
├── infrastructure/                     # Docker Compose 基础设施
│   ├── docker-compose.yml              # 核心中间件（PG, Redis, Qdrant）
│   ├── docker-compose.langfuse.yml     # LLM 可观测性
│   └── docker/
├── sql/                                # 数据库初始化脚本
├── packages/shared/                    # TypeScript 共享类型
├── tests/                              # 集成测试
├── docker-compose.yml                  # 顶层一键启动
├── pyproject.toml
└── requirements.txt
```

---

## 🚀 快速开始

### 前置要求

- Docker 20.10+ / Docker Compose
- Python 3.10+
- Node.js 18+（TypeScript 服务）
- Go 1.21+（网关服务，可选）
- NVIDIA GPU + CUDA 12.x（OCR 加速，可选）

### 1. 启动基础设施

```bash
# 启动 PostgreSQL + pgvector、Redis、Qdrant
cd infrastructure
docker compose up -d

# 初始化数据库
psql -h localhost -U rag_user -d rag_db -f ../sql/init/01_init_database.sql
```

### 2. 启动检索服务（Python）

```bash
cd src/backend/retrieval-service
pip install -r requirements.txt

# 默认使用 pgvector（零额外依赖）
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. 切换到 Milvus（可选）

```bash
# 启动 Milvus
docker run -d --name milvus-standalone \
  -p 19530:19530 -p 9091:9091 \
  milvusdb/milvus:v2.4.0 milvus run standalone

# 修改配置
# config/config.yaml → vector_store.type: milvus
# 或设置环境变量
export VECTOR_STORE_TYPE=milvus
export VECTOR_STORE_URI=http://localhost:19530
```

### 4. 启动 OCR 服务

```bash
# 构建 GPU 镜像（首次）
cd src/backend/ocr-service
docker build -t ocr-service:gpu .

# 启动
docker run -d --gpus all -p 8001:8001 --name ocr-gpu ocr-service:gpu

# Web UI（可选）
cd ocr_web_service
python3 -m uvicorn ocr_api_service:app --host 0.0.0.0 --port 8002
```

### 5. 验证

```bash
# 健康检查
curl http://localhost:8000/health

# RAG 查询
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "深圳建筑工程企业管理费费率是多少？", "top_k": 10}'
```

---

## ⚙️ 配置说明

### 向量存储（核心配置）

```yaml
# config/config.yaml
vector_store:
  type: milvus          # milvus | pgvector | qdrant | chroma | memory
  # Milvus
  uri: http://localhost:19530
  database: default
  # pgvector fallback（始终可用）
  # 使用 PostgreSQL 连接配置
  collection_name: document_chunks
  vector_size: 1024     # bge-m3 / bge-large = 1024
  metric_type: COSINE
```

### 环境变量

```bash
# LLM（OpenAI 兼容接口）
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.deepseek.com   # 可换 OpenAI / 本地 vLLM
LLM_MODEL=deepseek-chat

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=rag_db
POSTGRES_USER=rag_user
POSTGRES_PASSWORD=rag_password

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Milvus（可选）
VECTOR_STORE_TYPE=milvus
VECTOR_STORE_URI=http://localhost:19530

# Qdrant（session_context）
QDRANT_HOST=localhost
QDRANT_PORT=6333
```

完整示例见 [`config/.env.example`](config/.env.example)

---

## 🧪 测试

```bash
cd src/backend/retrieval-service

# 全量测试（含 Milvus/pgvector 切换单元测试）
pytest tests/ -v

# 仅向量后端切换测试
pytest tests/test_vector_store.py tests/test_vector_search_backend.py tests/test_hybrid_search_backend.py -v
```

---

## 📊 技术栈一览

| 层 | 技术 |
|----|------|
| RAG 编排 | LangGraph 0.2+ |
| 向量检索（主） | Milvus 2.4 / pymilvus |
| 向量检索（fallback） | PostgreSQL + pgvector |
| 全文检索 | PostgreSQL ts_rank（中文 simple 分词） |
| Session 向量缓存 | Qdrant |
| Reranker | sentence-transformers cross-encoder |
| Embedding | BGE-M3 / BGE-Large（1024维）|
| LLM | DeepSeek Chat（可换任意 OpenAI 兼容接口）|
| OCR | PaddleOCR PP-OCRv4 + PPStructure |
| 网关层 | Go（Fastify 风格路由 + WebSocket）|
| 编排服务 | TypeScript / Node.js |
| 前端 | React + TypeScript |
| 缓存 | Redis |
| 可观测性 | Langfuse（`infrastructure/docker-compose.langfuse.yml`）|

---

## 🤝 贡献指南

1. Fork 项目，创建特性分支：`git checkout -b feature/your-feature`
2. 遵循代码规范：Python 用 Black + Ruff，TypeScript 用 ESLint
3. 新增功能请附带测试，向量后端切换逻辑尤其需要覆盖 fallback 路径
4. 提交 PR，描述清楚技术方案

---

## 📄 许可证

MIT License

---

<div align="center">

Made with ❤️ for 深圳市建设工程造价

</div>

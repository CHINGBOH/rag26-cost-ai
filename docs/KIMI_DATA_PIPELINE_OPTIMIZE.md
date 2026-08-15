# Embedding 延迟高问题分析与优化提问（给 Copilot）

## 1. 问题概述

RAG Dashboard 的 Embedding 延迟在文档索引和查询检索时都非常高。经代码审查，发现了 **10+ 个明确的性能瓶颈**，从 CPU 阻塞、事件循环劫持到数据库误操作都有涉及。

**环境信息：**
- 模型：`BAAI/bge-m3` (1024维)
- 设备：`cpu`（`config.yaml` 硬编码）
- 后端：混合使用 `sentence-transformers` 本地推理 + TEI（Text Embeddings Inference）配置但未部署
- 架构：FastAPI (Python legacy `:8000`) + Retrieval Service (`:8002`) + Go Gateway (`:8080`)

---

## 2. 根因清单（按严重性排序）

### 🔴 P0 - 事件循环阻塞（Async Blocking）

**问题：** `sentence_transformers.SentenceTransformer.encode()` 是 CPU-bound 同步调用，直接在 FastAPI 的 `async def` 端点里调用，会阻塞整个事件循环，导致所有并发请求排队。

**涉及代码：**
- `src/backend/python-legacy/services/model_caller.py:215` - `model.encode()` 在 `async def _embed_local()` 中同步执行
- `src/backend/python-legacy/retrieval/vector_store.py:344` - `self.model.encode()` 无 `run_in_executor`
- `src/backend/retrieval-service/infrastructure/adapters/unified/unified_store.py:367` - `embedding_service.encode_query()` 在检索流程中同步调用
- `src/backend/python-legacy/infrastructure/adapters/ai_models.py:69` - `encode()` 是同步方法，被异步上下文直接调用

**问题细节：**
```python
# model_caller.py - 异步方法里直接跑 CPU 密集型 encode
async def _embed_local(self, texts, ...):
    model = self.current_model  # SentenceTransformer
    embeddings = model.encode(texts, ...)  # <-- 阻塞事件循环！
```

**期望优化：**
- 是否应该用 `asyncio.get_event_loop().run_in_executor(ThreadPoolExecutor, model.encode, ...)`？
- 或者使用 `torch.set_num_threads()` + 专用进程池？
- FastAPI 的 `BackgroundTasks` 是否适合大批量 indexing？

---

### 🔴 P0 - Qdrant 每次 upsert 都 recreate_collection（数据毁灭级 bug）

**问题：** `services/embedding_service.py:280` 的 `_store_to_qdrant()` 每次插入单个 chunk 都会调用 `recreate_collection()`，这会把整个集合删掉重建，导致：
1. 所有历史向量丢失
2. 每次插入延迟暴增（重建索引 + 重新写入）
3. 并发时互相覆盖数据

**代码位置：**
```python
# src/backend/python-legacy/services/embedding_service.py:280
self.qdrant_client.recreate_collection(
    collection_name=collection_name,
    vectors_config=VectorParams(size=..., distance=Distance.COSINE)
)
```

**期望优化：**
- 改为启动时一次性 `create_collection`（带 `exists_ok` 或先 `get_collections` 检查）
- `recreate_collection` 只在显式 reset 接口中使用

---

### 🔴 P0 - TEI 服务配置为启用但实际未部署

**问题：**
- `config/config.yaml:47` TEI `enabled: true`，`url: http://localhost:8003`
- `infrastructure/docker-compose.yml` 里 **完全没有 TEI 服务定义**
- `services/embedding_service.py:38` 环境变量 `EMBEDDING_BACKEND=tei` 默认走 TEI，但 TEI 不存在时会 fallback 到本地模型
- 问题是：如果 TEI 未启动，`httpx.AsyncClient` 30秒超时后才 fallback，每个请求白白等 30s

**期望优化：**
- docker-compose 里添加 TEI 容器（`ghcr.io/huggingface/text-embeddings-inference`），带 GPU/CPU 自适应
- 或者启动时做健康检查，TEI 不可用时直接切 local，不要等请求时才超时

---

### 🟠 P1 - Postgres 连接池误用

**问题：** `services/embedding_service.py:361` 在 `async with self.postgres_pool.acquire()` 上下文中显式调用了 `await conn.close()`。

**代码：**
```python
async with self.postgres_pool.acquire() as conn:
    await conn.execute(...)
    await conn.close()  # <-- 错误！pool 的 connection 不应该手动 close
```

**后果：** `asyncpg` 的连接池会被这个 `close()` 搞乱，可能导致连接泄漏或池耗尽，后续 DB 操作排队等待。

**期望优化：**
- 删除 `await conn.close()`，让 `async with` 自动释放连接
- 或者确认当前 asyncpg 版本下 `conn.close()` 的行为是否正确

---

### 🟠 P1 - Redis 同步客户端混在异步代码中

**问题：** `services/embedding_service.py:73` 使用 `redis.Redis()`（同步阻塞客户端），在 `async def _cache_embedding()` 中直接调用 `self.redis_client.setex()`。

**后果：** Redis 操作虽然快，但在高并发下同步 IO 会累积阻塞事件循环。

**期望优化：**
- 替换为 `redis.asyncio.Redis`（aioredis 兼容接口）
- 或者将 Redis 缓存操作也丢进线程池

---

### 🟠 P1 - 无 Query Embedding 缓存

**问题：** 同一个查询在每次检索时都重新做 embedding。检索 pipeline 里：
- `multi_stage_retriever.py:631` - `query_embedding = self.embed(query)` 每次调用
- `unified_store.py:367` - `embedding_service.encode_query(query.text)` 每次调用

**期望优化：**
- 增加查询向量缓存（Redis / LRU 内存缓存），相同查询直接复用
- 是否应该在 `EmbeddingService` 里加 `@lru_cache` 或 Redis 缓存层？

---

### 🟡 P2 - CPU 线程未调优

**问题：** 没有任何地方设置 `torch.set_num_threads()`。在 CPU 模式下，PyTorch 默认可能只用一个核心，或者滥用超线程。

**涉及代码：**
- `ai_models.py`, `vector_store.py`, `embedding_service.py` 均加载 `SentenceTransformer` 到 `cpu`，但无 `torch.set_num_threads()`

**期望优化：**
- 是否应该根据 CPU 核心数设置 `torch.set_num_threads(os.cpu_count() // 2)` 或读取环境变量 `OMP_NUM_THREADS`？
- 在 Docker/container 环境里如何正确检测可用 CPU？

---

### 🟡 P2 - 模型在导入/初始化时同步加载，阻塞启动

**问题：**
- `EmbeddingService.__init__()` 里直接调用 `_load_model()`
- `VectorStorePipeline.__init__()` 同步创建 `EmbeddingService()`
- `DocumentProcessor.__init__()` 同步调用 `get_embedding_service()`
- `RetrievalService` lifespan 里初始化 `UnifiedStore()`，其内部可能再次加载模型

**后果：** FastAPI 启动时就被模型加载卡住，首屏响应延迟极高；uwicorn worker 超时重启。

**期望优化：**
- 是否可以懒加载（lazy load）？第一次调用 `encode()` 时才加载模型
- 或者使用 `asyncio.create_task()` 在后台加载，启动时不阻塞

---

### 🟡 P2 - 无 ONNX / 量化推理

**问题：** 所有 embedding 都走 PyTorch eager 模式，没有使用 ONNX Runtime、OpenVINO、或 `optimum[onnxruntime]` 的量化加速。

**期望优化：**
- `bge-m3` 是否支持 ONNX 导出？
- 使用 `optimum` 库的 ORT 量化（int8/fp16）在 CPU 上通常有 2-5x 加速
- 是否值得引入 `fastembed`（基于 ONNX Runtime 的轻量 embedding 库）？

---

### 🟡 P2 - 多个冗余的 EmbeddingService 实现

**问题：** 代码库里有 **至少 5 个** EmbeddingService/encode 实现，互不相同，维护困难：

1. `src/backend/python-legacy/services/embedding_service.py` - 带 TEI/Redis/Postgres/Qdrant 的完整版
2. `src/backend/python-legacy/infrastructure/adapters/embedding_service.py` - 简化版，hardcode 本地路径
3. `src/backend/python-legacy/infrastructure/adapters/ai_models.py` - 适配器模式版（推荐，但被复用率低）
4. `src/backend/python-legacy/retrieval/vector_store.py` - 又一个独立版
5. `src/backend/retrieval-service/infrastructure/embedding_service.py` - retrieval service 专用版

**期望优化：**
- 是否应该统一成一个 `EmbeddingModelPort` 实现（`ai_models.py` 已经做了），所有模块共用？
- 如何处理 `retrieval-service` 和 `python-legacy` 的重复代码？

---

### 🟢 P3 - Retrieval Service 用 REST API 调 Qdrant（额外序列化开销）

**问题：** `retrieval-service/infrastructure/adapters/unified/unified_store.py:372` 使用 `requests.post()` 直接发 HTTP 到 Qdrant 的 REST endpoint，而不是用 `qdrant_client`。

**后果：**
- 向量在 Python dict -> JSON -> HTTP body -> Qdrant 之间多轮序列化/反序列化
- 1024维 float32 数组 JSON 化后体积膨胀约 3-5x
- `requests` 是同步调用，再次阻塞

**期望优化：**
- 统一使用 `qdrant_client.QdrantClient`（GRPC 或 HTTP），自带 batch upsert/search

---

## 3. 推荐优化优先级（给 Copilot 的实现顺序建议）

```
Phase 1 (立即，单文件改动):
  1. embedding_service.py: 移除 _store_to_qdrant 里的 recreate_collection，改为启动时检查创建
  2. embedding_service.py: 删除 conn.close() 误用
  3. embedding_service.py: redis.Redis -> redis.asyncio.Redis

Phase 2 (本周):
  4. 所有 async def 里的 model.encode() 改为 run_in_executor(ThreadPoolExecutor)
  5. 添加 TEI 到 docker-compose.yml，启动时健康检查
  6. 增加 query embedding 缓存（LRU + Redis）

Phase 3 (本月):
  7. 模型 ONNX 量化 / fastembed 替换
  8. 统一 EmbeddingService 实现，消除 5 个重复版本
  9. torch.set_num_threads 调优 + 启动懒加载
```

---

## 4. Copilot 提问模板（可复制粘贴）

### Prompt A: 紧急修复 Qdrant recreate + DB Pool + Redis 异步化
```
在 rag-dashboard 项目中，src/backend/python-legacy/services/embedding_service.py 有以下三个严重问题：

1. _store_to_qdrant() 每次 upsert 都调用 recreate_collection()，会删掉整个集合。请改成启动时一次性创建集合。
2. _store_to_postgres() 里 async with pool.acquire() 内部又 await conn.close()，这破坏了连接池。请修复。
3. 使用 redis.Redis（同步客户端）在 async 方法里。请改为 redis.asyncio.Redis。

要求：
- 只修改 embedding_service.py 这一个文件
- 保持现有接口不变（initialize / embed_text / embed_batch / embed_document_chunk / close）
- recreate_collection 的修复要保证：集合不存在时创建，存在时跳过
```

### Prompt B: 核心性能 - 把 model.encode() 从事件循环里捞出来
```
rag-dashboard 的 Python FastAPI 后端里，sentence_transformers 的 model.encode() 在多个 async def 方法中被同步调用，阻塞了整个事件循环。

涉及文件（按优先级）：
- src/backend/python-legacy/services/model_caller.py - _embed_local()
- src/backend/python-legacy/infrastructure/adapters/ai_models.py - encode()
- src/backend/retrieval-service/infrastructure/adapters/unified/unified_store.py - _multi_recall() 里调用 embedding_service.encode_query()

要求：
- 不破坏现有接口签名
- 使用 asyncio.get_running_loop().run_in_executor(ThreadPoolExecutor, ...) 方式
- ThreadPoolExecutor 应该在模块级或类级复用，不要每次调用都新建
- 对于 retrieval-service 的 UnifiedStore._multi_recall()，它目前是同步方法，如果它在 async 上下文被调用，请确保 encode_query 不会阻塞
```

### Prompt C: 架构优化 - 统一 Embedding 实现 + TEI 部署
```
rag-dashboard 里有 5 个不同的 EmbeddingService/encode 实现，非常混乱。请帮我：

1. 评估现有 5 个实现的差异，制定一个统一的 `EmbeddingModelPort` 实现策略
2. 在 infrastructure/docker-compose.yml 里添加 TEI (text-embeddings-inference) 服务容器，支持 CPU fallback
3. 增加启动时 TEI 健康检查：如果 TEI 不可用，自动切到本地模型，不要让请求等 30s 超时

参考文件：
- config/config.yaml (TEI 配置段)
- src/backend/python-legacy/infrastructure/adapters/ai_models.py (最规范的实现)
- src/backend/python-legacy/services/embedding_service.py (TEI 支持最全但问题最多)
```

---

## 5. 文件速查表

| 文件 | 问题数 | 关键行号 |
|------|--------|----------|
| `src/backend/python-legacy/services/embedding_service.py` | 4 (recreate_collection, conn.close, redis sync, tei timeout) | 73, 98, 280, 302, 361 |
| `src/backend/python-legacy/services/model_caller.py` | 1 (sync encode in async) | 215 |
| `src/backend/python-legacy/infrastructure/adapters/ai_models.py` | 1 (sync encode, no thread tuning) | 36, 69 |
| `src/backend/python-legacy/retrieval/vector_store.py` | 1 (sync encode) | 344 |
| `src/backend/python-legacy/retrieval/multi_stage_retriever.py` | 1 (sync embed) | 572 |
| `src/backend/retrieval-service/infrastructure/embedding_service.py` | 1 (sync encode, lazy load 缺失) | 32, 78 |
| `src/backend/retrieval-service/infrastructure/adapters/unified/unified_store.py` | 2 (sync encode, REST API 调 Qdrant) | 362, 372 |
| `config/config.yaml` | 1 (TEI enabled but no container) | 45-51 |
| `infrastructure/docker-compose.yml` | 1 (missing TEI service) | - |

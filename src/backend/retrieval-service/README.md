# Retrieval Service API

FastAPI microservice providing LangGraph ReAct Agent search over the four-database RAG system (Qdrant + PostgreSQL + Neo4j + Elasticsearch).

**Port:** `8002`  
**Base URL:** `http://localhost:8002`  
**Frontend access (via Go Gateway):** `http://localhost:8080/api/v1/agent`

---

## Startup

```bash
# From repo root (recommended — uses correct venv)
./start-all.sh local

# Manual
cd src/backend/retrieval-service
/home/l/rag-dashboard/venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8002
```

---

## Embedding + pgvector setup

The retrieval stack uses PostgreSQL + pgvector for dense retrieval and fulltext indexes for sparse retrieval.

### 1. Configure embedding backend

```bash
# llama.cpp OpenAI-compatible endpoint (recommended local path)
export EMBEDDING_BACKEND=llama_cpp_http
export LLAMA_CPP_EMBED_URL=http://127.0.0.1:8089
export LLAMA_CPP_EMBED_MODEL=bge-m3-q8_0.gguf
# optional strict guard
export EMBEDDING_VECTOR_DIM=1024
```

### 2. Bootstrap pgvector infra

```bash
python src/database/scripts/setup_pgvector_infra.py --probe-backend
```

### 3. Backfill embeddings

```bash
python src/database/scripts/backfill_embeddings.py --table text_chunks --backend llama_cpp --llama-url http://127.0.0.1:8089 --limit 0
python src/database/scripts/backfill_embeddings.py --table price_records --backend llama_cpp --llama-url http://127.0.0.1:8089 --limit 0
python src/database/scripts/backfill_embeddings.py --table fee_rates --backend llama_cpp --llama-url http://127.0.0.1:8089 --limit 0
python src/database/scripts/backfill_embeddings.py --table canonical_concepts --backend llama_cpp --llama-url http://127.0.0.1:8089 --limit 0
python src/database/scripts/backfill_embeddings.py --table chunk_vector_views --backend llama_cpp --llama-url http://127.0.0.1:8089 --limit 0
```

### 4. Verify database/vector health

```bash
python src/database/scripts/verify.py
python src/database/scripts/evaluate_retrieval_layers.py --strict
```

### 5. End-to-end OCR embedding pipeline

```bash
python src/database/scripts/run_full_ocr_embedding_pipeline.py \
  --embedding-backend llama_cpp \
  --llama-url http://127.0.0.1:8089 \
  --strict-metrics
```

---

## Routes

### GET /health

Health check.

```bash
curl http://localhost:8002/health
```

**Response:**
```json
{"status": "ok"}
```

---

### POST /api/v1/agent

Run the LangGraph ReAct agent synchronously. Returns full answer + retrieved chunks.

**Request:**

```json
{
  "query": "安全文明施工费计取基数是什么？",
  "session_id": "optional-uuid-for-conversation-continuity",
  "max_iterations": 5
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | ✓ | — | User question |
| `session_id` | string | — | auto-generated UUID | Conversation thread ID |
| `max_iterations` | int | — | `5` | Max ReAct loop iterations |

**Response:**

```json
{
  "session_id": "abc-123",
  "query": "安全文明施工费计取基数是什么？",
  "query_type": "standard_ref",
  "answer": "安全文明施工费的计取基数为...\n\n---\n**参考来源：** 《XX定额》P12",
  "chunks": [
    {
      "chunk_id": "tc_42_12",
      "doc_id": "42",
      "page": 12,
      "content": "安全文明施工费计取基数...",
      "score": 0.8721,
      "passed_threshold": true,
      "source": "2023广东定额总说明.pdf",
      "metadata": {
        "page": 12,
        "filename": "2023广东定额总说明.pdf"
      }
    }
  ],
  "evaluation": {
    "completeness": 0.85,
    "confidence": 0.90
  },
  "iterations": 2
}
```

**curl example:**

```bash
curl -s -X POST http://localhost:8002/api/v1/agent \
  -H "Content-Type: application/json" \
  -d '{"query": "安全文明施工费计取基数是什么？", "max_iterations": 3}' \
  | python3 -m json.tool
```

---

### POST /api/v1/agent/stream

Run the LangGraph ReAct agent with Server-Sent Events (SSE) streaming. Use this for real-time UI updates.

**Request:**

```json
{
  "query": "安全文明施工费计取基数是什么？",
  "session_id": "optional-uuid",
  "max_iterations": 3,
  "score_threshold": 0.60,
  "top_k": 8,
  "search_mode": "hybrid",
  "doc_types": []
}
```

**Response:** `text/event-stream`

Each line is an SSE event in the format:
```
event: <type>
data: <JSON>

```

#### SSE Event Types

| Event | Data shape | When |
|---|---|---|
| `query_analysis` | `{"intent": "standard_ref", "entities": [...], "sub_queries": [...]}` | After query analysis node |
| `retrieval_result` | `RetrievalChunk` (see below) | Once per retrieved chunk |
| `tool_call_start` | `{"call_id": "...", "tool": "price_lookup", "args": {...}}` | Before tool execution |
| `tool_call_end` | `{"call_id": "...", "tool": "price_lookup", "result_summary": "...", "duration_ms": 120}` | After tool execution |
| `eval_scores` | `{"completeness": 0.85, "confidence": 0.9, ...}` | After evaluator node |
| `loop_state` | `{"iteration": 2, "eval_score": 0.9, "max_iterations": 3}` | After each ReAct loop |
| `token` | `{"delta": "安全文明施工费的"}` | Answer tokens during synthesis |
| `done` | `{"answer": "...", "session_id": "...", "iterations": 2, "latency_ms": 4200}` | Stream complete |
| `error` | `{"message": "...", "code": "AGENT_ERROR"}` | On any exception |

#### RetrievalChunk schema

```typescript
interface RetrievalChunk {
  chunk_id: string;      // "tc_{doc_id}_{page}"
  doc_id: string;
  page: number;
  content: string;
  score: number;         // 0.0–1.0, rounded to 4 dp
  passed_threshold: boolean;  // score >= 0.60
  source: string;        // filename
  metadata: { page: number; filename: string };
}
```

**curl example (SSE):**

```bash
curl -N -X POST http://localhost:8002/api/v1/agent/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "P100 楼梯人工费是多少？", "max_iterations": 2}'
```

---

### POST /api/v1/search

Vector/keyword/hybrid search without the ReAct agent loop.

```bash
curl -s -X POST http://localhost:8002/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "楼梯人工费", "top_k": 5, "search_mode": "hybrid"}'
```

---

## Query Types

The agent auto-classifies queries into one of six intent types:

| Type | Triggers | Behaviour |
|---|---|---|
| `price` | 价格、单价、费用、元、元/m² | Looks up PostgreSQL price records |
| `calculation` | 计算、造价、合计、总价 | Uses calculation tool with Decimal precision |
| `comparison` | 对比、区别、与…比较 | Hybrid search across multiple docs |
| `trend_chart` | 趋势、波动、近年、走势 | Time-series price aggregation |
| `standard_ref` | 规范、标准、定额、填写、计税 | Dense document retrieval |
| `semantic` | (default) | General semantic search |

---

## Architecture

```
Frontend (React :3000)
  └─ Vite proxy /api/* → Go Gateway :8080
       └─ /api/v1/agent* → Retrieval Service :8002
            └─ LangGraph ReAct loop
                 ├─ query_analysis_node  (zero-shot classifier)
                 ├─ forced_rag_node      (mandatory first retrieval)
                 ├─ evaluator_node       (heuristic scorer)
                 ├─ react_node           (LLM tool-call decision)
                 ├─ tool_node            (price_lookup, calc, search)
                 └─ synthesize_node      (final answer + citations)
```

---

## Environment Variables

Key vars read from repo-root `.env` (via `config/loader.py`):

| Variable | Default | Description |
|---|---|---|
| `PG_HOST` / `PG_PORT` / `PG_DB` / `PG_USER` / `PG_PASSWORD` | `localhost/5432/rag_db/rag_user` | PostgreSQL connection |
| `EMBEDDING_BACKEND` | `sentence_transformers` | `sentence_transformers` or `llama_cpp_http` |
| `LLAMA_CPP_EMBED_URL` | `""` | llama.cpp `/v1/embeddings` endpoint |
| `LLAMA_CPP_EMBED_MODEL` | `llama.cpp-embedding` | model field sent to llama.cpp endpoint |
| `EMBEDDING_VECTOR_DIM` | `0` | optional strict dimension check (`0` = disabled) |
| `RETRIEVAL_OBSERVABILITY_ENABLED` | `1` | emit retrieval/embedding observability logs |
| `HYBRID_VECTOR_MIN_SCORE` | `0.40` | pgvector candidate threshold in `hybrid_search` |
| `HYBRID_VECTOR_FETCH_MULTIPLIER` | `1` | vector candidate multiplier (`top_k * multiplier`) |
| `HYBRID_TEXT_FETCH_MULTIPLIER` | `1` | fulltext candidate multiplier (`top_k * multiplier`) |
| `HYBRID_RRF_RANK_CONSTANT` | `60` | RRF rank constant for dense+sparse fusion |
| `HYBRID_STRUCTURED_TOP_K` | `top_k` | structured table candidate limit in hybrid pipeline |
| `HYBRID_LITERAL_TOP_K` | `top_k` | literal/fallback candidate limit in hybrid pipeline |
| `RETRIEVAL_SCORE_THRESHOLD` | `0.60` | Minimum chunk score |

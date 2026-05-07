# Project Resource Index

Human-readable capability map for this repo. Use this page before creating new helpers, wrappers, or parallel implementations.

For machine-readable lookup by AI/tools, see [`repo-capability-index.json`](repo-capability-index.json).
Run `npm run check:resource-index` after editing this page, [`repo-capability-index.json`](repo-capability-index.json), or the README reuse-first landing section.

## 1) Fast task lookup

| Task | First stop | Then check |
|---|---|---|
| Change config or read runtime settings | [`config/loader.py`](../config/loader.py) | [`config/config.yaml`](../config/config.yaml), [`docs/rag-system-internals/14-system-config.md`](rag-system-internals/14-system-config.md) |
| Add or debug an API route | [`src/backend/go-services/internal/gateway/proxy.go`](../src/backend/go-services/internal/gateway/proxy.go) | [`src/frontend/web/vite.config.ts`](../src/frontend/web/vite.config.ts), target service router |
| Work on search / rerank / evaluate / agent endpoints | [`src/backend/retrieval-service/app/api.py`](../src/backend/retrieval-service/app/api.py) | [`src/backend/retrieval-service/README.md`](../src/backend/retrieval-service/README.md) |
| Discover callable agent tools | [`src/backend/retrieval-service/app/tools_api.py`](../src/backend/retrieval-service/app/tools_api.py) | `GET /api/v1/tools` |
| Work on OCR | [`src/backend/ocr-service/ocr_service.py`](../src/backend/ocr-service/ocr_service.py) | [`docs/OCR-RESOURCES.md`](OCR-RESOURCES.md) |
| Change Node agent/runtime behavior | [`src/backend/server/src/modules/agent/src`](../src/backend/server/src/modules/agent/src) | [`docs/langgraph-runtime-core.md`](langgraph-runtime-core.md), [`rag-system-internals/12-agent-runtime.md`](rag-system-internals/12-agent-runtime.md) |
| Reuse TS contracts between web/server | [`packages/shared/src/index.ts`](../packages/shared/src/index.ts) | files under [`packages/shared/src/types`](../packages/shared/src/types) |
| Find operational scripts | [`scripts/`](../scripts) | [`start-all.sh`](../start-all.sh), [`stop-all.sh`](../stop-all.sh), [`tests/`](../tests) |

## 2) Canonical vs legacy surfaces

| Surface | Status | Notes |
|---|---|---|
| `src/backend/retrieval-service/` | **Canonical for retrieval/search** | Owns `/api/search`, `/api/v1/search`, rerank, evaluate, decompose, agent, tools, ops, learning APIs |
| `src/backend/python-legacy/` | **Active, but not canonical for search** | Still used for embedding, document ingestion, and compatibility APIs; do not assume new search work belongs here |
| `src/backend/server/src/modules/retrieval/` | **Helper/adapter layer** | Comments in code state real hybrid retrieval now runs in Python retrieval service; avoid treating this Node module as the production retrieval source of truth |
| `src/frontend/web/vite.config.ts` direct `/api/v1` proxy | **Dev-only shortcut** | Useful for local dev; shared routing truth still requires gateway mapping in `proxy.go` |
| `packages/shared/` | **Canonical TS shared contract package** | Reuse before duplicating request/response or infrastructure types in web/server |

## 3) Topology and connectivity map

```text
src/frontend/web
  -> vite.config.ts proxy rules
  -> src/backend/go-services/internal/gateway/proxy.go
      -> retrieval-service (search, rerank, evaluate, decompose, tools, learning)
      -> server (sessions, auth, agent APIs, pipeline orchestration)
      -> ocr-service (OCR)
      -> python-legacy (embedding, ingestion, compatibility)
      -> websocket gateway (/ws)
```

### Routing files you almost always need together

1. [`src/frontend/web/vite.config.ts`](../src/frontend/web/vite.config.ts)
2. [`src/backend/go-services/internal/gateway/proxy.go`](../src/backend/go-services/internal/gateway/proxy.go)
3. The target service router, usually one of:
   - [`src/backend/retrieval-service/app/api.py`](../src/backend/retrieval-service/app/api.py)
   - [`src/backend/retrieval-service/app/tools_api.py`](../src/backend/retrieval-service/app/tools_api.py)
   - [`src/backend/python-legacy/api/unified_api.py`](../src/backend/python-legacy/api/unified_api.py)
   - [`src/backend/ocr-service/ocr_service.py`](../src/backend/ocr-service/ocr_service.py)

## 4) Major services and packages

| Surface | Entrypoint | Responsibility | Reusable surfaces |
|---|---|---|---|
| Frontend | [`src/frontend/web`](../src/frontend/web) | React UI + dev proxy | `vite.config.ts`, imports from `@rag/shared` |
| Go gateway | [`cmd/gateway/main.go`](../src/backend/go-services/cmd/gateway/main.go) | Reverse proxy, `/health`, `/metrics` | `getRouteMapping()`, health aggregation, request IDs |
| Retrieval service | [`main.py`](../src/backend/retrieval-service/main.py) | Retrieval + tool + learning + architecture APIs | `app/api.py`, `app/tools_api.py`, `UnifiedRetrievalPipeline`, `UnifiedStore` |
| Node server | [`src/index.ts`](../src/backend/server/src/index.ts) | Fastify APIs, orchestration, XState runtime, broadcasts | `AgentFactory`, `ReactAgent`, `createFourDatabaseTools()`, `runtimeConfig` |
| OCR service | [`ocr_service.py`](../src/backend/ocr-service/ocr_service.py) | PDF/image OCR sync + async | `OCRDocumentResult`, async job endpoints |
| Python legacy | [`main.py`](../src/backend/python-legacy/main.py), [`rag_api_service.py`](../src/backend/python-legacy/rag_api_service.py) | Embedding, document workflows, compatibility APIs | `api/unified_api.py`, `config/runtime.py` |
| Shared TS package | [`packages/shared/src/index.ts`](../packages/shared/src/index.ts) | Shared web/server types | `chat`, `ocr`, `infrastructure`, `recursion` types |
| Config | [`config/loader.py`](../config/loader.py), [`src/backend/server/src/config/runtime.ts`](../src/backend/server/src/config/runtime.ts), [`src/frontend/web/src/config/runtime.ts`](../src/frontend/web/src/config/runtime.ts), [`src/backend/go-services/config/runtime.go`](../src/backend/go-services/config/runtime.go), [`src/backend/retrieval-service/app/runtime_config.py`](../src/backend/retrieval-service/app/runtime_config.py), [`src/backend/retrieval-service/app/runtime_overrides.py`](../src/backend/retrieval-service/app/runtime_overrides.py), [`src/backend/python-legacy/config/runtime.py`](../src/backend/python-legacy/config/runtime.py) | Canonical Python, Node, frontend, Go, retrieval-service runtime config, retrieval-service runtime overrides, and python-legacy runtime entrypoints | `RAGConfig`, `get_config()`, `reload_config()`, `createRuntimeConfig()`, `getApiBaseUrl()`, `LoadGatewayConfig()`, `LoadWebSocketConfig()`, `read_runtime_config()`, `postgres_connection_kwargs()`, `redis_connection_kwargs()`, `resolve_local_model_path()`, `get_runtime_override()`, `apply_runtime_override()` |

## 5) Capability catalog

### 5.1 Config and runtime settings

| Surface | Path | Public API / shape | Minimal usage |
|---|---|---|---|
| Python config loader | [`config/loader.py`](../config/loader.py) | `RAGConfig`, `get_config()`, `reload_config()`, env prefix `RAG__SECTION__KEY` | `from config.loader import get_config; cfg = get_config(); cfg.get_service_url("ocr")` |
| Node runtime config | [`src/backend/server/src/config/runtime.ts`](../src/backend/server/src/config/runtime.ts) | `createRuntimeConfig()`, `runtimeConfig`, `resolveLlmApiKey()`, precedence `default.json -> env -> CLI` | `const runtimeConfig = createRuntimeConfig(); const apiKey = resolveLlmApiKey(runtimeConfig.llm, body.apiKey); const ocr = createOCRPipeline({ language: runtimeConfig.ocr.language }); const persistence = new PostgresPersistenceService({ enabled: runtimeConfig.persistence.enabled })` |
| Frontend runtime config | [`src/frontend/web/src/config/runtime.ts`](../src/frontend/web/src/config/runtime.ts) | `frontendRuntimeConfig`, `getApiBaseUrl()`, `resolveWebSocketUrl()` driven by Vite env defaults | `import { getApiBaseUrl, resolveWebSocketUrl } from './config/runtime'; const apiBase = getApiBaseUrl(); const wsUrl = resolveWebSocketUrl('dashboard')` |
| Go runtime config | [`src/backend/go-services/config/runtime.go`](../src/backend/go-services/config/runtime.go), [`src/backend/go-services/config/default.json`](../src/backend/go-services/config/default.json) | `LoadGatewayConfig(args)`, `LoadWebSocketConfig(args)`, precedence `embedded defaults -> optional JSON config file -> env -> CLI` | `cfg, telemetryCfg, err := config.LoadGatewayConfig(os.Args[1:]); wsCfg, err := config.LoadWebSocketConfig(os.Args[1:])` |
| Retrieval-service runtime config | [`src/backend/retrieval-service/app/runtime_config.py`](../src/backend/retrieval-service/app/runtime_config.py) | `bootstrap_runtime_environment()`, `bootstrap_llm_proxy_environment()`, `read_runtime_config()`, `postgres_connection_kwargs()`, `redis_connection_kwargs()`, `resolve_local_model_path()` | `from app.runtime_config import read_runtime_config, postgres_connection_kwargs, resolve_local_model_path; runtime = read_runtime_config(); ocr_url = runtime.ocr_service_url; pg = postgres_connection_kwargs(); model_path = resolve_local_model_path('BAAI/bge-m3')` |
| Retrieval-service runtime overrides | [`src/backend/retrieval-service/app/runtime_overrides.py`](../src/backend/retrieval-service/app/runtime_overrides.py) | `get_runtime_override()`, `apply_runtime_override()`, `validate_runtime_override()`, DB tables `runtime_config_overrides` + `runtime_config_audit` | `from app.runtime_overrides import get_runtime_override; top_k = get_runtime_override("top_k", 10)` |
| Python-legacy runtime config | [`src/backend/python-legacy/config/runtime.py`](../src/backend/python-legacy/config/runtime.py) | `bootstrap_runtime_environment()`, `read_runtime_config()`, `tool_pg_config()`, `tool_pg_database()`, runtime-owned `embedding_model_path` / `rerank_model_path` with precedence `default -> config/config.yaml -> env -> constructor/runtime args` | `from config.runtime import read_runtime_config, tool_pg_config, tool_pg_database; runtime = read_runtime_config(); tei_url = runtime.tei_url; rerank_path = runtime.rerank_model_path; pg = tool_pg_config(); db_name = tool_pg_database("rag_dashboard")` |
| Main config file | [`config/config.yaml`](../config/config.yaml) | YAML-backed defaults consumed by `RAGConfig.from_yaml()` | Put stable environment-specific defaults here |
| Node runtime defaults | [`src/backend/server/config/default.json`](../src/backend/server/config/default.json) | startup defaults for server, auth bootstrap, service connectivity, task queue, pipeline, recursion, logging, telemetry, database helpers, Neo4j/Elasticsearch settings, embeddings, retrieval module defaults, cascade retrieval flags/weights, OCR defaults, storage helper settings, persistence enablement, expert-judgment settings, request-path LLM behavior, agent helper behavior, and dev/prod runtime mode | Change file-level defaults here instead of hardcoding startup, module-helper, or request-path values in `index.ts`, service classes, or shared Node libraries |
| Frontend dev proxy | [`src/frontend/web/vite.config.ts`](../src/frontend/web/vite.config.ts) | `VITE_WEB_PORT`, `VITE_NODE_URL`, `VITE_RETRIEVAL_URL`, `VITE_GATEWAY_URL`, `VITE_WS_GATEWAY_URL` | Update when local dev routing changes |

### 5.2 Routing and gateway ownership

| Surface | Path | Public API / shape | Key inputs / outputs |
|---|---|---|---|
| Gateway route table | [`src/backend/go-services/internal/gateway/proxy.go`](../src/backend/go-services/internal/gateway/proxy.go) | `getRouteMapping()`, `findTargetService()`, `ProxyHandler()` | Input: request path. Output: target service + proxied response |
| Gateway bootstrap | [`src/backend/go-services/cmd/gateway/main.go`](../src/backend/go-services/cmd/gateway/main.go) | `gateway.LoadConfig(os.Args[1:])`, `gateway.SetupRouter()` | Starts HTTP gateway from Go runtime config (`--config`, `GATEWAY_PORT`/`PORT`, service URL envs, CLI overrides) |

**Usage pattern:** when adding a new externally reachable API prefix, register it in `getRouteMapping()` and verify whether `vite.config.ts` also needs a matching dev proxy rule.

### 5.3 Retrieval, tools, and search APIs

| Surface | Path | Public API / shape | Minimal usage |
|---|---|---|---|
| Retrieval HTTP API | [`src/backend/retrieval-service/app/api.py`](../src/backend/retrieval-service/app/api.py) | `/api/search`, `/api/v1/search`, `/api/v1/rerank`, `/api/v1/evaluate`, `/api/v1/decompose`, `/api/v1/agent`, `/api/v1/agent/stream`, learning/ops/system endpoints | `curl -X POST http://localhost:8002/api/v1/search -H 'Content-Type: application/json' -d '{"query":"test","top_k":5,"mode":"hybrid"}'` |
| Tool catalog API | [`src/backend/retrieval-service/app/tools_api.py`](../src/backend/retrieval-service/app/tools_api.py) | `GET /api/v1/tools`, `GET /api/v1/tools/{name}`, `POST /api/v1/tools/{name}/invoke` | `curl http://localhost:8002/api/v1/tools` |
| Retrieval service bootstrapping | [`src/backend/retrieval-service/main.py`](../src/backend/retrieval-service/main.py) | initializes `UnifiedStore`, `UnifiedRetrievalPipeline`, tool router, learning schedulers, and repo-root env/proxy bootstrap via `bootstrap_runtime_environment()` | Entry for service startup and lifespan behavior |
| Retrieval service docs | [`src/backend/retrieval-service/README.md`](../src/backend/retrieval-service/README.md) | service-level API and setup guide | Use when you need endpoint examples or embedding setup |

**Key request shapes to remember**

- Search: `{"query": str, "top_k": int, "mode": "vector|keyword|graph|hybrid", "session_id"?: str}`
- Rerank: `{"query": str, "documents": [{"id": str, "content": str}], "top_k": int}`
- Tool invoke: `{"args": {...}}`

### 5.4 Agent runtime and orchestration (Node)

| Surface | Path | Public API / shape | Minimal usage |
|---|---|---|---|
| Agent factory | [`src/backend/server/src/modules/agent/src/factory.ts`](../src/backend/server/src/modules/agent/src/factory.ts) | `AgentFactory.create(framework, llmOptions, options, eventCallback)` | `const agent = AgentFactory.create('langchain', { model, apiKey }, { maxIterations: 5 })` |
| Agent ReAct loop | [`src/backend/server/src/modules/agent/src/react-loop.ts`](../src/backend/server/src/modules/agent/src/react-loop.ts) | `ReactAgent.run(query)`, `AgentIterationEvent` | Change iterative reasoning/tool-call behavior here |
| Agent tool set | [`src/backend/server/src/modules/agent/src/tools.ts`](../src/backend/server/src/modules/agent/src/tools.ts) | `createVectorSearchTool()`, `createKeywordSearchTool()`, `createGraphSearchTool()`, `createCalculatorTool()`, `createFourDatabaseTools()` | Reuse these before adding new LangChain tool wrappers |

### 5.5 OCR and document processing

| Surface | Path | Public API / shape | Minimal usage |
|---|---|---|---|
| OCR service | [`src/backend/ocr-service/ocr_service.py`](../src/backend/ocr-service/ocr_service.py) | `GET /health`, `POST /ocr/pdf`, `POST /ocr/pdf/async`, `GET /ocr/pdf/async/{job_id}`, `POST /ocr/image` | `curl -F 'file=@doc.pdf' http://localhost:8001/ocr/pdf` |
| OCR models | [`src/backend/ocr-service/ocr_service.py`](../src/backend/ocr-service/ocr_service.py) | `OCRTextBlock`, `OCRTable`, `OCRFigure`, `OCRPageResult`, `OCRDocumentResult`, `AsyncJobStatus` | Reuse these shapes before inventing new OCR payload contracts |
| OCR reference doc | [`docs/OCR-RESOURCES.md`](OCR-RESOURCES.md) | framework comparison + design references | Use for OCR stack selection and trade-offs |

### 5.6 Python legacy / compatibility layer

| Surface | Path | Public API / shape | Notes |
|---|---|---|---|
| Legacy main entry | [`src/backend/python-legacy/main.py`](../src/backend/python-legacy/main.py) | imports `api.unified_api.app` | Active entrypoint, despite `legacy` name |
| Unified API | [`src/backend/python-legacy/api/unified_api.py`](../src/backend/python-legacy/api/unified_api.py) | `/api/search`, document upload/process, stats, rerank, evaluate, decompose, pipeline endpoints | Useful for compatibility and ingestion; not the default place to add new search-first behavior |

### 5.7 Shared contracts and frontend integration

| Surface | Path | Public API / shape | Minimal usage |
|---|---|---|---|
| Shared TS barrel | [`packages/shared/src/index.ts`](../packages/shared/src/index.ts) | re-exports chat, OCR, infrastructure, recursion types | `import { InfrastructureOverview } from '@rag/shared'` |
| Shared package build | [`packages/shared/package.json`](../packages/shared/package.json) | `npm run build`, `npm run dev` | Build when consumers need `dist/` |
| Frontend package | [`src/frontend/web/package.json`](../src/frontend/web/package.json) | `npm run dev`, `npm run build`, `npm run preview` | UI entrypoint; runtime env reads now centralize in `src/config/runtime.ts` |

## 6) Scripts and operational entrypoints

| Surface | Path | What it does |
|---|---|---|
| Local stack start | [`start-all.sh`](../start-all.sh) | starts Python legacy, retrieval, Node server, websocket gateway, API gateway |
| Local stack stop | [`stop-all.sh`](../stop-all.sh) | stops local ports/processes |
| Resource index check | [`package.json`](../package.json), [`repo-capability-index.schema.json`](repo-capability-index.schema.json) | validates the machine-readable manifest with `ajv-cli` and repo markdown links with `remark-validate-links` |
| Health check | [`scripts/health_check.sh`](../scripts/health_check.sh) | infra + API + resource checks |
| Index self docs | [`scripts/index_self_docs.py`](../scripts/index_self_docs.py) | doc/system KB indexing helper |
| Index system KB | [`scripts/index_system_kb.py`](../scripts/index_system_kb.py) | KB indexing helper |
| Architecture sync | [`scripts/sync_arch_docs.py`](../scripts/sync_arch_docs.py) | refreshes live architecture block in docs |
| Topology check | [`scripts/topology_health.py`](../scripts/topology_health.py) | topology/connectivity health helper |

## 7) Tests and validation entrypoints

| Surface | Path / command | Scope |
|---|---|---|
| Root test command | `npm test` | Node + Python test umbrella |
| Root typecheck | `npm run typecheck` | TypeScript server typecheck |
| Node tests | `cd src/backend/server && npm test` | Vitest for server modules |
| Python tests | `cd src/backend/python-legacy && python -m pytest tests/ -v` | legacy Python tests |
| Retrieval script | [`tests/retrieval-service-test.sh`](../tests/retrieval-service-test.sh) | boots retrieval service and hits core endpoints |
| Gateway routing script | [`tests/gateway-routing-test.sh`](../tests/gateway-routing-test.sh) | verifies path-to-service behavior |
| Other integration scripts | [`tests/`](../tests) | websocket, auth, frontend, end-to-end, persistence |

## 8) Key docs already in the repo

| Topic | Doc |
|---|---|
| Architecture implementation | [`docs/ARCHITECTURE_IMPLEMENTATION.md`](ARCHITECTURE_IMPLEMENTATION.md) |
| Runtime mental model | [`docs/langgraph-runtime-core.md`](langgraph-runtime-core.md) |
| OCR references | [`docs/OCR-RESOURCES.md`](OCR-RESOURCES.md) |
| Retrieval internals | [`docs/rag-system-internals/09-retrieval-pipeline.md`](rag-system-internals/09-retrieval-pipeline.md) |
| Agent runtime internals | [`docs/rag-system-internals/12-agent-runtime.md`](rag-system-internals/12-agent-runtime.md) |
| Usage guide | [`docs/rag-system-internals/13-usage-guide.md`](rag-system-internals/13-usage-guide.md) |
| Config internals | [`docs/rag-system-internals/14-system-config.md`](rag-system-internals/14-system-config.md) |
| FAQ | [`docs/rag-system-internals/15-faq.md`](rag-system-internals/15-faq.md) |

## 9) What still needs judgment when reusing code

Even with this index, a few areas still deserve a quick source check before editing:

- `src/backend/retrieval-service/app/api.py` is very large; use the service README or search within the file once you know the endpoint family.
- top-level markdown reports are numerous and uneven in freshness; prefer the service entrypoints and numbered `docs/rag-system-internals/` set first.
- gateway-specific README examples may lag behind the live route table; treat `proxy.go` as the routing source of truth.

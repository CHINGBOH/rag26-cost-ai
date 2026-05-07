# RAG Dashboard

Polyglot RAG monorepo for retrieval, OCR, agent runtime, routing, and UI.

> **Reuse-first rule:** before adding a new helper, module, or wrapper, check the [Project Resource Index](docs/project-resource-index.md) and the machine-readable [Repo Capability Index](docs/repo-capability-index.json). They point to the canonical surfaces already in this repo.
>
> **Anti-drift check:** after editing those index surfaces or adding a new reusable public surface, run `npm run check:resource-index`.

## Start here by task

| If you need... | Start here | Why |
|---|---|---|
| Config and runtime settings | [`config/loader.py`](config/loader.py), [`config/config.yaml`](config/config.yaml), [`docs/rag-system-internals/14-system-config.md`](docs/rag-system-internals/14-system-config.md) | Canonical Python config loader and precedence rules |
| Gateway routing / API path ownership | [`src/backend/go-services/internal/gateway/proxy.go`](src/backend/go-services/internal/gateway/proxy.go), [`src/frontend/web/vite.config.ts`](src/frontend/web/vite.config.ts) | Production routing lives in Go; dev proxy behavior lives in Vite |
| Retrieval / search / rerank / tools | [`src/backend/retrieval-service/app/api.py`](src/backend/retrieval-service/app/api.py), [`src/backend/retrieval-service/app/tools_api.py`](src/backend/retrieval-service/app/tools_api.py), [`src/backend/retrieval-service/README.md`](src/backend/retrieval-service/README.md) | Canonical search and tool surfaces |
| OCR processing | [`src/backend/ocr-service/ocr_service.py`](src/backend/ocr-service/ocr_service.py), [`docs/OCR-RESOURCES.md`](docs/OCR-RESOURCES.md) | OCR API entrypoint plus design/reference doc |
| Agent runtime / ReAct loop | [`src/backend/server/src/modules/agent/src/`](src/backend/server/src/modules/agent/src/), [`docs/langgraph-runtime-core.md`](docs/langgraph-runtime-core.md) | Active Node agent loop, tool set, and runtime design references |
| Shared TypeScript contracts | [`packages/shared/src/index.ts`](packages/shared/src/index.ts) | Shared types reused by server and web |
| Dev/startup scripts | [`start-all.sh`](start-all.sh), [`stop-all.sh`](stop-all.sh), [`scripts/`](scripts) | Main local ops entrypoints |
| Tests and validation | [`package.json`](package.json), [`tests/`](tests), [`src/backend/server/package.json`](src/backend/server/package.json) | Root test commands plus focused shell/integration tests |
| Architecture and subsystem docs | [`docs/project-resource-index.md`](docs/project-resource-index.md), [`docs/repo-capability-index.json`](docs/repo-capability-index.json), [`docs/rag-system-internals`](docs/rag-system-internals), [`docs/ARCHITECTURE_IMPLEMENTATION.md`](docs/ARCHITECTURE_IMPLEMENTATION.md) | Human-readable and machine-readable maps of the repo |

## Topology at a glance

```text
Frontend (src/frontend/web)
  -> dev proxy in vite.config.ts
  -> Go Gateway route map in internal/gateway/proxy.go
  -> Retrieval Service (8002) for /api/search, /api/v1/search, rerank, evaluate, decompose, agent APIs
  -> Node Server (3001) for /api/agent, sessions, auth, pipeline orchestration, websocket events
  -> OCR Service (8001) for /api/ocr and raw /ocr/* OCR endpoints
  -> Python Legacy (8000) for embedding, document ingestion, and compatibility APIs
```

### Canonical routing reminders

- **Search is not owned by `python-legacy`.** The canonical `/api/search` and `/api/v1/search` flow goes to **`src/backend/retrieval-service`**.
- **New API prefixes must be wired in the Go gateway** via [`getRouteMapping()`](src/backend/go-services/internal/gateway/proxy.go).
- **Frontend routing changes usually need two edits**: [`src/frontend/web/vite.config.ts`](src/frontend/web/vite.config.ts) for dev and [`src/backend/go-services/internal/gateway/proxy.go`](src/backend/go-services/internal/gateway/proxy.go) for shared/prod behavior.
- **`src/backend/python-legacy` is still active despite the name**: use it for embedding, ingestion, and compatibility endpoints, not as the default search implementation.

## Service and package map

| Surface | Port | Canonical entrypoint | Use it for |
|---|---:|---|---|
| Frontend | 3000 | [`src/frontend/web`](src/frontend/web) | React/Vite UI, dev proxy, shared TS contracts |
| Go API Gateway | 8080 | [`src/backend/go-services/cmd/gateway/main.go`](src/backend/go-services/cmd/gateway/main.go) | Path-based routing, health, metrics |
| Go WebSocket Gateway | 8081 | [`src/backend/go-services/cmd/websocket/main.go`](src/backend/go-services/cmd/websocket/main.go) | WebSocket fan-out |
| Retrieval Service | 8002 | [`src/backend/retrieval-service/main.py`](src/backend/retrieval-service/main.py) | Search, rerank, evaluate, decompose, tool APIs, learning/ops endpoints |
| Node Server | 3001 | [`src/backend/server/src/index.ts`](src/backend/server/src/index.ts) | Session/auth APIs, XState runtime, orchestration, broadcasts |
| OCR Service | 8001 | [`src/backend/ocr-service/ocr_service.py`](src/backend/ocr-service/ocr_service.py) | PDF/image OCR sync + async |
| Python Legacy | 8000 | [`src/backend/python-legacy/main.py`](src/backend/python-legacy/main.py) | Embedding, document ingestion, compatibility APIs |
| Shared types | — | [`packages/shared/src/index.ts`](packages/shared/src/index.ts) | Reusable TS types for server + web |
| Config loader | — | [`config/loader.py`](config/loader.py) | Canonical Python config access |

## High-value reusable areas

| Area | Path | Reuse before inventing |
|---|---|---|
| Config access | [`config/loader.py`](config/loader.py) | `get_config()`, `reload_config()`, `RAGConfig` |
| Route ownership | [`src/backend/go-services/internal/gateway/proxy.go`](src/backend/go-services/internal/gateway/proxy.go) | `getRouteMapping()`, `findTargetService()` |
| Retrieval APIs | [`src/backend/retrieval-service/app/api.py`](src/backend/retrieval-service/app/api.py) | Search/rerank/evaluate/decompose/agent endpoints |
| Tool catalog over HTTP | [`src/backend/retrieval-service/app/tools_api.py`](src/backend/retrieval-service/app/tools_api.py) | `/api/v1/tools`, `/api/v1/tools/{name}/invoke` |
| Agent factories and tool set | [`src/backend/server/src/modules/agent/src`](src/backend/server/src/modules/agent/src) | `AgentFactory`, `ReactAgent`, `createFourDatabaseTools()` |
| OCR endpoints/models | [`src/backend/ocr-service/ocr_service.py`](src/backend/ocr-service/ocr_service.py) | `OCRDocumentResult`, async job flow |
| Shared TS types | [`packages/shared/src`](packages/shared/src) | chat, OCR, infrastructure, recursion types |

## Quick local entrypoints

```bash
# Start core services locally
./start-all.sh local

# Stop them
./stop-all.sh

# Frontend only
cd src/frontend/web && npm run dev

# Retrieval service only
cd src/backend/retrieval-service && python -m uvicorn main:app --host 0.0.0.0 --port 8002
```

## Tests and validation entrypoints

| Scope | Command / file |
|---|---|
| Root Node + Python tests | `npm test` |
| Fast typecheck | `npm run typecheck` |
| Advisory TS/JS code-health lane | `npm run audit:advisory` |
| Node server tests | `cd src/backend/server && npm test` |
| Python legacy tests | `cd src/backend/python-legacy && python -m pytest tests/ -v` |
| Retrieval integration script | [`tests/retrieval-service-test.sh`](tests/retrieval-service-test.sh) |
| Gateway routing verification | [`tests/gateway-routing-test.sh`](tests/gateway-routing-test.sh) |
| Frontend / websocket / auth flows | [`tests/`](tests) |

> **Advisory code-health lane:** `npm run audit:advisory` checks TS/JS dead files/exports, dependency graph issues, circular imports, and duplication hotspots without changing the existing default test/typecheck entrypoints. The broader non-blocking full-repo advisory workflow lives in [`.github/workflows/code-health-advisory.yml`](.github/workflows/code-health-advisory.yml).

## Key docs worth knowing

- [Project Resource Index](docs/project-resource-index.md) — deeper capability catalog for humans
- [Repo Capability Index](docs/repo-capability-index.json) — machine-readable manifest for AI/tooling and quick surface lookup
- [Retrieval Service README](src/backend/retrieval-service/README.md) — retrieval APIs and examples
- [Go Gateway README](src/backend/go-services/README.md) — gateway-specific details
- [OCR resources](docs/OCR-RESOURCES.md) — OCR references and design options
- [LangGraph runtime core notes](docs/langgraph-runtime-core.md) — mental model for runtime/state/channel design
- [RAG system internals](docs/rag-system-internals) — numbered subsystem docs for architecture, tools, retrieval, runtime, config, and FAQ

## Need the deeper map?

Use the human-readable [Project Resource Index](docs/project-resource-index.md) for:

- canonical vs legacy callouts
- reusable module and API entrypoints
- minimal usage examples
- task-oriented paths for config, routing, retrieval, OCR, agent runtime, scripts, tests, and docs

For AI/tooling-oriented lookup, use the machine-readable [Repo Capability Index](docs/repo-capability-index.json).

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack at a glance

| Surface | Path | Port | Tech |
|---|---|---|---|
| Frontend | `src/frontend/web/` | 3000 | React 18 + Vite |
| Node orchestrator | `src/backend/server/` | 3001 | Fastify + XState v5 |
| Go API gateway | `src/backend/go-services/` | 8080 | Reverse proxy |
| Go WebSocket gateway | `src/backend/go-services/` | 8081 | Real-time broadcast |
| Python legacy API | `src/backend/python-legacy/` | 8000 | Embedding, ingestion |
| Retrieval service | `src/backend/retrieval-service/` | 8002 | FastAPI + LangGraph ReAct |
| OCR service | `src/backend/ocr-service/` | 8001 | Separate Python service |
| Shared TS package | `packages/shared/` | — | Types for web + Node |

Root `package.json` is an npm workspace covering `packages/*`, `src/frontend/*`, `src/backend/server`, and `src/backend/ocr-service`.

## Commands

### Start / stop

```bash
./start-all.sh local      # local stack (Python + Go + Node)
./start-all.sh docker     # Docker-based stack
./stop-all.sh
```

`npm run dev` only covers workspace dev scripts — it does not start Python or Go services.

### Build

```bash
cd packages/shared && npm run build          # build shared types first
cd src/backend/server && npm run build       # Node orchestrator
cd src/frontend/web && npm run build         # frontend
cd src/backend/go-services && go build ./...
```

### Test

```bash
npm test                                     # root smoke suite (Node + python-legacy)

# Node
cd src/backend/server && npm test
cd src/backend/server && npx vitest run src/modules/auth/__tests__/auth.test.ts
cd src/backend/server && npx vitest run src/__tests__/Agent.test.ts -t "should"

# Python legacy
cd src/backend/python-legacy && python -m pytest tests/ -v
cd src/backend/python-legacy && python -m pytest tests/test_api.py -q

# Retrieval service
cd src/backend/retrieval-service && python -m pytest tests/test_learning_endpoints.py -q
cd src/backend/retrieval-service && python -m pytest tests/test_query_analyzer_routing.py -q

# Integration (requires running stack)
python tests/test_agent_16.py
python -m pytest tests/routing/test_issue96_routing.py -q

# Go
cd src/backend/go-services && go test ./...
cd src/backend/go-services && go test ./internal/gateway -run TestFindTargetServiceRoutesExecutorEndpointsToRetrieval -v
```

`tests/test_agent_16.py` has a special audit rule: do not trust `passed`/confidence alone — inspect `answer_preview` for refusal phrases before claiming success.

### Lint / type-check

There is no single monorepo lint command. Use per-stack checks:

```bash
npm run typecheck                            # TypeScript

ruff check src/backend/python-legacy src/backend/retrieval-service
black --check src/backend/python-legacy src/backend/retrieval-service
mypy src/backend/python-legacy

qlty check                                  # optional, if installed
```

## Architecture

### Request routing

The Vite dev proxy and the Go gateway use **different** routing tables — read `vite.config.ts` first, then `proxy.go`, then the target backend when routing is unclear.

Dev proxy splits:
- `/api/agent` → Node orchestrator (`:3001`)
- `/api/v1/*` → retrieval service (`:3002`)
- `/api/*`, `/health`, `/metrics` → Go gateway (`:8080`)
- `/ws` → Go WebSocket gateway (`:8081`)

The Go gateway (`src/backend/go-services/internal/gateway/proxy.go`) uses **longest-prefix** matching via `getRouteMapping()`. New frontend-reachable prefixes must be registered there or the gateway returns 404.

### Service ownership (non-obvious)

- **Retrieval service** owns `/api/search`, `/api/v1/search`, `/api/v1/rag`, `/api/v1/agent`, `/api/v1/learning`, `/api/v1/executor`, `/api/v1/architecture`, `/api/v1/tools`, `/api/v1/sandbox`, `/api/v1/evaluate`, `/api/v1/rerank`.
- **Python legacy** owns `/api/v1/embedding`, `/api/v1/documents`, `/api/stats`, `/api/v1/stats`.
- **Node orchestrator** owns `/api/sessions`, `/api/activity`, `/api/heartbeat`, `/api/auth`, `/api/pipeline`, `/api/cache`, `/api/queue`, `/api/system`, `/api/agent`.

### WebSocket

Node is **not** the WebSocket server. It emits events via `WebSocketManager` to the Go WebSocket gateway. Debug real-time issues in both the Node emission path and the Go WebSocket process.

### Four-database RAG storage

1. **Qdrant** — dense vector embeddings, semantic search
2. **PostgreSQL + pgvector** — structured data, full-text search
3. **Elasticsearch** — keyword/full-text with IK analyzer
4. **Neo4j** — knowledge graph for relationship queries
5. **Redis** — cache and session store

### `@rag/shared` build dependency

`packages/shared/dist` must exist for Node and TypeScript builds. The Vite dev config can fall back to `packages/shared/src/index.ts`, but always build `packages/shared` first when types appear missing.

### Config layering

Config precedence (lowest → highest): YAML defaults → `.env` → environment variables (`RAG__SECTION__KEY`) → command-line → runtime dynamic input.

- **Python**: all mutable runtime config flows through `config/loader.py` (`get_config()`, `reload_config()`). Do not add ad-hoc `os.getenv` calls.
- **Node**: run commands from `src/backend/server/` so the relative `.env` lookup resolves. The legacy `.env` parser in `src/backend/server/src/index.ts` (before telemetry init) is a known bad pattern — do not copy it into new domains.

## Key conventions

- **Do not move Python imports above `sys.path.insert(0, project_root)`** in `python-legacy` — that bootstrap is required in multiple runtime files.
- Use **Pydantic v2** for Python schema validation and **Zod** for TypeScript. Avoid bare `dict`, `object`, or `any` as business-layer interfaces.
- XState is **v5 only**: use `createActor()`, write guards as functions, give invoked actors explicit `onError`, and stop spawned actors.
- Before adding a new module, service, endpoint, config surface, or job, consult `docs/project-resource-index.md` and `docs/repo-capability-index.json`. Extend an existing owned surface when one covers the need.
- Keep topology connected end-to-end: no black-hole routes, isolated files, dead parameters, or disconnected UI/API/test surfaces. If something cannot be reached and exercised, finish the wiring or delete it.
- Prefer hard cutovers over dual-read/dual-write compatibility shims. If an old path must survive, name both the canonical path and the exact surviving file.
- The OCR service is not covered by the root Python project metadata. Check `src/backend/ocr-service/requirements.txt` separately when touching OCR.
- Behavior-changing operations should leave timestamped traces in an existing audit surface (structured logs, state tables, event ledgers).

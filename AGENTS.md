# AGENTS.md — RAG Dashboard

Compact reference for AI agents working in this repo. Every item below is something you would likely guess wrong or waste time discovering.

## What this repo is

Polyglot microservices RAG system ("四库" = Qdrant + PostgreSQL + Neo4j + Elasticsearch). PyPI name `rag-retrieval`.

Languages: Python 3.10 (FastAPI), Node.js + TypeScript (Fastify + XState v5), Go 1.21 (Gin), React 18 (Vite).

## Monorepo boundaries & entrypoints

| Package / Service | Path | Entry | Notes |
|---|---|---|---|
| Python legacy API | `src/backend/python-legacy/` | `main.py` | Unified API, embedding, ingestion |
| Retrieval service | `src/backend/retrieval-service/` | `main.py` | Standalone search/rerank microservice |
| OCR service | `src/backend/ocr-service/` | `ocr_service.py` | PaddleOCR; has own `requirements.txt` |
| Node orchestrator | `src/backend/server/` | `src/index.ts` | XState v5 agent runtime, WS manager |
| Go gateway | `src/backend/go-services/` | `cmd/gateway/main.go` | Reverse proxy to all backends |
| Go websocket | `src/backend/go-services/` | `cmd/websocket/main.go` | WS broadcast gateway |
| React frontend | `src/frontend/web/` | `vite` dev | Uses `@rag/shared` |
| Shared types | `packages/shared/` | built to `dist/` | Consumed by `@rag/server` and `@rag/web` |
| Agent CLI | `clawai/` | Typer CLI | Separate Python 3.11+ project, own `pyproject.toml` |

Root `package.json` defines npm workspaces: `packages/*`, `src/frontend/*`, `src/backend/server`, `src/backend/ocr-service`.

## Running things

### Local dev (recommended)
```bash
./start-all.sh local   # checks ports, starts Python + Node + Go binaries in background
./stop-all.sh          # kills local background services
```

### Docker (all infra + apps)
```bash
docker-compose up -d          # includes Postgres, Redis, Qdrant, ES, Neo4j, TEI, all apps
docker-compose -f infrastructure/docker-compose.langfuse.yml up -d   # observability
```

### One service at a time
```bash
# Python legacy
cd src/backend/python-legacy && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Retrieval service
cd src/backend/retrieval-service && python -m uvicorn main:app --host 0.0.0.0 --port 8002

# OCR service
cd src/backend/ocr-service && python -m uvicorn ocr_service:app --port 8001

# Node server
cd src/backend/server && npx tsx src/index.ts        # dev
cd src/backend/server && npm run build && npm start  # prod

# Go binaries (build first)
cd src/backend/go-services && go build -o gateway ./cmd/gateway/main.go
cd src/backend/go-services && go build -o websocket ./cmd/websocket/main.go
PORT=8080 ./gateway
PORT=8081 ./websocket

# Frontend
cd src/frontend/web && npm run dev
```

## Testing

### Python
```bash
cd src/backend/python-legacy && python -m pytest tests/ -v
# or from root
npm run test:python
```

### Node.js
```bash
cd src/backend/server
npm test              # vitest run
npm run test:watch    # vitest
npm run test:coverage # vitest run --coverage
```

### TypeScript typecheck
```bash
npm run typecheck     # tsc --noEmit --project src/backend/server/tsconfig.json
```

### Integration / e2e shell tests
`tests/*.sh` at repo root (gateway, websocket, auth, xstate persistence). Most require the local stack to be running.

## Critical quirks & gotchas

1. **Python `sys.path` hacks** — Both `python-legacy` and `retrieval-service` hardcode `sys.path.insert(0, project_root)` in `main.py` and test files to enable relative imports. If you move files, these break.

2. **Node `.env` loading is custom** — `src/backend/server/src/index.ts` manually parses `../../../.env` with a hand-rolled parser (not `dotenv`). It only sets env vars that are **undefined** in `process.env`. If you need env vars loaded, ensure the server cwd is `src/backend/server` so the relative path resolves to repo root.

3. **Config loader (`config/loader.py`)** — The canonical Python config source. Loads `config/config.yaml` + `.env` + env vars (`RAG__SECTION__KEY` double-underscore nesting). Use `from config.loader import get_config, reload_config`.

4. **OCR service is NOT in root `pyproject.toml`** — It has its own `requirements.txt`. Install separately.

5. **Go services have no task runner scripts** — You must `go build` manually. No `go test` wrapper found at root.

6. **`packages/shared` must be built before Node server or web compile** — TS path mapping points to `packages/shared/dist`. If types are missing, run `tsc` in `packages/shared/` first.

7. **TEI (embedding inference) defaults to GPU** — `docker-compose.yml` reserves NVIDIA devices. CPU fallback requires changing `deploy.resources` or using local `sentence-transformers` (set `EMBEDDING_BACKEND=local`).

8. **XState v5 specifics** — Guards must be functions (`guard: ({ context }) => ...`), not strings. Actors must be `stop()`ped to avoid leaks. Every `invoke` needs an `onError` path. Do not use `interpret()`; use `createActor()`.

9. **Python style is enforced** — Black / Ruff line-length = 100, target py310. mypy `strict = true`. Run from root or `src/backend/python-legacy`.

10. **`.env` is gitignored and contains secrets** — Never commit it. Template is `config/.env.example`.

## Adding code

- **New Python adapter**: implement port in `domain/ports.py`, register in `container.py` (dependency-injector).
- **New FastAPI route**: add handler in `api/unified_api.py` or `api/routes.py`, models in `domain_models/`.
- **New Node module**: follow `src/backend/server/src/modules/<domain>/` pattern; re-export from `src/modules/<domain>/index.ts`.
- **New tool for RAG agent**: define in `src/modules/agent/src/tools.ts`, wire through `ToolBridge` in `src/modules/rag/tool-bridge.ts`.

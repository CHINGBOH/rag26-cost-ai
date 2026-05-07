# RAG Dashboard — GitHub Copilot Instructions

This file distills the repo-specific guidance that is currently spread across `README.md`, `AGENTS.md`, `.agent/rules/GEMINI.md`, `.aiassistant/rules/rules.md`, and the live runtime source. Prefer these instructions over generic monorepo assumptions.

## Monorepo at a glance

| Surface | Path | Default local port | Notes |
|---|---|---:|---|
| Frontend | `src/frontend/web/` | 3000 | React 18 + Vite |
| Node orchestrator/API | `src/backend/server/` | 3001 | Fastify + XState v5 |
| Go API gateway | `src/backend/go-services/` | 8080 | Reverse proxy for frontend-facing APIs |
| Go WebSocket gateway | `src/backend/go-services/` | 8081 | WebSocket broadcast layer |
| Python legacy API | `src/backend/python-legacy/` | 8000 | Embedding, documents, legacy ingestion |
| Retrieval service | `src/backend/retrieval-service/` | 8002 | Search, rerank, agent, learning APIs |
| OCR service | `src/backend/ocr-service/` | 8001 | Separate Python service with its own `requirements.txt` |
| Shared TS package | `packages/shared/` | — | Shared types consumed by web and Node |

Root `package.json` is an npm workspace for `packages/*`, `src/frontend/*`, `src/backend/server`, and `src/backend/ocr-service`.

## Build, test, and lint commands

### Start the local stack

```bash
./start-all.sh local
./stop-all.sh
```

Use `./start-all.sh docker` for the Docker-based stack. `npm run dev` only covers workspace dev scripts and does not start the Python or Go services.

### Build commands

```bash
# Shared package first when TypeScript builds need dist output
cd packages/shared && npm run build

# Node orchestrator
cd src/backend/server && npm run build

# Frontend
cd src/frontend/web && npm run build

# Go services
cd src/backend/go-services && go build ./...
```

### Test commands

```bash
# Root smoke suite (Node + python-legacy only)
npm test

# Node service tests
cd src/backend/server && npm test
cd src/backend/server && npx vitest run src/modules/auth/__tests__/auth.test.ts
cd src/backend/server && npx vitest run src/__tests__/Agent.test.ts -t "should"

# Python legacy tests
cd src/backend/python-legacy && python -m pytest tests/ -v
cd src/backend/python-legacy && python -m pytest tests/test_api.py -q

# Retrieval service tests
cd src/backend/retrieval-service && python -m pytest tests/test_learning_endpoints.py -q
cd src/backend/retrieval-service && python -m pytest tests/test_query_analyzer_routing.py -q

# Repo-root regression / integration tests
python tests/test_agent_16.py
python -m pytest tests/routing/test_issue96_routing.py -q

# Go tests
cd src/backend/go-services && go test ./...
cd src/backend/go-services && go test ./internal/gateway -run TestFindTargetServiceRoutesExecutorEndpointsToRetrieval -v
```

Most repo-root `tests/` cases assume the local stack is already running.

### Lint and type-check commands

There is no single monorepo `lint` script. Use the stack-native checks that already exist:

```bash
# TypeScript
npm run typecheck

# Python
ruff check src/backend/python-legacy src/backend/retrieval-service
black --check src/backend/python-legacy src/backend/retrieval-service
mypy src/backend/python-legacy

# Optional cross-language scan if qlty is installed
qlty check
```

## High-level architecture

### Request routing is split across Vite and the Go gateway

The frontend dev server in `src/frontend/web/vite.config.ts` does **not** send every request to the same backend:

- `/api/agent` → Node orchestrator (`:3001`)
- `/api/v1/*` → retrieval service (`:8002`) during dev
- `/api/*`, `/health`, `/metrics` → Go API gateway (`:8080`)
- `/ws` → Go WebSocket gateway (`:8081`)

The Go gateway in `src/backend/go-services/internal/gateway/proxy.go` applies **longest-prefix** matching. New frontend-reachable API prefixes must be registered in `getRouteMapping()` or the gateway returns 404.

### Service ownership is not intuitive

Do not assume all `/api/v1/*` routes belong to the same backend:

- **Retrieval service** owns `/api/search`, `/api/v1/search`, `/api/v1/rag`, `/api/v1/agent`, `/api/v1/learning`, `/api/v1/executor`, `/api/v1/architecture`, `/api/v1/tools`, `/api/v1/sandbox`, `/api/v1/evaluate`, `/api/v1/rerank`, and related retrieval/agent surfaces.
- **Python legacy** still owns `/api/v1/embedding`, `/api/v1/documents`, `/api/stats`, and `/api/v1/stats`.
- **Node orchestrator** owns `/api/sessions`, `/api/activity`, `/api/heartbeat`, `/api/auth`, `/api/pipeline`, `/api/cache`, `/api/queue`, `/api/system`, and `/api/agent`.

When routing is unclear, read `vite.config.ts` first, then `proxy.go`, then the target backend routes.

### Node is not the WebSocket server

The Node service emits events and uses `WebSocketManager` to forward them to the Go WebSocket gateway. If a real-time feature looks broken, inspect both the Node event emission path and the Go WebSocket process.

### `@rag/shared` is a real build dependency

`@rag/shared` comes from `packages/shared`. The frontend Vite config can fall back to `packages/shared/src/index.ts` during local dev, but Node and normal TypeScript builds still expect `packages/shared/dist`. Build `packages/shared` first when types look missing.

### Python and Node config entrypoints are different

- Python mutable runtime config should flow through `config/loader.py`, which layers defaults, YAML, `.env`, and environment variables such as `RAG__SECTION__KEY`.
- Node currently still has a legacy repo-root `.env` parser in `src/backend/server/src/index.ts` **before** telemetry initialization. Do not copy that pattern into new domains; prefer the domain's canonical config loader or mature config tooling, and call out this exact file whenever the legacy path still survives. Run Node commands from `src/backend/server` so the relative `.env` lookup still resolves correctly.

## Key conventions and non-obvious rules

- Do not move Python imports above `sys.path.insert(0, project_root)` in `python-legacy`; that bootstrap is required in multiple runtime files and tests.
- Use **Pydantic v2** for Python schema validation and **Zod** for TypeScript schema validation. Avoid bare `dict`, `object`, or `any` as business-layer interfaces.
- XState code is v5-only: use `createActor()`, write guards as functions, give invoked actors explicit `onError` handling, and stop spawned actors.
- Follow the config precedence chain everywhere: `default < config file < environment variable < command-line argument < runtime dynamic input`.
- Extend the existing config loader for a domain instead of adding another ad hoc `os.getenv`, scattered `process.env`, or custom parser path; prefer mature framework tooling when the stack already has it.
- Consult the project resource/capability index before introducing a new module, service, endpoint, job, or config surface; extend an existing owned surface when one already covers the need.
- Keep topology connected end-to-end: no black-hole routes, isolated files, dead parameters, or disconnected UI/API/job/test surfaces. If a value or route cannot be reached and exercised, finish the wiring or delete it.
- Prefer hard cutovers over keeping legacy dual-read or dual-write code alive. If an old path must survive, name both the canonical path and the exact surviving file or runtime edge.
- Behavior-changing operations should leave durable, timestamped traces in an existing audit surface such as structured logs, state tables, or event ledgers.
- Markdown-only rule changes are not enforcement when runtime/config behavior is in scope; executable config/runtime surfaces must carry the rule.
- `tests/test_agent_16.py` and `logs/agent_test_16_results.json` have a repo-specific audit rule: do not trust `passed`/confidence alone; inspect `answer_preview` for refusal phrases before claiming success.
- The OCR service is not covered by the root Python project metadata. If you touch OCR, check `src/backend/ocr-service/requirements.txt` separately.

# RAG Dashboard — GitHub Copilot Instructions

> Workspace-level instructions for GitHub Copilot Chat. Loaded automatically for all conversations in this repo.

## Project Context

Polyglot microservices RAG system ("四库" = Qdrant + PostgreSQL + Neo4j + Elasticsearch).

| Service | Path | Port | Language |
|---------|------|------|----------|
| Python Legacy | `src/backend/python-legacy/` | 8000 | FastAPI / Python 3.10 |
| Retrieval | `src/backend/retrieval-service/` | 8002 | FastAPI / Python 3.10 |
| Node Orchestrator | `src/backend/server/` | 3000 | Fastify + XState v5 |
| Go Gateway | `src/backend/go-services/` | 8080 | Gin |
| Frontend | `src/frontend/web/` | 5173 | React 18 + Vite |

## Agent System

Agent definitions live in `.agent/agents/`. Available agents:

| Agent | File | Use when |
|-------|------|----------|
| `@orchestrator` | `.agent/agents/orchestrator.md` | Multi-step planning, PDCA flow |
| `@engineer` | `.agent/agents/engineer.md` | Full-stack implementation |
| `@frontend-specialist` | `.agent/agents/frontend-specialist.md` | React / CSS / UI |
| `@backend-specialist` | `.agent/agents/backend-specialist.md` | Python / Go / Node APIs |
| `@qa-testing` | `.agent/agents/qa-testing.md` | Tests, coverage |
| `@security-review` | `.agent/agents/security-review.md` | OWASP audit |
| `@quality-inspector` | `.agent/agents/quality-inspector.md` | Code review, type safety |
| `@debugger` | `.agent/agents/debugger.md` | Bug diagnosis |
| `@ops-devops` | `.agent/agents/ops-devops.md` | Docker, CI/CD |
| `@project-planner` | `.agent/agents/project-planner.md` | PRD, task breakdown |

Activate the full system: read `.agent/rules/GEMINI.md`.

## Critical Routing Rules

1. `/api/search` → Go Gateway (8080) → Retrieval Service (8002) — **not** Python (8000)
2. New API paths must be registered in `proxy.go` `getRouteMapping()`
3. Frontend API calls route via Vite proxy → Go Gateway in dev
4. When routing is unclear: check `vite.config.ts` → `proxy.go` → backend routes

## Coding Standards

**Python**: Black + Ruff line-length=100, mypy strict, no SQL string concatenation  
**TypeScript**: No bare `any`, `tsc --noEmit` must pass  
**Go**: `go fmt`, `go build` must succeed  
**React**: Zustand (client state) + TanStack Query (server state)

## Common Pitfalls

- `sys.path.insert(0, project_root)` hacks in Python — do not move imports above them
- `packages/shared` must be built before compiling server or web
- Node `.env` loading is custom (not dotenv) — must run from `src/backend/server/`
- XState v5: use `createActor()` not `interpret()`, guards must be functions

## Workflows

| Command | File | Purpose |
|---------|------|---------|
| `/plan` | `.agent/workflows/plan.md` | Break down a task |
| `/create` | `.agent/workflows/create.md` | Implement a feature |
| `/debug` | `.agent/workflows/debug.md` | Systematic bug fix |
| `/test` | `.agent/workflows/test.md` | Write and run tests |
| `/status` | `.agent/workflows/status.md` | Check progress |
| `/security` | `.agent/workflows/security.md` | Security audit |

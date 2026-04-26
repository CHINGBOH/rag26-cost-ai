# AGENTS.md — RAG Dashboard

Compact reference for AI agents working in this repo. Every item below is something you would likely guess wrong or waste time discovering.

---

## ⚠️ HOOD AGENT — 强制审计规则（禁止绕过）

**触发条件**：任何时候 AI Agent 说出以下词语时，必须立即执行审计，不得直接向用户汇报结果：
- "测试通过"、"passed"、"16/16"、"命中率"、"✅"（在测试报告语境中）、"100%"、"全部通过"

**审计步骤（必须全部执行）**：
1. 打开 `logs/agent_test_16_results.json`，读取每题的 `answer_preview`
2. 检查每题是否包含**拒绝回答模式**（见下方列表）
3. 统计真实通过数，若与 `passed` 字段不符，**必须纠正并告知用户**

**拒绝回答模式**（answer 包含以下任意词 → 该题实际 FAIL，不管 passed=True）：
```
无法直接回答 | 无法回答 | 无法提供 | 无法分析 | 无法对比 | 无法计算
不足以回答   | 未提供   | 均显示为N/A | 无相关数据 | 未包含
```

**规则**：`passed = has_chunks AND confidence > 0.4` 是错误的判定标准。
- chunks > 0 只说明检索到了文本，不代表能回答问题
- confidence 由 LLM 自评，LLM 在无法回答时仍会给出高置信度
- **真正的 passed = answer 包含正确答案关键词，且不包含拒绝回答模式**

**违规惩罚**：如果 AI Agent 在未执行上述审计的情况下声称"测试通过"，视为严重误导用户，必须在下一条消息中主动纠正。

---

> **Agent behavior guidelines** (derived from [Karpathy's observations](docs/reference/andrej-karpathy-skills/README.zh.md) on LLM coding pitfalls):
>
> 1. **Think Before Coding** — State assumptions explicitly. If uncertain about requirements or architecture, ask rather than guess. Present tradeoffs when multiple approaches exist.
> 2. **Simplicity First** — Minimum code that solves the problem. No speculative abstractions. No "flexibility" that wasn't requested. If 200 lines could be 50, rewrite it.
> 3. **Surgical Changes** — Touch only what you must. Don't refactor adjacent code, comments, or formatting. Match existing style. Remove only imports/variables that YOUR changes made unused.
> 4. **Goal-Driven Execution** — Transform tasks into verifiable goals. "Fix the bug" → "Write a reproducer test, then make it pass." "Refactor X" → "Ensure tests pass before and after." State a brief plan with verification steps for multi-step tasks.
>
> **Project-specific note:** This repo has severe `sys.path` hacks, custom `.env` loading, hardcoded proxy rules, and a Go Gateway that frontend may bypass. When in doubt about service boundaries or API routing, check `vite.config.ts` against `proxy.go` **before** implementing.

## Agent behavior guidelines (Karpathy-inspired)

Behavioral rules to reduce costly mistakes in this complex polyglot repo. Bias toward caution over speed.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

This repo has four backends (Python legacy, Retrieval, Node orchestrator, Go Gateway) and a React frontend. A common mistake is assuming which backend handles a given API endpoint.

**Examples of wrong assumptions to avoid:**
- "Search API must be in Python" → No, `/api/search` is routed by Go Gateway to `retrieval-service` (`:8002`), not Python legacy (`:8000`).
- "WebSocket must be in Node.js" → No, Node.js forwards events via HTTP POST to the Go WebSocket gateway (`:8081`).
- "I'll add a new API route in Node.js" → Check `proxy.go` first. If Gateway doesn't have the prefix, the frontend can't reach it.

**When confused about service boundaries:**
1. Check `vite.config.ts` proxy rules
2. Check `proxy.go` `getRouteMapping()`
3. Check the target backend's route definitions
4. If still unclear, ask — don't guess.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

This repo already suffers from over-engineering (recursive config validators, XState v5 machines, four-database retrieval). Resist adding more.

**Examples:**
- Don't wrap a single `fetch` call in a new service class.
- Don't add a new config layer when a constant suffices.
- Don't create a shared utility for code used in exactly one place.
- If a PR changes 20 files for a 3-line fix, you've overcomplicated it.

**The test:** Would a senior engineer say "why not just...?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style — Black line-length 100, Go fmt, existing naming conventions.
- If you notice unrelated dead code, mention it in the PR description — don't delete it in the same commit.

**When your changes create orphans:**
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

**Every changed line should trace directly to the user's request.**

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform imperative tasks into verifiable goals:

| Instead of... | Transform to... |
|---------------|-----------------|
| "Fix the search API" | "Write a curl test for `/api/search`, verify it returns 200 with results, then fix the handler" |
| "Refactor the Gateway" | "Ensure `go build` passes and all frontend API paths still route correctly" |
| "Add a new feature" | "Add tests → verify tests fail → implement → verify tests pass → run typecheck → verify no circular deps" |

**For multi-step tasks, state a brief plan:**
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## LangGraph-style runtime / channel / state guidance

- Treat the agent as a stateful runtime loop, not a stateless one-shot pipeline.
- `Runtime` is the loop engine: observe the latest channel state, ask the LLM what to do, execute the selected tool/action, write results back, then repeat.
- `Channel` is the shared state container or blackboard. In LangGraph it corresponds to typed `State`/`Channel` values with versioned snapshots. In this repo, it maps to XState `context` plus tool outputs and RAG metadata.
- `State` is the typed payload inside the channel: question, rewritten query, documents, answer, iteration count, tool results, etc.
- `Version` is the state update sequence or vector clock. Use it to detect loops, support recovery, and keep concurrent writes consistent.

**Mapping to this repo:**
- LangGraph `State` ≈ XState `context`
- LangGraph `Channel` ≈ the shared runtime state/blackboard used by the agent
- LangGraph `Node`/`Reducer` ≈ action/tool invocation logic
- LangGraph `Checkpoint` ≈ persisted state snapshot / recovery point
- LLM is the decision-maker inside the runtime loop, choosing between `CALL_TOOL` and `FINAL_ANSWER` and writing intent back into the channel.

When comparing existing code, prefer this LangGraph-style mental model over a naive prompt-chain view.

---

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

## Architecture analysis tools

When investigating frontend-backend integration issues, use these tools:

| Tool | Command | Purpose |
|---|---|---|
| Dependency Cruiser | `depcruise --no-config --include-only "^src" --output-type json src` | Visualize module dependencies, detect circular imports |
| Madge | `madge --extensions ts,tsx --circular src` | Detect circular dependencies in TS/JS projects |
| Madge (image) | `madge --extensions ts,tsx --image deps.svg src` | Generate dependency graph (requires Graphviz) |
| Mermaid CLI | `mmdc -i diagram.mmd -o diagram.svg` | Generate architecture diagrams from Mermaid syntax |

**Typical analysis workflow:**
```bash
# 1. Check circular dependencies
cd src/frontend/web && npx madge --extensions ts,tsx --circular src
cd src/backend/server && npx madge --extensions ts --circular src

# 2. Analyze API proxy alignment
# Compare vite.config.ts proxy rules with Go Gateway proxy.go route mappings
# Ensure all frontend API paths have corresponding Gateway mappings

# 3. Generate architecture diagram
cat > arch.mmd << 'EOF'
graph TB
    FE[Frontend] --> GW[Go Gateway]
    GW --> SVC[Services]
EOF
npx mmdc -i arch.mmd -o arch.png
```

**Known integration pitfalls:**
- `vite.config.ts` proxy rules may bypass Go Gateway for `/api/search` and `/api/v1` — always route through Gateway in production.
- `@rag/shared` path alias points to `packages/shared/dist/` which must be built first (`tsc` in `packages/shared/`).
- Go Gateway `proxy.go` `getRouteMapping()` must include every frontend API prefix, or requests 404.

## Code quality scanning tools

For automated code quality checks across the polyglot codebase:

| Tool | Scope | Command | Notes |
|---|---|---|---|
| **Qlty** | All | `qlty check` | Runs 12+ plugins (ruff, bandit, shellcheck, gofmt, etc.) |
| **SonarScanner** | All | `sonar-scanner` | Requires SonarQube server; not runnable standalone |
| **ruff** | Python | `ruff check src/backend/python-legacy/` | Fast Python linter; already in project |
| **mypy** | Python | `mypy src/backend/python-legacy/` | Type checker; strict mode enabled |
| **golangci-lint** | Go | `golangci-lint run ./...` | Requires Go 1.26+; may crash on older versions |
| **tsc** | TypeScript | `tsc --noEmit` | Type check frontend and Node backend |

**Qlty setup:**
```bash
# Install (one-time)
curl https://qlty.sh | sh
export PATH="$HOME/.qlty/bin:$PATH"

# Initialize (generates .qlty/qlty.toml)
qlty init

# Check all files
qlty check

# Check specific files
qlty check src/backend/go-services/internal/gateway/proxy.go
```

**Known quality issues (by design, do not "fix"):**
- `E402` in Python files — caused by `sys.path.insert(0, project_root)` hack (see quirk #1 above). Moving imports above the sys.path hack would break the imports.
- `mypy` duplicate module errors — caused by `types/retrieval.py` coexisting with `retrieval/__init__.py`. This is a legacy structural issue.

## Architecture principles (from `.kimi/rules.md`)

This repo has a formal architecture specification at `.kimi/rules.md` (concepts) and `.kimi/rules.impl.md` (toolchain mappings). Below is the condensed version agents must know:

### The 6 principles

| # | Principle | What it means for this repo |
|---|-----------|----------------------------|
| 1 | **Type Safety** | All business data must have type definitions. No bare `any` / `object` / `dict`. Prefer deriving types from validation Schema (Zod `z.infer`, Pydantic model). |
| 2 | **Validation First** | Env vars, configs, and API inputs are validated at startup. If something can be wrong, it will be wrong — catch it early. |
| 3 | **Loose Coupling** | Business logic (Application Layer) must **not** import frameworks (FastAPI/Express) or infrastructure (SQLAlchemy/Prisma). Use constructor injection and ports/adapters. |
| 4 | **Recursive Validation** | Config validates config. `rulesConfig` in `config/index.ts` validates its own structure. Meta-rules apply to themselves. |
| 5 | **Precision First** | Never use `float`/`number` for money or scientific calculations. Use `Decimal` (Python) or `decimal.js` (JS). |
| 6 | **Explicit Errors** | Prefer `Result<T, E>` types over throwing exceptions. Callers must handle errors explicitly. See `neverthrow` (TS) and `returns` (Python). |

### Code review checklist

Apply this before marking any task complete:

- [ ] **Type Safety** — All data has types, no bare `any`/`object`/`dict`
- [ ] **Validation First** — Env vars, configs, API inputs/outputs validated
- [ ] **Loose Coupling** — Business logic doesn't import frameworks or infrastructure
- [ ] **Recursive Validation** — Config system has meta-validation
- [ ] **Precision First** — Money uses Decimal, not float/number
- [ ] **Explicit Errors** — Result types instead of exceptions where possible
- [ ] **Single Source of Truth** — Types and validation Schema not duplicated
- [ ] **Test Isolation** — Unit tests have zero external dependencies (no real DB/HTTP)
- [ ] **Surgical Changes** — Every changed line traces to the user's request
- [ ] **Goal Verification** — Tests/typecheck/lint pass before declaring done

### Toolchain mappings

| Concept | TypeScript | Python | File |
|---------|------------|--------|------|
| Runtime validation | Zod | Pydantic v2 | `.kimi/rules.impl.md` |
| DI container | TSyringe | dependency-injector | `.kimi/rules.impl.md` |
| Error handling | neverthrow | returns | `.kimi/rules.impl.md` |
| Precision calc | decimal.js | Decimal | `.kimi/rules.impl.md` |

## Adding code

- **New Python adapter**: implement port in `domain/ports.py`, register in `container.py` (dependency-injector).
- **New FastAPI route**: add handler in `api/unified_api.py` or `api/routes.py`, models in `domain_models/`.
- **New Node module**: follow `src/backend/server/src/modules/<domain>/` pattern; re-export from `src/modules/<domain>/index.ts`.
- **New tool for RAG agent**: define in `src/modules/agent/src/tools.ts`, wire through `ToolBridge` in `src/modules/rag/tool-bridge.ts`.

<!-- markdownlint-disable-file -->

# Task Details: Canonical Event Ledger Learning Architecture

## Research Reference

**Source Research**: #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md

## Phase 1: Canonical Schema and Projection Foundations

### Task 1.1: Create the canonical event ledger schema and explicit outcome taxonomy

Define the append-only `event_ledger` migration, add the initial outcome taxonomy contract, and introduce version/idempotency fields so sync, stream, feedback, learning-loop, and executor paths can converge on one fact model.

- **Files**:
  - `sql/migrations/20260506_event_ledger_phase1.sql` - create `event_ledger` with canonical metadata, idempotency, and version fields
  - `src/backend/retrieval-service/app/agent/event_taxonomy.py` - define `outcome_family`, `outcome_code`, `quality`, and `learning_eligible` semantics
  - `src/backend/retrieval-service/app/agent/event_builders.py` - normalize event payload shapes for interaction runs, learning runs, gaps, and improvement events
- **Success**:
  - every interaction path has a schema target that can emit exactly one terminal event per `run_id`
  - the taxonomy explicitly separates `system_failure`, `semantic_failure`, and `non_task`
- **Research References**:
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 9-145) - verified split-brain runtime evidence that requires a canonical event contract
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 278-344) - canonical schema, taxonomy, and invariant specification
  - #fetch:https://fastapi.tiangolo.com/advanced/events/ - service lifecycle ownership pattern reused from validated prior research
- **Dependencies**:
  - database migration path for retrieval-service
  - agreement on canonical outcome taxonomy before projector work begins

### Task 1.2: Add rebuildable projections, invariants, and reconcile scaffolding

Create projection tables and projector scaffolding so `conversation_turns`, `agent_run_projection`, and unified learning-run views become derived read models instead of independent sources of truth.

- **Files**:
  - `sql/migrations/20260506_event_projections_phase1.sql` - create `agent_run_projection` and extend `conversation_turns` projection columns
  - `src/backend/retrieval-service/app/agent/projections/conversation_turns_projection.py` - projection writer for user-visible turn history
  - `src/backend/retrieval-service/app/agent/projections/agent_run_projection.py` - projection writer for interaction-run operational reads
  - `src/backend/retrieval-service/app/agent/projections/rebuild.py` - full rebuild, single-run replay, and reconcile entry points
- **Success**:
  - projections can be rebuilt from `event_ledger` without depending on JSONL or route-local inserts
  - invariants for terminal events, traceability, and rebuildability are encoded in projector logic and validation helpers
- **Research References**:
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 224-277) - projection-first patterns derived from verified evidence
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 278-344) - projection requirements and system invariants
- **Dependencies**:
  - Task 1.1 completion
  - PostgreSQL JSONB and migration support already used in the repo

## Phase 2: Unified Interaction Run Writes and Read Surfaces

### Task 2.1: Route sync, stream, and early-exit flows through one terminal event writer

Introduce shared run context and terminal write helpers so sync `/api/v1/agent`, stream `/api/v1/agent/stream`, and graph early exits all emit one canonical terminal event with the same schema.

- **Files**:
  - `src/backend/retrieval-service/app/api.py` - generate `run_id`, invoke canonical write path for sync and stream terminal completion
  - `src/backend/retrieval-service/app/agent/graph.py` - attach outcome hints for early exits and retire synthesize-only JSONL semantics
  - `src/backend/retrieval-service/app/agent/run_context.py` - standardize per-request run metadata shared across sync/stream paths
  - `src/backend/retrieval-service/app/agent/outcome_classifier.py` - broaden refusal and semantic-failure classification
- **Success**:
  - sync, stream, and early-exit runs produce the same terminal contract and are all visible to learning
  - refusal-like phrases such as `无法直接计算` and `无法给出` no longer silently downgrade to good/weak outcomes
- **Research References**:
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 9-145) - verified sync/stream split, early-exit invisibility, and weak refusal markers
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 224-277) - one-terminal-event pattern for every `run_id`
  - #githubRepo:"tiangolo/fastapi lifespan" - runtime ownership precedent for a centralized request completion path
- **Dependencies**:
  - Phase 1 completion
  - no API contract changes should break current Go gateway passthrough

### Task 2.2: Replace JSONL-based interaction run reads with projection-backed APIs

Move `learning/runs` and related interaction-run surfaces off `agent_runs.jsonl` and onto projection-backed database reads while preserving temporary compatibility during cutover.

- **Files**:
  - `src/backend/retrieval-service/app/api.py` - replace JSONL run reads with `agent_run_projection` queries and expose `interaction|learning_loop|all` view modes
  - `src/backend/retrieval-service/app/agent/projections/learning_runs_view.py` - build unified run view helpers without merging underlying storage semantics
  - `src/backend/retrieval-service/app/agent/graph.py` - downgrade `_log_agent_run()` to compatibility-only during dual-write
- **Success**:
  - `/api/v1/learning/runs` no longer treats JSONL as the primary business read surface
  - interaction runs and scheduler/manual learning-loop runs can be displayed together without sharing storage semantics
- **Research References**:
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 9-145) - verified JSONL vs DB split in current run surfaces
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 224-277) - projection-backed consumer pattern
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 345-404) - cutover order and file-level implementation guidance
- **Dependencies**:
  - Task 2.1 completion
  - projection tables from Phase 1 available

## Phase 3: Learning Consumer Cutover and Lifecycle Correctness

### Task 3.1: Repoint failure monitoring, signal collection, and learning-run emission to canonical projections

Change learning consumers so failure-rate triggers, signal aggregation, and scheduler/executor lifecycle emission read and write through the new canonical event and projection model instead of route-local stores.

- **Files**:
  - `src/backend/retrieval-service/app/agent/failure_monitor.py` - compute rates from `agent_run_projection` and ignore `non_task`
  - `src/backend/retrieval-service/app/agent/signal_collector.py` - collect semantic and system failures from canonical projections
  - `src/backend/retrieval-service/app/agent/scheduler.py` - emit canonical learning-run events in addition to durable run projections
  - `src/backend/retrieval-service/app/agent/executor.py` - emit improvement verification events that can drive gap lifecycle transitions
- **Success**:
  - sync-origin semantic failures contribute to the learning trigger path after cutover
  - scheduler/manual learning runs remain durable while their event emission becomes consistent with the rest of the architecture
- **Research References**:
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 9-145) - verified `conversation_turns` coupling in monitor and collector plus durable DB scheduler writes
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 278-344) - invariant and projection requirements for learning consumers
  - #fetch:https://apscheduler.readthedocs.io/en/3.x/modules/schedulers/asyncio.html - existing async scheduler lifecycle pattern reused from validated prior research
- **Dependencies**:
  - Phase 2 completion
  - taxonomy and projections finalized enough for learning consumers to rely on them

### Task 3.2: Extend gap lifecycle with observing and controlled reopen semantics

Introduce `observing` as the post-verification buffer state, tighten reopen rules around fresh eligible signals, and expose the corrected lifecycle consistently through learning APIs and UI surfaces.

- **Files**:
  - `sql/migrations/20260506_gap_observing_state.sql` - extend `knowledge_gaps` lifecycle columns and states
  - `src/backend/retrieval-service/app/agent/learning_state.py` - encode `verified -> observing -> resolved` plus fresh-signal reopen rules
  - `src/backend/retrieval-service/app/agent/executor.py` - move successful verification into `observing` instead of immediate `resolved`
  - `src/backend/retrieval-service/app/api.py` - expose corrected gap lifecycle and run semantics in learning endpoints
  - `src/frontend/web/src/pages/LearningPage.tsx` - show interaction runs, learning loop runs, improvement events, and gap lifecycle separately
  - `src/frontend/web/src/services/metricsApi.ts` - align API client with projection-backed run and gap reads
- **Success**:
  - a verified improvement does not immediately close its gap
  - reopen only occurs from new eligible signals after verification, not stale historical rows alone
- **Research References**:
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 9-145) - verified current gap status set and reopen behavior without observing state
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 224-277) - corrected `verified -> observing -> resolved` lifecycle pattern
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 345-404) - file-level guidance for learning state, executor, and frontend split
- **Dependencies**:
  - Task 3.1 completion
  - frontend read-path update depends on new API semantics stabilizing

## Phase 4: Migration Safety and Acceptance Verification

### Task 4.1: Implement dual-write, shadow-read, cutover, and rollback controls

Plan and scaffold a safe migration path so the system can compare canonical projections against legacy stores before fully cutting the learning surfaces over.

- **Files**:
  - `src/backend/retrieval-service/app/agent/event_ledger.py` - idempotent write façade with compatibility toggles for dual-write
  - `src/backend/retrieval-service/app/agent/projections/rebuild.py` - reconcile and drift detection utilities used during shadow-read
  - `src/backend/retrieval-service/app/api.py` - cutover flags or routing hooks for old/new read paths
  - `.copilot-tracking/changes/20260506-canonical-event-ledger-learning-architecture-changes.md` - implementation log and migration checkpoints during execution
- **Success**:
  - legacy JSONL and route-local writes can remain temporarily while canonical projections are validated
  - rollback preserves event facts even if UI or consumer reads return to legacy mode briefly
- **Research References**:
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 224-277) - dual-write and shadow-read migration pattern from verified repo constraints
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 405-412) - additive migration and cutover constraints
- **Dependencies**:
  - Phase 3 completion
  - operational agreement on cutover checkpoints and rollback triggers

### Task 4.2: Add invariant, rebuild, and end-to-end acceptance tests

Build the verification suite that proves the new architecture is internally consistent and user-visible behavior remains correct under real interaction paths.

- **Files**:
  - `src/backend/retrieval-service/tests/test_event_ledger_sync_agent.py` - sync path canonical event and projection coverage
  - `src/backend/retrieval-service/tests/test_event_ledger_stream_agent.py` - stream path canonical event and projection coverage
  - `src/backend/retrieval-service/tests/test_agent_early_exit_projection.py` - non-task and early-exit visibility checks
  - `src/backend/retrieval-service/tests/test_outcome_classifier.py` - refusal, semantic failure, and non-task classification checks
  - `src/backend/retrieval-service/tests/test_learning_runs_unified_api.py` - unified run surface verification
  - `src/backend/retrieval-service/tests/test_gap_observing_reopen.py` - observing and reopen lifecycle verification
- **Success**:
  - the invariant suite proves one terminal event per `run_id`, rebuildable projections, and correct non-task exclusion from failure rate
  - end-to-end acceptance covers sync, stream, early-exit, gap verification, observing, and reopen paths
- **Research References**:
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 278-344) - system invariants and projection rebuild requirements
  - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md (Lines 345-404) - acceptance and testing guidance based on verified evidence
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 176-182) - audited validation remains a required acceptance input
- **Dependencies**:
  - Task 4.1 completion
  - existing retrieval-service test harness and audited validation flow remain available

## Dependencies

- PostgreSQL migrations and JSONB-backed projection storage
- Existing FastAPI lifespan wiring in retrieval-service main process
- Existing APScheduler-based learning trigger ownership
- Frontend learning page and API client surfaces under `src/frontend/web`

## Success Criteria

- one canonical event model exists for interaction runs, learning runs, gaps, and improvement lifecycle transitions
- sync, stream, and early-exit traffic all produce one terminal event per `run_id`
- failure monitoring and signal collection no longer depend on route-local persistence gaps
- `/api/v1/learning/runs` is projection-backed instead of JSONL-backed
- gap closure uses `observing` before `resolved`, with controlled reopen from fresh eligible signals
- rollout can proceed with dual-write, shadow-read, cutover, and rollback checkpoints

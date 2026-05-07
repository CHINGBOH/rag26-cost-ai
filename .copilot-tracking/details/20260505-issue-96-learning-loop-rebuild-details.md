<!-- markdownlint-disable-file -->

# Task Details: Issue #96 Learning Loop Rebuild

## Research Reference

**Source Research**: #file:../research/20260505-issue-96-learning-loop-rebuild-research.md

## Phase 1: Backend Consolidation

### Task 1.1: Remove duplicate learning route implementations and define a single authoritative API surface

Consolidate learning route definitions in `src/backend/retrieval-service/app/api.py` so each learning endpoint path is defined exactly once. Keep the implementation variant that is aligned with scheduler/monitor/analyzer integration, and remove or merge stubbed/legacy variants that only return queued or static state.

- **Files**:
  - `src/backend/retrieval-service/app/api.py` - remove duplicate `trigger` and `status` routes, preserve one authoritative implementation set
  - `src/backend/retrieval-service/tests/test_learning_endpoints.py` - verify the retained endpoint set still matches exposed routes
- **Success**:
  - `POST /api/v1/learning/trigger` is defined once
  - `GET /api/v1/learning/status` is defined once
  - Learning endpoint inventory remains complete for signals, problems, strategies, history, stats, and dashboard
- **Research References**:
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 11-13) - repository route analysis verified duplicated learning endpoints
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 84-91) - duplicate route definitions identified as the primary architectural blocker
- **Dependencies**:
  - Existing research validation complete
  - No frontend semantic fixes should start until this route inventory is stable

### Task 1.2: Unify learning status computation behind a single backend status source

Refactor backend learning status calculation so `status`, `dashboard`, `history`, and review counts read from one shared status source rather than independently computed values. The unified state should expose engine status, current/last run, pending reviews, active problems, health score, and recent events.

- **Files**:
  - `src/backend/retrieval-service/app/api.py` - centralize status assembly used by multiple learning endpoints
  - `src/backend/retrieval-service/app/agent/executor.py` - expose verified execution state needed by status and history views
- **Success**:
  - `status` and `dashboard` no longer report conflicting pending approval values
  - Review/history/dashboard panels can consume a single consistent backend state model
- **Research References**:
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 23-25) - live endpoint verification proved conflicting runtime state
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 104-110) - status inconsistency blocks reliable frontend behavior
- **Dependencies**:
  - Task 1.1 completion
  - Existing execution and event records remain available for aggregation

### Task 1.3: Wire scheduler, failure monitor, and feedback analyzer into service startup/shutdown lifecycle

Initialize scheduler and monitor components once during retrieval-service startup, shut them down cleanly during service teardown, and make their accessors (`get_scheduler`, `get_failure_monitor`, `get_feedback_analyzer`) available at module scope for both runtime use and test patching.

- **Files**:
  - `src/backend/retrieval-service/main.py` - attach learning runtime initialization to FastAPI lifespan/startup
  - `src/backend/retrieval-service/app/agent/scheduler.py` - ensure scheduler init/shutdown hooks are stable
  - `src/backend/retrieval-service/app/agent/failure_monitor.py` - ensure lifecycle-safe singleton or shared instance exposure
  - `src/backend/retrieval-service/app/agent/feedback_analyzer.py` - ensure lifecycle-safe singleton or shared instance exposure
  - `src/backend/retrieval-service/app/api.py` - import accessor functions at module scope for patchable/testable use
- **Success**:
  - Startup creates real scheduler/monitor/analyzer instances
  - Shutdown stops background scheduler cleanly
  - Tests can patch `app.api.get_scheduler`, `app.api.get_failure_monitor`, and `app.api.get_feedback_analyzer`
- **Research References**:
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 29-31) - failing tests prove lifecycle and import exposure are incomplete
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 35-36, 118-124) - FastAPI lifespan and APScheduler lifecycle patterns validate startup/shutdown integration
- **Dependencies**:
  - Task 1.1 completion
  - FastAPI application lifecycle integration point available in `main.py`

## Phase 2: Closed-Loop Execution Core

### Task 2.1: Normalize signal aggregation into consistent problem reports and root-cause analysis inputs

Ensure learning signals are transformed into a stable `ProblemReport`-style structure before reaching root-cause analysis and strategy generation. This should consolidate failures, feedback, repeats, violations, and topology anomalies into one problem inventory with evidence and severity.

- **Files**:
  - `src/backend/retrieval-service/app/agent/signal_collector.py` - normalize aggregated signal output structure
  - `src/backend/retrieval-service/app/agent/problem_detector.py` - emit stable problem objects with evidence and severity
  - `src/backend/retrieval-service/app/agent/root_cause_analyzer.py` - accept normalized problem objects and produce evidence-backed root causes
  - `src/backend/retrieval-service/app/api.py` - ensure `/learning/problems` and `/learning/analyze-problem` expose real detector/analyzer output
- **Success**:
  - `/api/v1/learning/problems` returns real detector output, not placeholder data
  - `/api/v1/learning/analyze-problem` returns actionable root cause analysis with evidence groupings
- **Research References**:
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 42-59) - project structure confirms signal/problem/analyzer modules already exist
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 159-169) - recommended planning direction requires signals -> problems -> root cause as the first closed-loop path
- **Dependencies**:
  - Phase 1 completion
  - Unified backend state available for problem counts and health updates

### Task 2.2: Formalize strategy generation and low-risk executor verification/rollback flow

Generate strategies using explicit risk-based decision buckets (`auto_apply`, `pending_review`, `manual_only`) and connect low-risk strategies to a real executor path that records before/after metrics, verifies outcome, and reverts failed changes.

- **Files**:
  - `src/backend/retrieval-service/app/api.py` - expose strategy and approval endpoints against the real strategy/executor stack
  - `src/backend/retrieval-service/app/agent/executor.py` - implement apply, verify, and revert transitions with durable event recording
  - `src/backend/server/src/modules/learning/strategy-generator.ts` or corresponding backend strategy logic - normalize strategy risk/decision output
- **Success**:
  - Strategies are categorized into executable vs review/manual buckets
  - Executor records before/after metrics and final status (`verified`, `reverted`, `failed`)
  - Low-risk strategies can complete a full apply -> verify -> revert|verified path
- **Research References**:
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 144-153) - verified pattern keeps low-risk automation as the safe initial execution scope
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 176-182) - implementation guidance requires closed-loop execution before UI cleanup
- **Dependencies**:
  - Task 2.1 completion
  - Unified status/event source from Phase 1

### Task 2.3: Align reviews and history semantics with true learning lifecycle states

Separate pending review records from applied/verified/reverted/failed execution history. Reviews must only show `pending_review` items, while history must display executed lifecycle outcomes with verification evidence.

- **Files**:
  - `src/frontend/web/src/pages/LearningPage.tsx` - stop filtering applied events into the reviews tab
  - `src/frontend/web/src/components/learning/ReviewsPanel.tsx` - consume real pending review queue data
  - `src/frontend/web/src/components/learning/ImprovementHistoryPanel.tsx` - display executed outcomes and verification/rollback evidence
  - `src/backend/retrieval-service/app/api.py` - expose separate review queue and historical execution state
- **Success**:
  - Reviews tab shows only true pending review items
  - History tab shows applied/verified/reverted/failed outcomes with before/after evidence
- **Research References**:
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 17-19) - frontend review/history semantics are currently incorrect
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 137-142) - verified pattern requires strict separation between review queue and history
- **Dependencies**:
  - Task 2.2 completion
  - Pending review and historical statuses available from backend

## Phase 3: Automation, Dashboard, and Audited Validation

### Task 3.1: Rebuild dashboard as the unified learning system control plane

Refactor dashboard data and UI so it reflects real engine status, trigger sources, active problems, pending reviews, execution outcomes, and learning benefit metrics from the unified backend status model.

- **Files**:
  - `src/frontend/web/src/components/learning/DashboardPanel.tsx` - render unified control-plane metrics instead of isolated dashboard-only values
  - `src/frontend/web/src/pages/LearningPage.tsx` - keep tab order and descriptions aligned with the real learning lifecycle
  - `src/backend/retrieval-service/app/api.py` - provide unified dashboard payload built from the same status source as reviews/history/status
- **Success**:
  - Dashboard shows one consistent engine state
  - Trigger source, pending reviews, active problems, rollback counts, and recent events all reflect unified backend status
- **Research References**:
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 104-110) - dashboard/status divergence must be eliminated
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 176-182) - dashboard work belongs after backend and execution semantics are corrected
- **Dependencies**:
  - Phase 1 and Phase 2 completion
  - Unified status source and review/history semantics already stable

### Task 3.2: Enable cron/failure/feedback triggers with debounce and idempotency controls

Turn the learning engine from manual-only into a controlled multi-trigger system. Add cron scheduling, failure-threshold activation, and feedback-trend activation, while preventing duplicate trigger storms or overlapping runs.

- **Files**:
  - `src/backend/retrieval-service/app/agent/scheduler.py` - own cron registration and run coordination
  - `src/backend/retrieval-service/app/agent/failure_monitor.py` - emit bounded failure-trigger events
  - `src/backend/retrieval-service/app/agent/feedback_analyzer.py` - emit bounded feedback-trigger events
  - `src/backend/retrieval-service/app/api.py` - surface trigger source state and next-run timing in engine/dashboard endpoints
- **Success**:
  - Engine no longer reports manual-only mode once flags/triggers are enabled
  - Cron/failure/feedback triggers respect cooldown/debounce/idempotency constraints
  - Overlapping runs are prevented or explicitly serialized
- **Research References**:
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 23-25, 93-102) - live engine currently marks automation inactive
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 35-36, 118-124) - FastAPI lifespan + APScheduler validate this integration path
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 170-174, 176-182) - automation is Phase 3 after backend consolidation and execution safety
- **Dependencies**:
  - Phase 1 completion
  - Phase 2 verification/rollback path available to support safe automated execution

### Task 3.3: Integrate audited gold-test validation as a formal learning acceptance signal

Use audited gold-test results, not raw `passed/confidence` values, as one of the official verification inputs for learning improvements. Surface audited pass counts and refusal-like answer detection in status, history, and dashboard acceptance metrics.

- **Files**:
  - `logs/agent_test_16_results.json` access/analysis path - audited gold result source
  - `src/backend/retrieval-service/app/api.py` - expose audited metrics to learning status/dashboard/history
  - `src/backend/retrieval-service/app/agent/executor.py` - store verification basis using audited results where applicable
- **Success**:
  - Dashboard/history can distinguish raw pass counts from audited pass counts
  - Refusal-like answer detection is part of formal learning verification
- **Research References**:
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 170-174, 176-182) - audited gold validation is required before calling the system complete
  - #file:../research/20260505-issue-96-learning-loop-rebuild-research.md (Lines 176-182) - implementation guidance explicitly treats audited gold results as a separate acceptance signal
- **Dependencies**:
  - Phase 2 verification flow completion
  - Phase 3 dashboard/status redesign in place to display audited metrics

## Dependencies

- FastAPI lifespan-managed application lifecycle
- APScheduler `AsyncIOScheduler`
- Existing retrieval-service learning modules and test suite
- Audited gold-test artifact availability in `logs/agent_test_16_results.json`

## Success Criteria

- Learning API has one authoritative backend implementation surface
- Scheduler/monitor/analyzer are initialized and patchable in runtime/tests
- Problems, strategies, reviews, history, and dashboard all consume consistent backend state
- Low-risk strategies can execute with verification and rollback
- Automation and audited validation are designed as system-level capabilities rather than UI-only features

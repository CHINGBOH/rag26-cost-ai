---
applyTo: ".copilot-tracking/changes/20260506-canonical-event-ledger-learning-architecture-changes.md"
---

<!-- markdownlint-disable-file -->

# Task Checklist: Canonical Event Ledger Learning Architecture

## Overview

Create a canonical event-ledger-based learning architecture plan that unifies interaction run facts, projection-backed reads, and gap lifecycle closure semantics for Issue #96 follow-on work.

## Objectives

- Establish one append-only event model and projection strategy that removes the current sync/stream/JSONL/DB split-brain behavior.
- Deliver an implementation-ready phased plan that preserves current repo boundaries while enabling correct learning triggers, unified run surfaces, and safe migration.

## Research Summary

### Project Files

- `src/backend/retrieval-service/app/api.py` - current sync/stream split, `learning/runs` JSONL read path, and primary canonical writer integration point.
- `src/backend/retrieval-service/app/agent/graph.py` - early-exit handling, synthesize-only run logging, and refusal classification bottleneck.
- `src/backend/retrieval-service/app/agent/failure_monitor.py` - current trigger-rate dependency on `conversation_turns`.
- `src/backend/retrieval-service/app/agent/signal_collector.py` - current failure aggregation dependency on `conversation_turns`.
- `src/backend/retrieval-service/app/agent/scheduler.py` - existing durable learning-loop run writer.
- `src/backend/retrieval-service/app/agent/learning_state.py` - current gap status and reopen semantics.

### External References

- #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md - verified runtime evidence, canonical schema guidance, and rollout strategy for the unified architecture plan.
- #file:../research/20260505-issue-96-learning-loop-rebuild-research.md - prior validated FastAPI/APScheduler external guidance reused for lifecycle ownership.
- #githubRepo:"tiangolo/fastapi lifespan" - lifecycle management precedent compatible with centralized service ownership.
- #fetch:https://fastapi.tiangolo.com/advanced/events/ - FastAPI lifespan guidance for startup/shutdown ownership.
- #fetch:https://apscheduler.readthedocs.io/en/3.x/modules/schedulers/asyncio.html - AsyncIOScheduler lifecycle guidance for existing trigger infrastructure.

### Standards References

- #file:../../.agent/rules/GEMINI.md - repository-wide operating rules and architecture context.
- #file:../../.agent/rules/backend.md - backend implementation conventions for Python/Go service changes.
- #file:../../.agent/rules/testing-standard.md - testing expectations for new regression and acceptance coverage.

## Implementation Checklist

### [ ] Phase 1: Canonical Schema and Projection Foundations

- [ ] Task 1.1: Create the canonical event ledger schema and explicit outcome taxonomy
  - Details: .copilot-tracking/details/20260506-canonical-event-ledger-learning-architecture-details.md (Lines 11-29)

- [ ] Task 1.2: Add rebuildable projections, invariants, and reconcile scaffolding
  - Details: .copilot-tracking/details/20260506-canonical-event-ledger-learning-architecture-details.md (Lines 30-48)

### [ ] Phase 2: Unified Interaction Run Writes and Read Surfaces

- [ ] Task 2.1: Route sync, stream, and early-exit flows through one terminal event writer
  - Details: .copilot-tracking/details/20260506-canonical-event-ledger-learning-architecture-details.md (Lines 51-70)

- [ ] Task 2.2: Replace JSONL-based interaction run reads with projection-backed APIs
  - Details: .copilot-tracking/details/20260506-canonical-event-ledger-learning-architecture-details.md (Lines 71-89)

### [ ] Phase 3: Learning Consumer Cutover and Lifecycle Correctness

- [ ] Task 3.1: Repoint failure monitoring, signal collection, and learning-run emission to canonical projections
  - Details: .copilot-tracking/details/20260506-canonical-event-ledger-learning-architecture-details.md (Lines 92-111)

- [ ] Task 3.2: Extend gap lifecycle with observing and controlled reopen semantics
  - Details: .copilot-tracking/details/20260506-canonical-event-ledger-learning-architecture-details.md (Lines 112-133)

### [ ] Phase 4: Migration Safety and Acceptance Verification

- [ ] Task 4.1: Implement dual-write, shadow-read, cutover, and rollback controls
  - Details: .copilot-tracking/details/20260506-canonical-event-ledger-learning-architecture-details.md (Lines 136-154)

- [ ] Task 4.2: Add invariant, rebuild, and end-to-end acceptance tests
  - Details: .copilot-tracking/details/20260506-canonical-event-ledger-learning-architecture-details.md (Lines 155-191)

## Dependencies

- PostgreSQL schema migrations and projection-friendly JSONB storage.
- Existing FastAPI lifespan and APScheduler runtime ownership in retrieval-service.
- Retrieval-service, frontend learning page, and gap/executor runtime modules remaining the core integration surfaces.
- Existing audited validation flow from Issue #96 rebuild retained as an acceptance signal.

## Success Criteria

- The plan defines one canonical fact model for interaction runs, learning runs, gaps, and improvement events.
- The implementation path removes JSONL/DB split-brain behavior from operational run surfaces.
- Failure monitoring and signal collection become projection-backed and transport-agnostic.
- Gap closure semantics include `observing` and fresh-signal-controlled reopen.
- Migration can proceed safely through dual-write, shadow-read, cutover, and rollback checkpoints.

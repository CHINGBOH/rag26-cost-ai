---
applyTo: ".copilot-tracking/changes/20260505-issue-96-learning-loop-rebuild-changes.md"
---

<!-- markdownlint-disable-file -->

# Task Checklist: Issue #96 Learning Loop Rebuild

## Overview

Rebuild Issue #96 into a real learning-loop system by consolidating backend routes/state, enabling closed-loop execution, and adding controlled automation with audited validation.

## Objectives

- Replace duplicate or stubbed learning API behavior with one authoritative backend execution path.
- Deliver a phased learning loop that supports problem detection, strategy execution, verification/rollback, and audited system-level automation.

## Research Summary

### Project Files

- `src/backend/retrieval-service/app/api.py` - duplicated learning routes and inconsistent status assembly must be consolidated first.
- `src/backend/retrieval-service/main.py` - startup/shutdown lifecycle integration point for scheduler and monitors.
- `src/backend/retrieval-service/app/agent/scheduler.py` - cron/manual trigger orchestration and scheduler lifecycle management.
- `src/frontend/web/src/pages/LearningPage.tsx` - current learning tab composition and incorrect review/history wiring.

### External References

- #file:../research/20260505-issue-96-learning-loop-rebuild-research.md - verified repo analysis, live endpoint behavior, failing tests, and external lifecycle references.
- #githubRepo:"CHINGBOH/RAG26 issue-96 learning loop" - repository-local implementation context and affected code paths.
- #fetch:https://fastapi.tiangolo.com/advanced/events/ - FastAPI lifespan lifecycle pattern used to justify startup/shutdown wiring.

### Standards References

- #file:../../AGENTS.md - repository behavior, routing, and architectural constraints for this codebase.
- #file:../../.github/copilot-instructions.md - project-level Copilot implementation guidance and standards.

## Implementation Checklist

### [ ] Phase 1: Backend Consolidation

- [ ] Task 1.1: Remove duplicate learning route implementations and define a single authoritative API surface

  - Details: .copilot-tracking/details/20260505-issue-96-learning-loop-rebuild-details.md (Lines 9-26)

- [ ] Task 1.2: Unify learning status computation behind a single backend status source
  - Details: .copilot-tracking/details/20260505-issue-96-learning-loop-rebuild-details.md (Lines 28-42)

- [ ] Task 1.3: Wire scheduler, failure monitor, and feedback analyzer into service startup/shutdown lifecycle
  - Details: .copilot-tracking/details/20260505-issue-96-learning-loop-rebuild-details.md (Lines 44-61)

### [ ] Phase 2: Closed-Loop Execution Core

- [ ] Task 2.1: Normalize signal aggregation into consistent problem reports and root-cause analysis inputs
  - Details: .copilot-tracking/details/20260505-issue-96-learning-loop-rebuild-details.md (Lines 65-79)

- [ ] Task 2.2: Formalize strategy generation and low-risk executor verification/rollback flow
  - Details: .copilot-tracking/details/20260505-issue-96-learning-loop-rebuild-details.md (Lines 81-95)

- [ ] Task 2.3: Align reviews and history semantics with true learning lifecycle states
  - Details: .copilot-tracking/details/20260505-issue-96-learning-loop-rebuild-details.md (Lines 97-110)

### [ ] Phase 3: Automation, Dashboard, and Audited Validation

- [ ] Task 3.1: Rebuild dashboard as the unified learning system control plane
  - Details: .copilot-tracking/details/20260505-issue-96-learning-loop-rebuild-details.md (Lines 114-127)

- [ ] Task 3.2: Enable cron/failure/feedback triggers with debounce and idempotency controls
  - Details: .copilot-tracking/details/20260505-issue-96-learning-loop-rebuild-details.md (Lines 129-144)

- [ ] Task 3.3: Integrate audited gold-test validation as a formal learning acceptance signal
  - Details: .copilot-tracking/details/20260505-issue-96-learning-loop-rebuild-details.md (Lines 146-158)

## Dependencies

- FastAPI lifespan-managed startup/shutdown integration
- APScheduler `AsyncIOScheduler`
- Existing retrieval-service learning modules, tests, and gold-test artifact

## Success Criteria

- Learning API behavior is consolidated behind a single backend implementation and consistent status model.
- The plan is implementation-ready for phased work covering consolidation, closed-loop execution, and audited automation.

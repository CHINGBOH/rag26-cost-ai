---
mode: agent
model: Claude Sonnet 4
---

<!-- markdownlint-disable-file -->

# Implementation Prompt: Canonical Event Ledger Learning Architecture

## Task Overview

Implement the canonical event ledger learning architecture so interaction runs, learning runs, gap lifecycle, and improvement events converge on one fact model with rebuildable projections and safe rollout controls.

## Implementation Instructions

### Step 1: Create Changes Tracking File

You WILL create `20260506-canonical-event-ledger-learning-architecture-changes.md` in #file:../changes/ if it does not exist.

### Step 2: Execute Implementation

You WILL systematically implement #file:../plans/20260506-canonical-event-ledger-learning-architecture-plan.instructions.md task-by-task.
You WILL use #file:../details/20260506-canonical-event-ledger-learning-architecture-details.md as the source of exact file targets, dependencies, and verification goals.
You WILL follow repository standards in:

- #file:../../.agent/rules/GEMINI.md
- #file:../../.agent/rules/backend.md
- #file:../../.agent/rules/testing-standard.md

**CRITICAL**: If ${input:phaseStop:true} is true, you WILL stop after each Phase for user review.
**CRITICAL**: If ${input:taskStop:false} is true, you WILL stop after each Task for user review.
**CRITICAL**: You WILL preserve additive migration safety: dual-write first, shadow-read second, read cutover third, legacy-path removal last.

### Step 3: Cleanup

When ALL Phases are checked off (`[x]`) and completed you WILL do the following:

1. You WILL provide a markdown style link and a brief summary of all changes from #file:../changes/20260506-canonical-event-ledger-learning-architecture-changes.md.
2. You WILL provide markdown style links to:
   - #file:../plans/20260506-canonical-event-ledger-learning-architecture-plan.instructions.md
   - #file:../details/20260506-canonical-event-ledger-learning-architecture-details.md
   - #file:../research/20260506-canonical-event-ledger-learning-architecture-research.md
   and recommend cleaning them up if no longer needed.
3. You WILL attempt to delete #file:../prompts/implement-canonical-event-ledger-learning-architecture.prompt.md.

## Success Criteria

- [ ] Changes tracking file created
- [ ] All plan phases implemented in order
- [ ] Canonical event writes and projection reads are working
- [ ] Gap lifecycle supports observing and controlled reopen
- [ ] Migration safety and verification checks are documented in the changes file

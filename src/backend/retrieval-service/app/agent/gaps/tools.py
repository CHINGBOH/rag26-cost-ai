"""Agent-facing database tools for learning gaps."""

from __future__ import annotations

from typing import Any, Optional

from app.agent.gaps.repository import KnowledgeGapRepository
from app.agent.gaps.retest import GapRetestService
from app.agent.gaps.workbench import GapWorkbenchService


def find_learning_gaps(
    status: Optional[list[str]] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    repository = KnowledgeGapRepository()
    return repository.fetch_gaps(limit=limit, statuses=status, include_resolved=True)


def build_gap_workbench(include_resolved: bool = False, limit: int = 200) -> dict[str, Any]:
    return GapWorkbenchService().build(include_resolved=include_resolved, limit=limit)


async def retest_learning_gap(
    gap_key: str,
    actor: str = "gap_tool",
    consultation_endpoint: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    repository = KnowledgeGapRepository()
    gaps = repository.fetch_gaps(limit=1, gap_keys=[gap_key], include_resolved=True)
    if not gaps:
        raise ValueError(f"Unknown knowledge gap: {gap_key}")
    return await GapRetestService(repository).retest_gap(
        gaps[0],
        actor=actor,
        consultation_endpoint=consultation_endpoint,
        dry_run=dry_run,
    )

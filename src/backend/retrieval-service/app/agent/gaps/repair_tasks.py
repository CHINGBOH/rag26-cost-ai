"""Promotion of repeated live-retest failures into repair tasks."""

from __future__ import annotations

from typing import Any

from app.agent.gaps.repository import KnowledgeGapRepository


def _is_coverage_repair_candidate(gap: dict[str, Any], action: dict[str, Any]) -> bool:
    if action.get("action") != "keep_open":
        return False
    if gap.get("affected_route"):
        return False
    evidence = action.get("evidence") if isinstance(action.get("evidence"), dict) else {}
    if evidence.get("generic_answer"):
        return False
    if int(evidence.get("chunks_count") or 0) > 0 and not evidence.get("refused"):
        return False
    return True


class GapRepairTaskService:
    def __init__(self, repository: KnowledgeGapRepository | None = None):
        self.repository = repository or KnowledgeGapRepository()

    def promote_from_retest_actions(
        self,
        *,
        active_gaps: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        actor: str,
        min_keep_open_evidence: int = 2,
        issue_number: int | None = None,
        issue_url: str | None = None,
    ) -> list[dict[str, Any]]:
        gaps_by_key = {str(gap.get("gap_key") or ""): gap for gap in active_gaps}
        promotions: list[dict[str, Any]] = []
        for action in actions:
            gap_key = str(action.get("gap_key") or "")
            gap = gaps_by_key.get(gap_key)
            if not gap or not _is_coverage_repair_candidate(gap, action):
                continue
            recent_evidence = self.repository.fetch_recent_keep_open_evidence(
                gap_key,
                limit=max(1, int(min_keep_open_evidence or 2)),
            )
            if len(recent_evidence) < max(1, int(min_keep_open_evidence or 2)):
                continue
            evidence_ids = [int(row["id"]) for row in recent_evidence if row.get("id")]
            reason = (
                "Repeated live retest keep_open evidence indicates a data/retrieval coverage "
                "repair task is required"
            )
            repair_task = self.repository.create_repair_task(
                gap_key=gap_key,
                task_type="data_retrieval_coverage",
                actor=actor,
                reason=reason,
                latest_evidence_ids=evidence_ids,
                issue_number=issue_number,
                issue_url=issue_url,
                metadata={
                    "query": gap.get("query"),
                    "source": gap.get("source"),
                    "cause_type": gap.get("cause_type"),
                    "latest_action": action,
                },
            )
            evidence = self.repository.insert_evidence(
                gap_key=gap_key,
                evidence_type="repair_task_created",
                actor=actor,
                evidence={
                    "query": gap.get("query"),
                    "source_type": "repair_task",
                    "repair_task_id": repair_task["id"],
                    "repair_task_type": repair_task["task_type"],
                    "latest_evidence_ids": evidence_ids,
                    "outcome_code": "REPAIR_TASK_CREATED",
                    "reason": reason,
                },
                decision="create_repair_task",
                decision_reason=reason,
            )
            previous_status = str(gap.get("status") or "open")
            updated = self.repository.update_gap_status(
                gap_key=gap_key,
                status="in_progress",
                reason=reason,
                actor=actor,
                metadata_patch={
                    "repair_task_id": repair_task["id"],
                    "repair_task_type": repair_task["task_type"],
                    "repair_issue_url": issue_url,
                },
            )
            transition = self.repository.insert_transition(
                gap_key=gap_key,
                from_status=previous_status,
                to_status="in_progress",
                action="create_repair_task",
                actor=actor,
                reason=reason,
                evidence_id=evidence.get("id"),
            )
            promotions.append(
                {
                    "gap_key": gap_key,
                    "repair_task": repair_task,
                    "evidence_id": evidence.get("id"),
                    "transition_id": transition.get("id"),
                    "updated": updated,
                }
            )
        return promotions

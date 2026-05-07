"""Workbench projection for learning gaps."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.agent.gaps.lifecycle import (
    allowed_actions_for_status,
    bucket_for_status,
    is_passing_gap_evidence,
)
from app.agent.gaps.repository import KnowledgeGapRepository


def _build_public_gap(gap: dict[str, Any], latest_evidence: dict[str, Any] | None) -> dict[str, Any]:
    public_gap = {key: value for key, value in gap.items() if key != "metadata"}
    status = str(public_gap.get("status") or "open").lower()
    if status in {"observing", "resolved"} and is_passing_gap_evidence(latest_evidence):
        public_gap["quality"] = "good"
        public_gap["refused"] = False
        public_gap["chunks_count"] = int(latest_evidence.get("chunks_count") or 0)
        if latest_evidence.get("confidence") is not None:
            public_gap["confidence"] = float(latest_evidence["confidence"])
        if latest_evidence.get("answer_preview"):
            public_gap["answer_preview"] = latest_evidence["answer_preview"]
        public_gap["current_outcome_code"] = latest_evidence.get("outcome_code")
        public_gap["current_decision"] = latest_evidence.get("decision")
    return public_gap


def _build_presentation(gap: dict[str, Any], latest_evidence: dict[str, Any] | None) -> dict[str, Any]:
    status = str(gap.get("status") or "open").lower()
    quality = str(gap.get("quality") or "weak")
    refused = bool(gap.get("refused"))
    chunks_count = int(gap.get("chunks_count") or 0)
    confidence = float(gap.get("confidence") or 0.0)
    badge = quality
    reason = "Original gap detection state"

    if status in {"observing", "resolved"} and is_passing_gap_evidence(latest_evidence):
        quality = "good"
        refused = False
        chunks_count = int(latest_evidence.get("chunks_count") or 0)
        if latest_evidence.get("confidence") is not None:
            confidence = float(latest_evidence["confidence"])
        badge = "validated"
        reason = "Latest persisted evidence answered successfully; historical failure is retained only in evidence history"
    elif latest_evidence and latest_evidence.get("decision") == "observe_fixed" and not is_passing_gap_evidence(latest_evidence):
        quality = "failure"
        refused = True
        chunks_count = int(latest_evidence.get("chunks_count") or 0)
        if latest_evidence.get("confidence") is not None:
            confidence = float(latest_evidence["confidence"])
        badge = "failure"
        reason = "Latest fixed-state evidence is invalid and requires retest"
    elif latest_evidence:
        if latest_evidence.get("quality"):
            quality = str(latest_evidence["quality"])
        if latest_evidence.get("refused") is not None:
            refused = bool(latest_evidence["refused"])
        if latest_evidence.get("chunks_count") is not None:
            chunks_count = int(latest_evidence.get("chunks_count") or 0)
        if latest_evidence.get("confidence") is not None:
            confidence = float(latest_evidence["confidence"])
        badge = quality
        reason = "Latest persisted evidence state"

    return {
        "quality": quality,
        "refused": refused,
        "chunks_count": chunks_count,
        "confidence": confidence,
        "badge": badge,
        "reason": reason,
    }


class GapWorkbenchService:
    def __init__(self, repository: KnowledgeGapRepository | None = None):
        self.repository = repository or KnowledgeGapRepository()

    def build(self, *, include_resolved: bool = False, limit: int = 200) -> dict[str, Any]:
        gaps = self.repository.fetch_gaps(limit=limit, include_resolved=include_resolved)
        latest_evidence = self.repository.latest_evidence_map(
            [str(gap.get("gap_key")) for gap in gaps if gap.get("gap_key")]
        )
        active_repair_tasks = self.repository.fetch_active_repair_tasks_map(
            [str(gap.get("gap_key")) for gap in gaps if gap.get("gap_key")]
        )
        buckets: dict[str, list[dict[str, Any]]] = {
            "active": [],
            "observing": [],
            "blocked": [],
            "resolved": [],
        }
        counts = {
            "active": 0,
            "observing": 0,
            "blocked": 0,
            "resolved": 0,
            "total": 0,
            "by_status": {
                "open": 0,
                "in_progress": 0,
                "observing": 0,
                "blocked": 0,
                "resolved": 0,
            },
        }
        for gap in gaps:
            status = str(gap.get("status") or "open").lower()
            bucket = bucket_for_status(status)
            evidence = latest_evidence.get(str(gap.get("gap_key")))
            public_gap = _build_public_gap(gap, evidence)
            item = {
                "gap": public_gap,
                "latest_evidence": evidence,
                "repair_task": active_repair_tasks.get(str(gap.get("gap_key"))),
                "allowed_actions": allowed_actions_for_status(status),
                "bucket": bucket,
                "presentation": _build_presentation(public_gap, evidence),
            }
            if bucket == "resolved" and not include_resolved:
                continue
            buckets[bucket].append(item)
            counts["total"] += 1
            counts[bucket] += 1
            if status in counts["by_status"]:
                counts["by_status"][status] += 1
        return {
            "counts": counts,
            "by_status": counts["by_status"],
            "buckets": buckets,
            "last_retest_run": self.repository.latest_gap_retest_run(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def detail(self, gap_key: str) -> dict[str, Any] | None:
        gaps = self.repository.fetch_gaps(limit=1, gap_keys=[gap_key], include_resolved=True)
        if not gaps:
            return None
        gap = gaps[0]
        status = str(gap.get("status") or "open").lower()
        latest_evidence = self.repository.latest_evidence_map([gap_key]).get(gap_key)
        public_gap = _build_public_gap(gap, latest_evidence)
        repair_task = self.repository.fetch_active_repair_tasks_map([gap_key]).get(gap_key)
        return {
            "gap": {
                **public_gap,
                "allowed_actions": allowed_actions_for_status(status),
                "bucket": bucket_for_status(status),
            },
            "latest_evidence": latest_evidence,
            "presentation": _build_presentation(public_gap, latest_evidence),
            "repair_task": repair_task,
            "evidence_history": self.repository.fetch_evidence_history(gap_key),
            "transitions": self.repository.fetch_transition_history(gap_key),
        }

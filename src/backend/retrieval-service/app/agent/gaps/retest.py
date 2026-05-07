"""Live consultation retest service for learning gaps."""

from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Optional

from app.agent.gaps.lifecycle import decide_from_live_retest
from app.agent.gaps.repository import KnowledgeGapRepository
from app.agent.learning_state import coerce_json_dict

_REFUSAL_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"无法直接回答|无法回答|无法提供|无法分析|无法对比|无法计算",
        r"不足以回答|未提供|均显示为N/A|无相关数据|未包含",
        r"cannot answer|cannot provide|insufficient evidence|not enough information",
    )
]


def normalize_consultation_endpoint(endpoint: Optional[str]) -> str:
    base = (endpoint or "").strip() or "http://localhost:8002/api/v1/agent"
    if base.endswith("/api/v1/agent"):
        return base
    return f"{base.rstrip('/')}/api/v1/agent"


def detect_refusal_answer(answer: str) -> bool:
    return any(pattern.search(answer or "") for pattern in _REFUSAL_PATTERNS)


def is_generic_consultation_answer(answer: str) -> bool:
    normalized = re.sub(r"\s+", "", answer or "")
    generic_patterns = (
        "我是专注于工程造价领域的智能问答助手",
        "只能回答与建设工程定额",
        "工程造价领域的智能问答助手",
    )
    return any(pattern in normalized for pattern in generic_patterns)


def extract_gap_retest_query(gap: dict[str, Any]) -> str:
    for key in ("query", "query_text", "description"):
        value = str(gap.get(key) or "").strip()
        if value:
            return value
    sample_queries = gap.get("sample_queries")
    if isinstance(sample_queries, list):
        for query in sample_queries:
            value = str(query or "").strip()
            if value:
                return value
    return str(gap.get("gap_key") or "").strip()


def call_consultation_endpoint(
    *,
    endpoint: str,
    query: str,
    timeout_seconds: int,
    max_iterations: int,
) -> dict[str, Any]:
    normalized_endpoint = normalize_consultation_endpoint(endpoint)
    request_payload = json.dumps(
        {
            "query": query,
            "session_id": f"learning-live-retest-{uuid.uuid4()}",
            "max_iterations": max(1, min(int(max_iterations or 3), 5)),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        normalized_endpoint,
        data=request_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started_at = int(time.time() * 1000)
    try:
        with urllib.request.urlopen(
            request,
            timeout=max(5, min(int(timeout_seconds or 60), 180)),
        ) as response:
            raw_body = response.read().decode("utf-8")
            http_status = int(response.status)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "http_status": int(exc.code),
            "endpoint": normalized_endpoint,
            "query": query,
            "answer_preview": "",
            "chunks_count": 0,
            "refused": True,
            "quality": "failure",
            "outcome_code": "HTTP_ERROR",
            "error": body[:500],
            "latency_ms": int(time.time() * 1000) - started_at,
        }
    except Exception as exc:
        return {
            "ok": False,
            "http_status": None,
            "endpoint": normalized_endpoint,
            "query": query,
            "answer_preview": "",
            "chunks_count": 0,
            "refused": True,
            "quality": "failure",
            "outcome_code": "REQUEST_ERROR",
            "error": str(exc),
            "latency_ms": int(time.time() * 1000) - started_at,
        }

    try:
        data = json.loads(raw_body)
    except Exception:
        data = {}
    answer = str(data.get("answer") or "")
    chunks = data.get("chunks") if isinstance(data.get("chunks"), list) else []
    evaluation = coerce_json_dict(data.get("evaluation"))
    refused = detect_refusal_answer(answer)
    generic_answer = is_generic_consultation_answer(answer)
    confidence = evaluation.get("confidence")
    confidence_value = float(confidence) if isinstance(confidence, (int, float)) else None
    quality = (
        "failure"
        if refused or generic_answer or not answer.strip() or not chunks
        else "weak"
        if confidence_value is not None and confidence_value < 0.4
        else "good"
    )
    return {
        "ok": http_status < 500,
        "http_status": http_status,
        "endpoint": normalized_endpoint,
        "query": query,
        "run_id": data.get("run_id"),
        "session_id": data.get("session_id"),
        "answer_preview": answer[:500],
        "chunks_count": len(chunks),
        "refused": refused,
        "generic_answer": generic_answer,
        "quality": quality,
        "outcome_code": "REFUSED_LIVE_RETEST" if refused else "ANSWERED_OK",
        "confidence": confidence_value,
        "latency_ms": int(time.time() * 1000) - started_at,
    }


class GapRetestService:
    def __init__(self, repository: KnowledgeGapRepository | None = None):
        self.repository = repository or KnowledgeGapRepository()

    async def retest_gap(
        self,
        gap: dict[str, Any],
        *,
        actor: str,
        consultation_endpoint: Optional[str] = None,
        timeout_seconds: int = 60,
        max_iterations: int = 3,
        observation_window_days: int = 7,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        query = extract_gap_retest_query(gap)
        evidence = await asyncio.to_thread(
            call_consultation_endpoint,
            endpoint=normalize_consultation_endpoint(consultation_endpoint),
            query=query,
            timeout_seconds=timeout_seconds,
            max_iterations=max_iterations,
        )
        decision = decide_from_live_retest(gap, evidence)
        action = str(decision["action"])
        previous_status = str(gap.get("status") or "open").lower()
        next_status = str(decision["status"] or previous_status).lower()
        evidence_row: dict[str, Any] | None = None
        transition_row: dict[str, Any] | None = None
        applied = False

        if not dry_run:
            evidence_row = self.repository.insert_evidence(
                gap_key=str(gap.get("gap_key")),
                evidence_type="live_retest",
                actor=actor,
                evidence=evidence,
                decision=action,
                decision_reason=str(decision.get("reason") or ""),
            )
            self.repository.project_current_state_from_evidence(
                gap_key=str(gap.get("gap_key")),
                evidence=evidence,
                actor=actor,
                decision=action,
                evidence_id=evidence_row.get("id") if evidence_row else None,
            )
            if next_status != previous_status:
                applied = self.repository.update_gap_status(
                    gap_key=str(gap.get("gap_key")),
                    status=next_status,
                    reason=str(decision.get("reason") or ""),
                    actor=actor,
                    metadata_patch={
                        "triage_action": action,
                        "triage_reason": decision.get("reason"),
                        "triage_actor": actor,
                        "triage_mode": "live_consultation",
                        "triage_evidence": evidence,
                    },
                    observation_window_days=observation_window_days,
                )
                transition_row = self.repository.insert_transition(
                    gap_key=str(gap.get("gap_key")),
                    from_status=previous_status,
                    to_status=next_status,
                    action=action,
                    actor=actor,
                    reason=str(decision.get("reason") or ""),
                    evidence_id=evidence_row.get("id") if evidence_row else None,
                )

        return {
            "gap_key": str(gap.get("gap_key") or ""),
            "previous_status": previous_status,
            "action": action,
            "status": next_status,
            "reason": decision.get("reason"),
            "applied": applied,
            "event_id": None,
            "evidence": evidence,
            "evidence_id": evidence_row.get("id") if evidence_row else None,
            "transition_id": transition_row.get("id") if transition_row else None,
            "triage_mode": "live_consultation",
        }

    async def retest_batch(
        self,
        *,
        gaps: list[dict[str, Any]],
        actor: str,
        consultation_endpoint: Optional[str] = None,
        timeout_seconds: int = 60,
        max_iterations: int = 3,
        observation_window_days: int = 7,
        max_live_retests: int = 5,
        dry_run: bool = False,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        used = 0
        for gap in gaps:
            if used >= max(0, int(max_live_retests or 0)):
                break
            if str(gap.get("status") or "open").lower() not in {"open", "in_progress"}:
                continue
            used += 1
            results.append(
                await self.retest_gap(
                    gap,
                    actor=actor,
                    consultation_endpoint=consultation_endpoint,
                    timeout_seconds=timeout_seconds,
                    max_iterations=max_iterations,
                    observation_window_days=observation_window_days,
                    dry_run=dry_run,
                )
            )
        return results

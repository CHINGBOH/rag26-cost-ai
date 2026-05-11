"""Learning gap lifecycle state machine."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.agent.event_taxonomy import REFUSAL_MARKERS
from app.agent.gaps.state_machine import get_state_machine

logger = logging.getLogger(__name__)


ACTIVE_STATUSES = {"open", "in_progress"}
GAP_BUCKETS = ("active", "observing", "blocked", "resolved")

_POLICY_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"忽略.*(身份|规则|系统)",
        r"ignore.*(role|instruction|system)",
        r"不要提.*(依据|资料|证据)",
        r"不需要.*(依据|资料|证据)",
        r"编造|捏造|fabricate|make up",
        r"英伟达|nvidia|股票|股价|stock",
    )
]


def bucket_for_status(status: str) -> str:
    normalized = str(status or "open").lower()
    if normalized in ACTIVE_STATUSES:
        return "active"
    if normalized == "observing":
        return "observing"
    if normalized == "blocked":
        return "blocked"
    if normalized == "resolved":
        return "resolved"
    return "active"


def allowed_actions_for_status(status: str) -> list[str]:
    normalized = str(status or "open").lower()
    if normalized == "open":
        return ["retest", "start_repair", "block", "link_event"]
    if normalized == "in_progress":
        return ["retest", "mark_observing", "link_event"]
    if normalized == "observing":
        return ["retest", "resolve", "reopen"]
    if normalized == "blocked":
        return ["reopen", "inspect_evidence"]
    if normalized == "resolved":
        return ["reopen", "inspect_evidence"]
    return ["inspect_evidence"]


def answer_contains_refusal(text: Any) -> bool:
    answer = str(text or "")
    return any(marker in answer for marker in REFUSAL_MARKERS)


def is_passing_gap_evidence(evidence: dict[str, Any] | None) -> bool:
    if not evidence:
        return False
    decision_fixed = evidence.get("decision") == "observe_fixed"
    return (
        evidence.get("quality") == "good"
        and not evidence.get("generic_answer")
        and (not evidence.get("refused") or decision_fixed)
        and not answer_contains_refusal(evidence.get("answer_preview"))
        and int(evidence.get("chunks_count") or 0) > 0
        and (decision_fixed or evidence.get("outcome_code") == "ANSWERED_OK")
    )


def is_policy_boundary_gap(gap: dict[str, Any]) -> bool:
    text = " ".join(
        str(gap.get(key) or "")
        for key in ("query", "description", "answer_preview", "cause_type", "problem_id")
    )
    return any(pattern.search(text) for pattern in _POLICY_PATTERNS)


def _observation_window_expired(gap: dict[str, Any]) -> bool:
    """Return True if gap is in observing state and observation_until has passed."""
    if str(gap.get("status") or "").lower() != "observing":
        return False
    observation_until = gap.get("observation_until")
    if not observation_until:
        return False
    try:
        from datetime import datetime, timezone
        if isinstance(observation_until, (int, float)):
            # epoch milliseconds
            until_dt = datetime.fromtimestamp(observation_until / 1000.0, tz=timezone.utc)
        elif isinstance(observation_until, str):
            until_dt = datetime.fromisoformat(observation_until.replace("Z", "+00:00"))
            if until_dt.tzinfo is None:
                until_dt = until_dt.replace(tzinfo=timezone.utc)
        else:
            until_dt = observation_until  # datetime already
        return datetime.now(timezone.utc) >= until_dt
    except Exception:
        return False


def decide_from_live_retest(gap: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    current_status = str(gap.get("status") or "open").lower()
    if is_policy_boundary_gap(gap):
        return {
            "action": "block_policy",
            "status": "blocked",
            "reason": "Live consultation retest confirmed policy, out-of-domain, or fabrication boundary",
        }
    passing = (
        evidence.get("ok")
        and evidence.get("quality") == "good"
        and not evidence.get("refused")
        and not evidence.get("generic_answer")
        and int(evidence.get("chunks_count") or 0) > 0
    )
    if passing:
        # 观察期已过 + 复测仍然通过 → 自动 resolve（关闭闭环）
        if current_status == "observing" and _observation_window_expired(gap):
            return {
                "action": "resolve_after_observation",
                "status": "resolved",
                "reason": "Observation window expired and live retest continues to pass — auto-resolved",
            }
        return {
            "action": "observe_fixed",
            "status": "observing",
            "reason": "Live consultation retest returned non-refusal answer with retrieval evidence",
        }
    if current_status in {"observing", "resolved"}:
        return {
            "action": "reopen",
            "status": "open",
            "reason": "Live consultation retest invalidated the previous fixed/observing evidence",
        }
    return {
        "action": "keep_open",
        "status": current_status,
        "reason": "Live consultation retest did not produce passing evidence",
    }


def transition_status_for_action(current_status: str, action: str) -> str:
    normalized = str(current_status or "open").lower()
    normalized_action = str(action or "").lower()
    if normalized_action == "resolve" and normalized == "observing":
        target = "resolved"
    elif normalized_action == "reopen" and normalized in {"observing", "resolved", "blocked"}:
        target = "open"
    elif normalized_action == "block" and normalized in {"open", "in_progress"}:
        target = "blocked"
    elif normalized_action == "mark_observing" and normalized in {"open", "in_progress"}:
        target = "observing"
    elif normalized_action == "start_repair" and normalized == "open":
        target = "in_progress"
    else:
        return normalized

    # Issue #120: Validate transition through state machine
    sm = get_state_machine()
    try:
        if not sm.is_valid_transition(normalized, target):
            logger.warning(
                f"[lifecycle] Action '{action}' produced invalid transition "
                f"{normalized} → {target}. Returning current status."
            )
            return normalized
    except ValueError:
        return normalized

    return target

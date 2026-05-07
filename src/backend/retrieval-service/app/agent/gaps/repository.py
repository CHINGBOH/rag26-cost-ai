"""
Repository helpers for database-backed learning gap workbench data.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from psycopg2.extras import Json

from app.agent.gaps.lifecycle import is_passing_gap_evidence
from app.agent.learning_state import (
    _KNOWLEDGE_GAP_RETURNING_COLUMNS,
    _knowledge_gap_row_to_snapshot,
    coerce_json_dict,
    fetch_knowledge_gaps,
    normalize_epoch_milliseconds,
    update_knowledge_gap_status,
)
from app.agent.tools import _get_pg_conn, _put_pg_conn


_SENSITIVE_KEYS = {"api_key", "authorization", "password", "secret", "token"}


def _redact_sensitive_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***REDACTED***" if key.lower() in _SENSITIVE_KEYS else _redact_sensitive_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_payload(item) for item in value]
    return value


def _evidence_row_to_dict(row: Any) -> dict[str, Any]:
    created_at = normalize_epoch_milliseconds(row[19])
    raw_payload = _redact_sensitive_payload(coerce_json_dict(row[18]))
    return {
        "id": int(row[0]),
        "gap_key": row[1],
        "evidence_type": row[2],
        "source_type": raw_payload.get("source_type"),
        "actor": row[3],
        "source_run_id": row[4],
        "consultation_run_id": row[5],
        "session_id": row[6],
        "endpoint": row[7],
        "query_text": row[8],
        "answer_preview": row[9],
        "chunks_count": int(row[10] or 0),
        "refused": bool(row[11]) if row[11] is not None else None,
        "generic_answer": bool(row[12]) if row[12] is not None else None,
        "quality": row[13],
        "outcome_code": row[14],
        "confidence": float(row[15]) if row[15] is not None else None,
        "decision": row[16],
        "decision_reason": row[17],
        "created_at": created_at,
        "recorded_at": created_at,
    }


def _transition_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": int(row[0]),
        "gap_key": row[1],
        "from_status": row[2],
        "to_status": row[3],
        "action": row[4],
        "actor": row[5],
        "reason": row[6],
        "evidence_id": row[7],
        "occurred_at": normalize_epoch_milliseconds(row[8]),
    }


class KnowledgeGapRepository:
    """Owns all DB reads/writes for learning gap workbench state."""

    def fetch_gap(self, gap_key: str) -> Optional[dict[str, Any]]:
        gaps = fetch_knowledge_gaps(limit=1, pool=None)
        for gap in gaps:
            if gap.get("gap_key") == gap_key:
                return gap
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status
                    FROM knowledge_gaps
                    WHERE gap_key = %s
                    """,
                    (gap_key,),
                )
                if cur.fetchone() is None:
                    return None
            return self.fetch_gaps(limit=1, gap_keys=[gap_key])[0]
        finally:
            _put_pg_conn(conn)

    def fetch_gaps(
        self,
        *,
        limit: int = 200,
        statuses: Optional[Iterable[str]] = None,
        gap_keys: Optional[Iterable[str]] = None,
        include_resolved: bool = True,
    ) -> list[dict[str, Any]]:
        conn = _get_pg_conn()
        try:
            clauses: list[str] = []
            params: list[Any] = []
            normalized_statuses = [str(status).lower() for status in statuses or [] if status]
            keys = [str(key) for key in gap_keys or [] if key]
            if normalized_statuses:
                clauses.append("status = ANY(%s)")
                params.append(normalized_statuses)
            elif not include_resolved:
                clauses.append("status != 'resolved'")
            if keys:
                clauses.append("gap_key = ANY(%s)")
                params.append(keys)
            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        gap_key, problem_id, description, source, affected_route, query_text, status, quality,
                        resolution_plan, confidence, metadata, created_at, updated_at, resolved_at,
                        verified_at, observation_until, last_reopened_at, scope_type, scope_id, cluster_id,
                        cause_type, priority, owner, reopen_count, linked_event_id, first_seen_at, last_seen_at
                    FROM knowledge_gaps
                    {where_sql}
                    ORDER BY
                        CASE status
                            WHEN 'open' THEN 0
                            WHEN 'in_progress' THEN 1
                            WHEN 'observing' THEN 2
                            WHEN 'blocked' THEN 3
                            WHEN 'resolved' THEN 4
                            ELSE 5
                        END,
                        priority DESC,
                        last_seen_at DESC,
                        updated_at DESC
                    LIMIT %s
                    """,
                    (*params, max(1, min(int(limit or 200), 500))),
                )
                rows = cur.fetchall()
        finally:
            _put_pg_conn(conn)

        gaps: list[dict[str, Any]] = []
        for row in rows:
            metadata = coerce_json_dict(row[10])
            sample_queries = metadata.get("sample_queries") if isinstance(metadata.get("sample_queries"), list) else []
            gaps.append(
                {
                    "gap_key": row[0],
                    "problem_id": row[1],
                    "query": row[5] or row[2],
                    "description": row[2],
                    "source": row[3],
                    "affected_route": row[4],
                    "status": row[6],
                    "quality": row[7] or "weak",
                    "resolution_plan": row[8],
                    "confidence": float(row[9] or 0.0),
                    "answer_preview": metadata.get("answer_preview", ""),
                    "chunks_count": int(metadata.get("chunks_count") or 0),
                    "refused": bool(metadata.get("refused")),
                    "created_at": normalize_epoch_milliseconds(row[11]),
                    "updated_at": normalize_epoch_milliseconds(row[12]),
                    "resolved_at": normalize_epoch_milliseconds(row[13]),
                    "verified_at": normalize_epoch_milliseconds(row[14]),
                    "observation_until": normalize_epoch_milliseconds(row[15]),
                    "last_reopened_at": normalize_epoch_milliseconds(row[16]),
                    "scope_type": row[17],
                    "scope_id": row[18],
                    "cluster_id": row[19],
                    "cause_type": row[20],
                    "priority": int(row[21] or 0),
                    "owner": row[22],
                    "reopen_count": int(row[23] or 0),
                    "linked_event_id": row[24],
                    "first_seen_at": normalize_epoch_milliseconds(row[25]),
                    "last_seen_at": normalize_epoch_milliseconds(row[26]),
                    "sample_queries": sample_queries,
                    "frequency": int(metadata.get("frequency") or max(1, len(sample_queries) or 1)),
                    "metadata": metadata,
                    "ts": normalize_epoch_milliseconds(row[26] or row[11]),
                }
            )
        return gaps

    def insert_evidence(
        self,
        *,
        gap_key: str,
        evidence_type: str,
        actor: str,
        evidence: dict[str, Any],
        decision: Optional[str] = None,
        decision_reason: Optional[str] = None,
    ) -> dict[str, Any]:
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO knowledge_gap_evidence (
                        gap_key, evidence_type, actor, source_run_id, consultation_run_id, session_id,
                        endpoint, query_text, answer_preview, chunks_count, refused, generic_answer,
                        quality, outcome_code, confidence, decision, decision_reason, raw_payload
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    RETURNING
                        id, gap_key, evidence_type, actor, source_run_id, consultation_run_id, session_id,
                        endpoint, query_text, answer_preview, chunks_count, refused, generic_answer,
                        quality, outcome_code, confidence, decision, decision_reason, raw_payload, created_at
                    """,
                    (
                        gap_key,
                        evidence_type,
                        actor,
                        evidence.get("source_run_id"),
                        evidence.get("run_id") or evidence.get("consultation_run_id"),
                        evidence.get("session_id"),
                        evidence.get("endpoint"),
                        evidence.get("query"),
                        evidence.get("answer_preview"),
                        int(evidence.get("chunks_count") or 0),
                        evidence.get("refused"),
                        evidence.get("generic_answer"),
                        evidence.get("quality"),
                        evidence.get("outcome_code"),
                        evidence.get("confidence"),
                        decision,
                        decision_reason,
                        Json(evidence),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _put_pg_conn(conn)
        return _evidence_row_to_dict(row)

    def insert_transition(
        self,
        *,
        gap_key: str,
        from_status: Optional[str],
        to_status: str,
        action: str,
        actor: str,
        reason: str,
        evidence_id: Optional[int] = None,
    ) -> dict[str, Any]:
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO knowledge_gap_transitions (
                        gap_key, from_status, to_status, action, actor, reason, evidence_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING
                        id, gap_key, from_status, to_status, action, actor, reason, evidence_id, occurred_at
                    """,
                    (gap_key, from_status, to_status, action, actor, reason, evidence_id),
                )
                row = cur.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _put_pg_conn(conn)
        return _transition_row_to_dict(row)

    def update_gap_status(
        self,
        *,
        gap_key: str,
        status: str,
        reason: str,
        actor: str,
        metadata_patch: Optional[dict[str, Any]] = None,
        observation_window_days: int = 7,
    ) -> bool:
        return update_knowledge_gap_status(
            gap_key,
            status,
            reason,
            metadata_patch=metadata_patch or {},
            owner=actor,
            observation_window_days=observation_window_days,
        )

    def project_current_state_from_evidence(
        self,
        *,
        gap_key: str,
        evidence: dict[str, Any],
        actor: str,
        decision: Optional[str] = None,
        evidence_id: Optional[int] = None,
    ) -> bool:
        quality = evidence.get("quality")
        confidence = evidence.get("confidence")
        confidence_value = float(confidence) if isinstance(confidence, (int, float)) else None
        refused = False if is_passing_gap_evidence({**evidence, "decision": decision}) else bool(evidence.get("refused"))
        metadata_patch = {
            "answer_preview": evidence.get("answer_preview") or "",
            "chunks_count": int(evidence.get("chunks_count") or 0),
            "refused": refused,
            "generic_answer": bool(evidence.get("generic_answer")),
            "current_outcome_code": evidence.get("outcome_code"),
            "current_decision": decision,
            "current_evidence_id": evidence_id,
            "current_evidence_actor": actor,
        }
        conn = _get_pg_conn()
        try:
            from app.agent.event_ledger import insert_knowledge_gap_event

            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE knowledge_gaps
                    SET quality = COALESCE(%s, quality),
                        confidence = COALESCE(%s, confidence),
                        metadata = COALESCE(metadata, '{{}}'::jsonb) || %s::jsonb,
                        updated_at = NOW()
                    WHERE gap_key = %s
                    RETURNING
                        {_KNOWLEDGE_GAP_RETURNING_COLUMNS}
                    """,
                    (
                        quality if isinstance(quality, str) and quality else None,
                        confidence_value,
                        json.dumps(metadata_patch, ensure_ascii=False),
                        gap_key,
                    ),
                )
                updated = cur.rowcount > 0
                snapshot_row = cur.fetchone() if updated else None
                if snapshot_row:
                    snapshot = _knowledge_gap_row_to_snapshot(snapshot_row)
                    insert_knowledge_gap_event(
                        cur,
                        gap_key=str(snapshot["gap_key"]),
                        event_type="knowledge.gap.evidence_projected",
                        snapshot=snapshot,
                        occurred_at=snapshot.get("updated_at"),
                    )
            conn.commit()
            return updated
        except Exception:
            conn.rollback()
            raise
        finally:
            _put_pg_conn(conn)

    def reconcile_latest_evidence_projection(
        self,
        *,
        actor: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH latest AS (
                        SELECT DISTINCT ON (gap_key)
                            id, gap_key, evidence_type, actor, source_run_id,
                            consultation_run_id, session_id, endpoint, query_text,
                            answer_preview, chunks_count, refused, generic_answer,
                            quality, outcome_code, confidence, decision, decision_reason,
                            raw_payload, created_at
                        FROM knowledge_gap_evidence
                        WHERE evidence_type IN ('live_retest', 'legacy_metadata')
                          AND quality IS NOT NULL
                        ORDER BY gap_key, created_at DESC, id DESC
                    )
                    SELECT
                        latest.id, latest.gap_key, latest.evidence_type, latest.actor,
                        latest.source_run_id, latest.consultation_run_id, latest.session_id,
                        latest.endpoint, latest.query_text, latest.answer_preview,
                        latest.chunks_count, latest.refused, latest.generic_answer,
                        latest.quality, latest.outcome_code, latest.confidence,
                        latest.decision, latest.decision_reason, latest.raw_payload,
                        latest.created_at
                    FROM knowledge_gaps gap
                    JOIN latest ON latest.gap_key = gap.gap_key
                    WHERE gap.status IN ('open', 'in_progress', 'observing', 'resolved')
                      AND (
                            gap.quality IS DISTINCT FROM latest.quality
                            OR COALESCE(gap.metadata->>'current_evidence_id', '') IS DISTINCT FROM latest.id::text
                            OR COALESCE(gap.metadata->>'refused', '') IS DISTINCT FROM COALESCE(latest.refused::text, '')
                            OR COALESCE(gap.metadata->>'chunks_count', '') IS DISTINCT FROM COALESCE(latest.chunks_count::text, '')
                          )
                    ORDER BY latest.created_at DESC, latest.id DESC
                    LIMIT %s
                    """,
                    (max(1, min(int(limit or 200), 500)),),
                )
                rows = cur.fetchall()
        finally:
            _put_pg_conn(conn)

        reconciled: list[dict[str, Any]] = []
        for row in rows:
            evidence = _evidence_row_to_dict(row)
            self.project_current_state_from_evidence(
                gap_key=str(evidence["gap_key"]),
                evidence=evidence,
                actor=actor,
                decision=evidence.get("decision"),
                evidence_id=int(evidence["id"]),
            )
            reconciled.append(
                {
                    "gap_key": evidence["gap_key"],
                    "evidence_id": evidence["id"],
                    "quality": evidence.get("quality"),
                    "refused": False
                    if is_passing_gap_evidence(evidence)
                    else evidence.get("refused"),
                    "chunks_count": evidence.get("chunks_count"),
                    "decision": evidence.get("decision"),
                    "outcome_code": evidence.get("outcome_code"),
                }
            )
        return reconciled

    def invalidate_stale_fixed_state(
        self,
        *,
        actor: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH latest AS (
                        SELECT DISTINCT ON (gap_key)
                            id, gap_key, evidence_type, actor, source_run_id,
                            consultation_run_id, session_id, endpoint, query_text,
                            answer_preview, chunks_count, refused, generic_answer,
                            quality, outcome_code, confidence, decision, decision_reason,
                            raw_payload, created_at
                        FROM knowledge_gap_evidence
                        WHERE evidence_type IN ('live_retest', 'legacy_metadata')
                          AND quality IS NOT NULL
                        ORDER BY gap_key, created_at DESC, id DESC
                    )
                    SELECT
                        latest.id, latest.gap_key, latest.evidence_type, latest.actor,
                        latest.source_run_id, latest.consultation_run_id, latest.session_id,
                        latest.endpoint, latest.query_text, latest.answer_preview,
                        latest.chunks_count, latest.refused, latest.generic_answer,
                        latest.quality, latest.outcome_code, latest.confidence,
                        latest.decision, latest.decision_reason, latest.raw_payload,
                        latest.created_at,
                        gap.status
                    FROM knowledge_gaps gap
                    JOIN latest ON latest.gap_key = gap.gap_key
                    WHERE gap.status IN ('observing', 'resolved')
                    ORDER BY latest.created_at DESC, latest.id DESC
                    LIMIT %s
                    """,
                    (max(1, min(int(limit or 100), 500)),),
                )
                rows = cur.fetchall()
        finally:
            _put_pg_conn(conn)

        invalidated: list[dict[str, Any]] = []
        for row in rows:
            evidence = _evidence_row_to_dict(row[:20])
            previous_status = str(row[20] or "observing").lower()
            if is_passing_gap_evidence(evidence):
                continue
            reason = "Latest persisted answer evidence no longer satisfies fixed/observing criteria"
            metadata_patch = {
                "triage_action": "reopen_invalid_fixed_state",
                "triage_reason": reason,
                "triage_actor": actor,
                "invalidated_evidence_id": evidence.get("id"),
                "invalidated_outcome_code": evidence.get("outcome_code"),
                "invalidated_decision": evidence.get("decision"),
            }
            self.update_gap_status(
                gap_key=str(evidence["gap_key"]),
                status="open",
                reason=reason,
                actor=actor,
                metadata_patch=metadata_patch,
            )
            self.project_current_state_from_evidence(
                gap_key=str(evidence["gap_key"]),
                evidence={
                    **evidence,
                    "quality": "failure",
                    "refused": True,
                    "outcome_code": "FIXED_STATE_INVALIDATED",
                },
                actor=actor,
                decision="reopen_invalid_fixed_state",
                evidence_id=int(evidence["id"]),
            )
            transition = self.insert_transition(
                gap_key=str(evidence["gap_key"]),
                from_status=previous_status,
                to_status="open",
                action="reopen_invalid_fixed_state",
                actor=actor,
                reason=reason,
                evidence_id=int(evidence["id"]),
            )
            invalidated.append(
                {
                    "gap_key": evidence["gap_key"],
                    "from_status": previous_status,
                    "to_status": "open",
                    "evidence_id": evidence["id"],
                    "quality": evidence.get("quality"),
                    "refused": evidence.get("refused"),
                    "chunks_count": evidence.get("chunks_count"),
                    "decision": evidence.get("decision"),
                    "outcome_code": evidence.get("outcome_code"),
                    "transition_id": transition.get("id"),
                }
            )
        return invalidated

    def latest_evidence_map(self, gap_keys: Iterable[str]) -> dict[str, dict[str, Any]]:
        keys = [str(key) for key in gap_keys if key]
        if not keys:
            return {}
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT ON (gap_key)
                        id, gap_key, evidence_type, actor, source_run_id, consultation_run_id, session_id,
                        endpoint, query_text, answer_preview, chunks_count, refused, generic_answer,
                        quality, outcome_code, confidence, decision, decision_reason, raw_payload, created_at
                    FROM knowledge_gap_evidence
                    WHERE gap_key = ANY(%s)
                    ORDER BY gap_key, created_at DESC, id DESC
                    """,
                    (keys,),
                )
                rows = cur.fetchall()
        finally:
            _put_pg_conn(conn)
        return {row[1]: _evidence_row_to_dict(row) for row in rows}

    def fetch_evidence_history(self, gap_key: str, *, limit: int = 20) -> list[dict[str, Any]]:
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id, gap_key, evidence_type, actor, source_run_id, consultation_run_id, session_id,
                        endpoint, query_text, answer_preview, chunks_count, refused, generic_answer,
                        quality, outcome_code, confidence, decision, decision_reason, raw_payload, created_at
                    FROM knowledge_gap_evidence
                    WHERE gap_key = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (gap_key, max(1, min(int(limit or 20), 100))),
                )
                rows = cur.fetchall()
        finally:
            _put_pg_conn(conn)
        return [_evidence_row_to_dict(row) for row in rows]

    def fetch_recent_keep_open_evidence(
        self,
        gap_key: str,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id, gap_key, evidence_type, actor, source_run_id, consultation_run_id, session_id,
                        endpoint, query_text, answer_preview, chunks_count, refused, generic_answer,
                        quality, outcome_code, confidence, decision, decision_reason, raw_payload, created_at
                    FROM knowledge_gap_evidence
                    WHERE gap_key = %s
                      AND evidence_type = 'live_retest'
                      AND decision = 'keep_open'
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (gap_key, max(1, min(int(limit or 5), 20))),
                )
                rows = cur.fetchall()
        finally:
            _put_pg_conn(conn)
        return [_evidence_row_to_dict(row) for row in rows]

    def fetch_active_repair_task_keys(self, gap_keys: Iterable[str]) -> set[str]:
        keys = [str(key) for key in gap_keys if key]
        if not keys:
            return set()
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT gap_key
                    FROM knowledge_gap_repair_tasks
                    WHERE gap_key = ANY(%s)
                      AND status IN ('open', 'in_progress')
                    """,
                    (keys,),
                )
                rows = cur.fetchall()
        finally:
            _put_pg_conn(conn)
        return {str(row[0]) for row in rows}

    def fetch_active_repair_tasks_map(self, gap_keys: Iterable[str]) -> dict[str, dict[str, Any]]:
        keys = [str(key) for key in gap_keys if key]
        if not keys:
            return {}
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT ON (gap_key)
                        id, gap_key, task_type, status, actor, reason, latest_evidence_ids,
                        issue_number, issue_url, metadata, created_at, updated_at, resolved_at
                    FROM knowledge_gap_repair_tasks
                    WHERE gap_key = ANY(%s)
                      AND status IN ('open', 'in_progress')
                    ORDER BY gap_key, updated_at DESC, id DESC
                    """,
                    (keys,),
                )
                rows = cur.fetchall()
        finally:
            _put_pg_conn(conn)
        return {
            str(row[1]): {
                "id": int(row[0]),
                "gap_key": row[1],
                "task_type": row[2],
                "status": row[3],
                "actor": row[4],
                "reason": row[5],
                "latest_evidence_ids": list(row[6] or []),
                "issue_number": row[7],
                "issue_url": row[8],
                "metadata": coerce_json_dict(row[9]),
                "created_at": normalize_epoch_milliseconds(row[10]),
                "updated_at": normalize_epoch_milliseconds(row[11]),
                "resolved_at": normalize_epoch_milliseconds(row[12]),
            }
            for row in rows
        }

    def create_repair_task(
        self,
        *,
        gap_key: str,
        task_type: str,
        actor: str,
        reason: str,
        latest_evidence_ids: list[int],
        issue_number: int | None = None,
        issue_url: str | None = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO knowledge_gap_repair_tasks (
                        gap_key, task_type, status, actor, reason, latest_evidence_ids,
                        issue_number, issue_url, metadata
                    )
                    VALUES (%s, %s, 'open', %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (gap_key, task_type)
                        WHERE status IN ('open', 'in_progress')
                    DO UPDATE SET
                        reason = EXCLUDED.reason,
                        latest_evidence_ids = EXCLUDED.latest_evidence_ids,
                        issue_number = COALESCE(EXCLUDED.issue_number, knowledge_gap_repair_tasks.issue_number),
                        issue_url = COALESCE(EXCLUDED.issue_url, knowledge_gap_repair_tasks.issue_url),
                        metadata = knowledge_gap_repair_tasks.metadata || EXCLUDED.metadata,
                        updated_at = NOW()
                    RETURNING
                        id, gap_key, task_type, status, actor, reason, latest_evidence_ids,
                        issue_number, issue_url, metadata, created_at, updated_at, resolved_at
                    """,
                    (
                        gap_key,
                        task_type,
                        actor,
                        reason,
                        latest_evidence_ids,
                        issue_number,
                        issue_url,
                        Json(metadata or {}),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _put_pg_conn(conn)
        return {
            "id": int(row[0]),
            "gap_key": row[1],
            "task_type": row[2],
            "status": row[3],
            "actor": row[4],
            "reason": row[5],
            "latest_evidence_ids": list(row[6] or []),
            "issue_number": row[7],
            "issue_url": row[8],
            "metadata": coerce_json_dict(row[9]),
            "created_at": normalize_epoch_milliseconds(row[10]),
            "updated_at": normalize_epoch_milliseconds(row[11]),
            "resolved_at": normalize_epoch_milliseconds(row[12]),
        }

    def fetch_transition_history(self, gap_key: str, *, limit: int = 20) -> list[dict[str, Any]]:
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, gap_key, from_status, to_status, action, actor, reason, evidence_id, occurred_at
                    FROM knowledge_gap_transitions
                    WHERE gap_key = %s
                    ORDER BY occurred_at DESC, id DESC
                    LIMIT %s
                    """,
                    (gap_key, max(1, min(int(limit or 20), 100))),
                )
                rows = cur.fetchall()
        finally:
            _put_pg_conn(conn)
        return [_transition_row_to_dict(row) for row in rows]

    def latest_gap_retest_run(self) -> Optional[dict[str, Any]]:
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT run_id, run_type, status, ts, result
                    FROM learning_runs
                    WHERE run_id LIKE 'run_gap_retest_%'
                    ORDER BY ts DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
        finally:
            _put_pg_conn(conn)
        if not row:
            return None
        result = row[4]
        if isinstance(result, str):
            result = json.loads(result)
        return {
            "run_id": row[0],
            "run_type": row[1],
            "status": row[2],
            "ts": normalize_epoch_milliseconds(row[3]),
            "result": coerce_json_dict(result),
        }

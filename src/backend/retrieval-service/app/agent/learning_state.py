"""
Shared persistence helpers for the learning loop.

This module keeps knowledge gap state and resumable executor state in one place
so scheduler, API endpoints, and executor updates stay consistent.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

GAP_STATUS_VALUES = {"open", "in_progress", "observing", "resolved", "blocked"}
REOPENABLE_GAP_STATUSES = {"observing", "resolved", "blocked"}
DEFAULT_OBSERVATION_WINDOW_DAYS = 7
GAP_SCOPE_VALUES = {"user", "agent", "project", "global"}
SECONDS_EPOCH_THRESHOLD = 100_000_000_000

_SOURCE_BY_CATEGORY = {
    "tool_failure": "failure",
    "low_quality": "feedback",
    "diversity_issue": "repeat_question",
    "contract_violation": "contract_violation",
    "topo_anomaly": "topology",
    "prompt_issue": "problem",
    "routing_error": "problem",
}

_QUALITY_BY_SEVERITY = {
    "high": "failure",
    "medium": "weak",
    "low": "weak",
}

_SCOPE_PRIORITY = {
    "user": 5,
    "agent": 10,
    "project": 15,
    "global": 20,
}


def _get_pool(pool=None):
    if pool is not None:
        return pool

    from app.agent.tools import _get_pool

    return _get_pool()


def _get_db_conn(pool=None):
    return _get_pool(pool).getconn()


def _put_db_conn(conn, pool=None, error: bool = False):
    try:
        _get_pool(pool).putconn(conn, close=error)
    except Exception as exc:
        logger.warning("Failed to return learning-state DB connection: %s", exc)


def coerce_json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except Exception:
            return {}
        if isinstance(loaded, dict):
            return loaded
    return {}


def normalize_epoch_milliseconds(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric <= 0:
            return None
        if numeric < SECONDS_EPOCH_THRESHOLD:
            return int(numeric * 1000)
        return int(numeric)
    if isinstance(value, str):
        trimmed = value.strip()
        if not trimmed:
            return None
        if re.fullmatch(r"\d+(\.\d+)?", trimmed):
            return normalize_epoch_milliseconds(float(trimmed))
        try:
            normalized = trimmed.replace("Z", "+00:00")
            return int(datetime.fromisoformat(normalized).timestamp() * 1000)
        except ValueError:
            return None
    return None


_KNOWLEDGE_GAP_RETURNING_COLUMNS = """
gap_key, problem_id, description, source, affected_route, query_text, status, quality,
resolution_plan, related_issue_url, confidence, metadata, created_at, updated_at, resolved_at,
verified_at, observation_until, last_reopened_at, scope_type, scope_id, cluster_id,
cause_type, priority, owner, reopen_count, linked_event_id, first_seen_at, last_seen_at
"""


def _knowledge_gap_row_to_snapshot(row: Any) -> Dict[str, Any]:
    metadata = coerce_json_dict(row[11])
    return {
        "gap_key": row[0],
        "problem_id": row[1],
        "description": row[2],
        "source": row[3],
        "affected_route": row[4],
        "query_text": row[5],
        "status": row[6],
        "quality": row[7],
        "resolution_plan": row[8],
        "related_issue_url": row[9],
        "confidence": float(row[10] or 0.0),
        "metadata": metadata,
        "created_at": row[12],
        "updated_at": row[13],
        "resolved_at": row[14],
        "verified_at": row[15],
        "observation_until": row[16],
        "last_reopened_at": row[17],
        "scope_type": row[18],
        "scope_id": row[19],
        "cluster_id": row[20],
        "cause_type": row[21],
        "priority": int(row[22] or 0),
        "owner": row[23],
        "reopen_count": int(row[24] or 0),
        "linked_event_id": row[25],
        "first_seen_at": row[26],
        "last_seen_at": row[27],
    }


def _hash_key(value: str, prefix: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _normalize_text(value: str) -> str:
    lowered = value.lower().strip()
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", lowered)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _build_run_gap_key(query: str) -> str:
    return _hash_key(_normalize_text(query) or query, "run")


def _build_cluster_id(parts: Iterable[str], prefix: str = "cluster") -> str:
    material = "|".join(part for part in parts if part).strip("|")
    return _hash_key(material or "unclassified", prefix)


def _derive_scope(scope_type: Optional[str], scope_id: Optional[str], *, fallback: str) -> tuple[str, str]:
    normalized_scope = (scope_type or fallback).strip().lower()
    if normalized_scope not in GAP_SCOPE_VALUES:
        normalized_scope = fallback
    return normalized_scope, (scope_id or fallback).strip() or fallback


def _derive_priority(
    *,
    confidence: float,
    severity: Optional[str] = None,
    quality: Optional[str] = None,
    refused: bool = False,
    frequency: int = 1,
    scope_type: str = "project",
) -> int:
    score = min(60, int(round(max(0.0, confidence) * 60)))
    severity_bonus = {"high": 20, "medium": 12, "low": 6}.get((severity or "").lower(), 8)
    quality_bonus = {"failure": 12, "weak": 6}.get((quality or "").lower(), 0)
    frequency_bonus = min(12, max(0, frequency - 1) * 3)
    refused_bonus = 8 if refused else 0
    scope_bonus = _SCOPE_PRIORITY.get(scope_type, 0)
    return min(100, score + severity_bonus + quality_bonus + frequency_bonus + refused_bonus + scope_bonus)


def _should_reopen_gap(
    *,
    existing_status: str,
    incoming_status: str,
    verified_at: Optional[datetime],
    incoming_last_seen_at: Optional[datetime],
) -> bool:
    normalized_existing = str(existing_status or "").lower()
    normalized_incoming = str(incoming_status or "").lower()
    if normalized_existing not in REOPENABLE_GAP_STATUSES:
        return False
    if normalized_incoming not in {"open", "in_progress"}:
        return False
    if verified_at is None:
        return True
    if incoming_last_seen_at is None:
        return False
    return incoming_last_seen_at > verified_at


def build_problem_gap_records(
    problems: Iterable[Dict[str, Any]], run_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for problem in problems:
        if not isinstance(problem, dict):
            continue

        gap_key = problem.get("suggested_gap_id") or f"problem_{problem.get('problem_id', 'unknown')}"
        severity = str(problem.get("severity") or "medium").lower()
        category = str(problem.get("category") or "problem").lower()
        problem_id = problem.get("problem_id")
        confidence = float(problem.get("confidence") or 0.0)
        ts_ms = normalize_epoch_milliseconds(problem.get("ts") or problem.get("created_at"))
        scope_type, scope_id = _derive_scope(
            problem.get("scope_type"),
            problem.get("scope_id") or problem.get("affected_route"),
            fallback="project",
        )
        cluster_id = problem.get("cluster_id") or _build_cluster_id(
            [
                category,
                problem.get("affected_route") or "",
                gap_key,
            ]
        )
        evidence = problem.get("evidence") or []
        records.append(
            {
                "gap_key": gap_key,
                "problem_id": problem_id,
                "description": problem.get("description") or problem_id or gap_key,
                "source": _SOURCE_BY_CATEGORY.get(category, "problem"),
                "affected_route": problem.get("affected_route"),
                "query_text": problem.get("description") or problem_id or gap_key,
                "status": "open",
                "quality": _QUALITY_BY_SEVERITY.get(severity, "weak"),
                "confidence": confidence,
                "created_at_ms": ts_ms,
                "first_seen_at_ms": ts_ms,
                "last_seen_at_ms": ts_ms,
                "resolution_plan": None,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "cluster_id": cluster_id,
                "cause_type": category,
                "priority": _derive_priority(
                    confidence=confidence,
                    severity=severity,
                    quality=_QUALITY_BY_SEVERITY.get(severity, "weak"),
                    frequency=max(1, len(evidence)),
                    scope_type=scope_type,
                ),
                "owner": None,
                "linked_event_id": None,
                "metadata": {
                    "problem_id": problem_id,
                    "category": category,
                    "severity": severity,
                    "evidence": evidence,
                    "evidence_count": len(evidence),
                    "additional_context": problem.get("additional_context") or {},
                    "source_run_id": run_id,
                },
            }
        )
    return records


def build_learning_run_gap_records(runs: Iterable[Dict[str, Any]], limit: int = 30) -> List[Dict[str, Any]]:
    clusters: Dict[str, Dict[str, Any]] = {}

    for run in reversed(list(runs)):
        if not isinstance(run, dict):
            continue
        quality = str(run.get("quality") or "").lower()
        if quality not in {"failure", "weak"}:
            continue

        query = str(run.get("query") or "").strip()
        if not query:
            continue

        normalized_query = _normalize_text(query) or query
        cluster_id = _build_cluster_id(
            [
                str(run.get("query_type") or "unknown"),
                normalized_query,
            ],
            prefix="cluster",
        )
        gap_key = _build_run_gap_key(query)
        ts_ms = normalize_epoch_milliseconds(run.get("ts"))
        runtime = run.get("runtime") or {}
        session_id = run.get("session_id")
        scope_type, scope_id = _derive_scope(
            "user" if session_id else "agent",
            session_id or runtime.get("model") or runtime.get("provider") or "retrieval-agent",
            fallback="agent",
        )

        existing = clusters.get(cluster_id)
        if existing is None:
            clusters[cluster_id] = {
                "gap_key": gap_key,
                "problem_id": None,
                "description": query,
                "source": "run",
                "affected_route": None,
                "query_text": query,
                "status": "open" if quality == "failure" else "in_progress",
                "quality": quality,
                "confidence": float((run.get("evaluation") or {}).get("confidence") or 0.0),
                "created_at_ms": ts_ms,
                "first_seen_at_ms": ts_ms,
                "last_seen_at_ms": ts_ms,
                "resolution_plan": None,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "cluster_id": cluster_id,
                "cause_type": "coverage_gap" if bool(run.get("refused")) else "answer_quality_gap",
                "priority": 0,
                "owner": None,
                "linked_event_id": None,
                "metadata": {
                    "answer_preview": (run.get("answer") or "")[:200],
                    "chunks_count": int(run.get("chunks_count") or 0),
                    "refused": bool(run.get("refused")),
                    "query_type": run.get("query_type"),
                    "runtime": runtime,
                    "sample_queries": [query],
                    "frequency": 1,
                },
            }
            existing = clusters[cluster_id]
        else:
            existing["last_seen_at_ms"] = max(existing.get("last_seen_at_ms") or 0, ts_ms or 0) or existing.get(
                "last_seen_at_ms"
            )
            existing["created_at_ms"] = existing["last_seen_at_ms"]
            existing["quality"] = "failure" if quality == "failure" else existing["quality"]
            existing["status"] = "open" if quality == "failure" else existing["status"]
            existing["confidence"] = max(existing.get("confidence") or 0.0, float((run.get("evaluation") or {}).get("confidence") or 0.0))
            metadata = existing["metadata"]
            metadata["chunks_count"] = max(int(metadata.get("chunks_count") or 0), int(run.get("chunks_count") or 0))
            metadata["refused"] = bool(metadata.get("refused")) or bool(run.get("refused"))
            metadata["frequency"] = int(metadata.get("frequency") or 1) + 1
            sample_queries = metadata.setdefault("sample_queries", [])
            if query not in sample_queries and len(sample_queries) < 5:
                sample_queries.append(query)

    records: List[Dict[str, Any]] = []
    for cluster in clusters.values():
        metadata = cluster["metadata"]
        cluster["priority"] = _derive_priority(
            confidence=float(cluster.get("confidence") or 0.0),
            quality=cluster.get("quality"),
            refused=bool(metadata.get("refused")),
            frequency=int(metadata.get("frequency") or 1),
            scope_type=cluster.get("scope_type") or "agent",
        )
        records.append(cluster)

    records.sort(
        key=lambda item: (
            -(item.get("priority") or 0),
            -(item.get("last_seen_at_ms") or 0),
        )
    )
    return records[:limit]


def upsert_knowledge_gap_records(records: Iterable[Dict[str, Any]], pool=None) -> int:
    record_list = [record for record in records if isinstance(record, dict) and record.get("gap_key")]
    if not record_list:
        return 0

    conn = _get_db_conn(pool=pool)
    upserted = 0
    try:
        from app.agent.event_ledger import insert_knowledge_gap_event

        cursor = conn.cursor()
        for record in record_list:
            status = str(record.get("status") or "open").lower()
            if status not in GAP_STATUS_VALUES:
                status = "open"

            scope_type, scope_id = _derive_scope(
                record.get("scope_type"),
                record.get("scope_id"),
                fallback="project",
            )
            priority = int(record.get("priority") or 0)
            metadata_json = json.dumps(record.get("metadata") or {}, ensure_ascii=False)
            created_at_ms = normalize_epoch_milliseconds(record.get("created_at_ms"))
            first_seen_at_ms = normalize_epoch_milliseconds(record.get("first_seen_at_ms")) or created_at_ms
            last_seen_at_ms = normalize_epoch_milliseconds(record.get("last_seen_at_ms")) or created_at_ms
            cursor.execute(
                f"""
                INSERT INTO knowledge_gaps
                    (
                        gap_key, problem_id, description, source, affected_route, query_text, status, quality,
                        resolution_plan, related_issue_url, confidence, metadata, created_at, updated_at,
                        scope_type, scope_id, cluster_id, cause_type, priority, owner, linked_event_id,
                        first_seen_at, last_seen_at
                    )
                VALUES
                    (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s::jsonb, COALESCE(to_timestamp(%s / 1000.0), NOW()), NOW(),
                        %s, %s, %s, %s, %s, %s, %s,
                        COALESCE(to_timestamp(%s / 1000.0), COALESCE(to_timestamp(%s / 1000.0), NOW())),
                        COALESCE(to_timestamp(%s / 1000.0), COALESCE(to_timestamp(%s / 1000.0), NOW()))
                    )
                ON CONFLICT (gap_key) DO UPDATE SET
                    problem_id = COALESCE(EXCLUDED.problem_id, knowledge_gaps.problem_id),
                    description = EXCLUDED.description,
                    source = EXCLUDED.source,
                    affected_route = COALESCE(EXCLUDED.affected_route, knowledge_gaps.affected_route),
                    query_text = COALESCE(EXCLUDED.query_text, knowledge_gaps.query_text),
                    quality = COALESCE(EXCLUDED.quality, knowledge_gaps.quality),
                    confidence = GREATEST(COALESCE(knowledge_gaps.confidence, 0), COALESCE(EXCLUDED.confidence, 0)),
                    metadata = COALESCE(knowledge_gaps.metadata, '{{}}'::jsonb) || EXCLUDED.metadata,
                    scope_type = COALESCE(EXCLUDED.scope_type, knowledge_gaps.scope_type),
                    scope_id = COALESCE(EXCLUDED.scope_id, knowledge_gaps.scope_id),
                    cluster_id = COALESCE(EXCLUDED.cluster_id, knowledge_gaps.cluster_id),
                    cause_type = COALESCE(EXCLUDED.cause_type, knowledge_gaps.cause_type),
                    priority = GREATEST(COALESCE(knowledge_gaps.priority, 0), COALESCE(EXCLUDED.priority, 0)),
                    owner = COALESCE(knowledge_gaps.owner, EXCLUDED.owner),
                    linked_event_id = COALESCE(EXCLUDED.linked_event_id, knowledge_gaps.linked_event_id),
                    first_seen_at = COALESCE(knowledge_gaps.first_seen_at, EXCLUDED.first_seen_at),
                    last_seen_at = GREATEST(COALESCE(knowledge_gaps.last_seen_at, EXCLUDED.last_seen_at), EXCLUDED.last_seen_at),
                    updated_at = NOW(),
                    reopen_count = CASE
                        WHEN knowledge_gaps.status IN ('observing', 'resolved', 'blocked')
                             AND EXCLUDED.status IN ('open', 'in_progress')
                             AND (
                                 knowledge_gaps.verified_at IS NULL
                                 OR EXCLUDED.last_seen_at > knowledge_gaps.verified_at
                             )
                        THEN COALESCE(knowledge_gaps.reopen_count, 0) + 1
                        ELSE COALESCE(knowledge_gaps.reopen_count, 0)
                    END,
                    status = CASE
                        WHEN knowledge_gaps.status IN ('observing', 'resolved', 'blocked')
                             AND EXCLUDED.status IN ('open', 'in_progress')
                             AND (
                                 knowledge_gaps.verified_at IS NULL
                                 OR EXCLUDED.last_seen_at > knowledge_gaps.verified_at
                             )
                        THEN EXCLUDED.status
                        WHEN knowledge_gaps.status = 'resolved' AND EXCLUDED.status = 'resolved'
                        THEN 'resolved'
                        ELSE COALESCE(knowledge_gaps.status, EXCLUDED.status)
                    END,
                    resolution_plan = CASE
                        WHEN knowledge_gaps.status IN ('observing', 'resolved', 'blocked')
                             AND EXCLUDED.status IN ('open', 'in_progress')
                             AND (
                                 knowledge_gaps.verified_at IS NULL
                                 OR EXCLUDED.last_seen_at > knowledge_gaps.verified_at
                             )
                        THEN NULL
                        ELSE COALESCE(knowledge_gaps.resolution_plan, EXCLUDED.resolution_plan)
                    END,
                    resolved_at = CASE
                        WHEN knowledge_gaps.status IN ('observing', 'resolved', 'blocked')
                             AND EXCLUDED.status IN ('open', 'in_progress')
                             AND (
                                 knowledge_gaps.verified_at IS NULL
                                 OR EXCLUDED.last_seen_at > knowledge_gaps.verified_at
                             )
                        THEN NULL
                        WHEN EXCLUDED.status IN ('resolved', 'blocked')
                        THEN COALESCE(knowledge_gaps.resolved_at, NOW())
                        ELSE knowledge_gaps.resolved_at
                    END,
                    observation_until = CASE
                        WHEN knowledge_gaps.status IN ('observing', 'resolved', 'blocked')
                             AND EXCLUDED.status IN ('open', 'in_progress')
                             AND (
                                 knowledge_gaps.verified_at IS NULL
                                 OR EXCLUDED.last_seen_at > knowledge_gaps.verified_at
                             )
                        THEN NULL
                        ELSE knowledge_gaps.observation_until
                    END,
                    last_reopened_at = CASE
                        WHEN knowledge_gaps.status IN ('observing', 'resolved', 'blocked')
                             AND EXCLUDED.status IN ('open', 'in_progress')
                             AND (
                                 knowledge_gaps.verified_at IS NULL
                                 OR EXCLUDED.last_seen_at > knowledge_gaps.verified_at
                             )
                        THEN NOW()
                        ELSE knowledge_gaps.last_reopened_at
                    END
                RETURNING
                    {_KNOWLEDGE_GAP_RETURNING_COLUMNS}
                """,
                (
                    record["gap_key"],
                    record.get("problem_id"),
                    record.get("description") or record["gap_key"],
                    record.get("source") or "problem",
                    record.get("affected_route"),
                    record.get("query_text"),
                    status,
                    record.get("quality"),
                    record.get("resolution_plan"),
                    record.get("related_issue_url"),
                    float(record.get("confidence") or 0.0),
                    metadata_json,
                    created_at_ms,
                    scope_type,
                    scope_id,
                    record.get("cluster_id"),
                    record.get("cause_type"),
                    priority,
                    record.get("owner"),
                    record.get("linked_event_id"),
                    first_seen_at_ms,
                    created_at_ms,
                    last_seen_at_ms,
                    created_at_ms,
                ),
            )
            snapshot_row = cursor.fetchone()
            if snapshot_row:
                snapshot = _knowledge_gap_row_to_snapshot(snapshot_row)
                insert_knowledge_gap_event(
                    cursor,
                    gap_key=str(snapshot["gap_key"]),
                    event_type="knowledge.gap.upserted",
                    snapshot=snapshot,
                    occurred_at=snapshot.get("updated_at"),
                )
            upserted += 1
        conn.commit()
        cursor.close()
        return upserted
    except Exception:
        conn.rollback()
        raise
    finally:
        _put_db_conn(conn, pool=pool)


def summarize_knowledge_gaps(gaps: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    gap_list = list(gaps)
    status_counts = Counter(str(gap.get("status") or "open") for gap in gap_list)
    cluster_ids = {gap.get("cluster_id") for gap in gap_list if gap.get("cluster_id")}
    return {
        "total": len(gap_list),
        "open": status_counts.get("open", 0),
        "in_progress": status_counts.get("in_progress", 0),
        "observing": status_counts.get("observing", 0),
        "resolved": status_counts.get("resolved", 0),
        "blocked": status_counts.get("blocked", 0),
        "cluster_count": len(cluster_ids),
    }


def fetch_knowledge_gaps(
    *,
    limit: int = 30,
    status: Optional[str] = None,
    statuses: Optional[Iterable[str]] = None,
    scope_type: Optional[str] = None,
    cause_type: Optional[str] = None,
    cluster_id: Optional[str] = None,
    pool=None,
) -> List[Dict[str, Any]]:
    conn = _get_db_conn(pool=pool)
    try:
        cursor = conn.cursor()
        clauses = []
        params: List[Any] = []
        if status:
            clauses.append("status = %s")
            params.append(status)
        if statuses:
            normalized_statuses = [str(value).lower() for value in statuses if value]
            if normalized_statuses:
                clauses.append("status = ANY(%s)")
                params.append(normalized_statuses)
        if scope_type:
            clauses.append("scope_type = %s")
            params.append(scope_type)
        if cause_type:
            clauses.append("cause_type = %s")
            params.append(cause_type)
        if cluster_id:
            clauses.append("cluster_id = %s")
            params.append(cluster_id)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor.execute(
            f"""
            SELECT
                gap_key, problem_id, description, source, affected_route, query_text, status, quality,
                resolution_plan, confidence, metadata, created_at, updated_at, resolved_at,
                verified_at, observation_until, last_reopened_at, scope_type, scope_id, cluster_id,
                cause_type, priority, owner, reopen_count, linked_event_id, first_seen_at, last_seen_at
            FROM knowledge_gaps
            {where_sql}
            ORDER BY priority DESC, last_seen_at DESC, updated_at DESC
            LIMIT %s
            """,
            (*params, max(1, min(limit, 200))),
        )
        rows = cursor.fetchall()
        cursor.close()
    finally:
        _put_db_conn(conn, pool=pool)

    gaps: List[Dict[str, Any]] = []
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
                "ts": normalize_epoch_milliseconds(row[26] or row[11]),
            }
        )
    return gaps


def fetch_knowledge_gap_status_map(gap_keys: Iterable[str], pool=None) -> Dict[str, Dict[str, Any]]:
    keys = [key for key in gap_keys if key]
    if not keys:
        return {}

    conn = _get_db_conn(pool=pool)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                gap_key, status, resolution_plan, confidence, resolved_at, verified_at,
                observation_until, last_reopened_at, updated_at, scope_type, scope_id,
                cluster_id, cause_type, priority, reopen_count, linked_event_id
            FROM knowledge_gaps
            WHERE gap_key = ANY(%s)
            """,
            (keys,),
        )
        rows = cursor.fetchall()
        cursor.close()
    finally:
        _put_db_conn(conn, pool=pool)

    return {
        row[0]: {
            "status": row[1],
            "resolution_plan": row[2],
            "confidence": float(row[3] or 0.0),
            "resolved_at": normalize_epoch_milliseconds(row[4]),
            "verified_at": normalize_epoch_milliseconds(row[5]),
            "observation_until": normalize_epoch_milliseconds(row[6]),
            "last_reopened_at": normalize_epoch_milliseconds(row[7]),
            "updated_at": normalize_epoch_milliseconds(row[8]),
            "scope_type": row[9],
            "scope_id": row[10],
            "cluster_id": row[11],
            "cause_type": row[12],
            "priority": int(row[13] or 0),
            "reopen_count": int(row[14] or 0),
            "linked_event_id": row[15],
        }
        for row in rows
    }


def link_knowledge_gap_event(
    gap_key: Optional[str],
    event_id: int,
    *,
    status: Optional[str] = None,
    owner: Optional[str] = None,
    note: Optional[str] = None,
    pool=None,
) -> bool:
    if not gap_key:
        return False

    conn = _get_db_conn(pool=pool)
    try:
        from app.agent.event_ledger import insert_knowledge_gap_event

        cursor = conn.cursor()
        cursor.execute(
            f"""
            UPDATE knowledge_gaps
            SET linked_event_id = %s,
                owner = COALESCE(%s, owner),
                status = COALESCE(%s, status),
                resolution_plan = COALESCE(resolution_plan, %s),
                metadata = COALESCE(metadata, '{{}}'::jsonb) || %s::jsonb,
                updated_at = NOW()
            WHERE gap_key = %s
            RETURNING
                {_KNOWLEDGE_GAP_RETURNING_COLUMNS}
            """,
            (
                event_id,
                owner,
                status,
                note,
                json.dumps({"linked_event_id": event_id}, ensure_ascii=False),
                gap_key,
            ),
        )
        updated = cursor.rowcount > 0
        snapshot_row = cursor.fetchone() if updated else None
        if snapshot_row:
            snapshot = _knowledge_gap_row_to_snapshot(snapshot_row)
            insert_knowledge_gap_event(
                cursor,
                gap_key=str(snapshot["gap_key"]),
                event_type="knowledge.gap.linked",
                snapshot=snapshot,
                occurred_at=snapshot.get("updated_at"),
            )
        conn.commit()
        cursor.close()
        return updated
    except Exception:
        conn.rollback()
        raise
    finally:
        _put_db_conn(conn, pool=pool)


def update_knowledge_gap_status(
    gap_key: Optional[str],
    status: str,
    resolution_plan: str,
    *,
    metadata_patch: Optional[Dict[str, Any]] = None,
    linked_event_id: Optional[int] = None,
    owner: Optional[str] = None,
    observation_window_days: int = DEFAULT_OBSERVATION_WINDOW_DAYS,
    pool=None,
) -> bool:
    if not gap_key:
        return False

    normalized_status = str(status or "open").lower()
    if normalized_status not in GAP_STATUS_VALUES:
        raise ValueError(f"Invalid knowledge gap status: {status}")

    conn = _get_db_conn(pool=pool)
    try:
        from app.agent.event_ledger import insert_knowledge_gap_event

        cursor = conn.cursor()
        cursor.execute(
            f"""
            UPDATE knowledge_gaps
            SET status = %s,
                resolution_plan = %s,
                linked_event_id = COALESCE(%s, linked_event_id),
                owner = COALESCE(%s, owner),
                metadata = COALESCE(metadata, '{{}}'::jsonb) || %s::jsonb,
                updated_at = NOW(),
                last_seen_at = NOW(),
                resolved_at = CASE
                    WHEN %s IN ('resolved', 'blocked') THEN NOW()
                    WHEN %s IN ('open', 'in_progress', 'observing') THEN NULL
                    ELSE NULL
                END,
                verified_at = CASE
                    WHEN %s IN ('observing', 'resolved', 'blocked') THEN NOW()
                    ELSE verified_at
                END,
                observation_until = CASE
                    WHEN %s = 'observing' THEN NOW() + (%s * INTERVAL '1 day')
                    WHEN %s IN ('open', 'in_progress') THEN NULL
                    ELSE observation_until
                END
            WHERE gap_key = %s
            RETURNING
                {_KNOWLEDGE_GAP_RETURNING_COLUMNS}
            """,
            (
                normalized_status,
                resolution_plan,
                linked_event_id,
                owner,
                json.dumps(metadata_patch or {}, ensure_ascii=False),
                normalized_status,
                normalized_status,
                normalized_status,
                normalized_status,
                max(1, int(observation_window_days or DEFAULT_OBSERVATION_WINDOW_DAYS)),
                normalized_status,
                gap_key,
            ),
        )
        updated = cursor.rowcount > 0
        snapshot_row = cursor.fetchone() if updated else None
        if snapshot_row:
            snapshot = _knowledge_gap_row_to_snapshot(snapshot_row)
            insert_knowledge_gap_event(
                cursor,
                gap_key=str(snapshot["gap_key"]),
                event_type="knowledge.gap.status_updated",
                snapshot=snapshot,
                occurred_at=snapshot.get("updated_at"),
            )
        conn.commit()
        cursor.close()
        return updated
    except Exception:
        conn.rollback()
        raise
    finally:
        _put_db_conn(conn, pool=pool)


def list_resumable_improvement_event_ids(limit: int = 50, pool=None) -> List[int]:
    conn = _get_db_conn(pool=pool)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id
            FROM improvement_events
            WHERE reverted_at IS NULL
              AND COALESCE(verification_result->>'status', '') != 'failed'
              AND (
                    (
                        COALESCE(patch_payload->'review'->>'status', 'pending_review') = 'approved'
                        AND applied_at IS NULL
                    )
                    OR (
                        applied_at IS NOT NULL
                        AND verified_at IS NULL
                        AND COALESCE(patch_payload->'review'->>'status', 'pending_review') != 'rejected'
                    )
                  )
            ORDER BY ts ASC
            LIMIT %s
            """,
            (max(1, min(limit, 200)),),
        )
        rows = cursor.fetchall()
        cursor.close()
    finally:
        _put_db_conn(conn, pool=pool)

    return [int(row[0]) for row in rows]

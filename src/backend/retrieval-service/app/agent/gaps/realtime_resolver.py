"""F3 (#135): Agent 主链路答对题时，实时找到匹配的知识缺口并触发 lifecycle 决策。

不依赖 5 分钟 listener 慢轮询。在 synthesize_node 完成后 fire-and-forget 调用。

设计原则：
- 永不阻塞主响应：内部用 threading.Thread(daemon=True) 后台执行
- 永不抛异常：所有失败 swallow + log，不影响 agent 返回
- 严格匹配：query_text 精确相等（避免误 resolve 不相关 gap）
- 复用 lifecycle.decide_from_live_retest：保持决策语义一致
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


def try_resolve_gap_for_answer(
    *,
    query: str,
    final_answer: str,
    chunks: list[dict[str, Any]],
    confidence: float,
    information_gain: float,
    refused: bool,
    actor: str = "agent_realtime",
) -> None:
    """Fire-and-forget 入口：从 agent 主链路调用。无返回值，错误吞掉。"""
    if not query or not query.strip():
        return
    # 主链路质量判定：跟 synthesize_node 内 _q 计算口径一致
    if refused or not chunks:
        return  # 失败/无证据，不动 gap
    quality = "good" if (confidence >= 0.5 and information_gain >= 0.3) else "weak"
    if quality != "good":
        return  # 只有 good 才触发 resolve 流程

    payload = {
        "query": query,
        "answer": final_answer,
        "chunks_count": len(chunks),
        "confidence": float(confidence),
        "quality": quality,
        "refused": refused,
        "actor": actor,
    }
    # daemon=True 让进程退出时不被它阻塞
    threading.Thread(target=_resolve_in_background, args=(payload,), daemon=True).start()


def _resolve_in_background(payload: dict[str, Any]) -> None:
    try:
        from app.agent.gaps.repository import KnowledgeGapRepository
        from app.agent.gaps.lifecycle import decide_from_live_retest

        repo = KnowledgeGapRepository()
        # 严格 query_text 相等匹配 + 仅 active 缺口（open/in_progress/observing）
        gap = _find_matching_active_gap(repo, payload["query"])
        if not gap:
            return

        # 构造一份与 GapRetestService 兼容的 evidence
        evidence = {
            "ok": True,
            "quality": payload["quality"],  # 'good'
            "refused": payload["refused"],
            "generic_answer": False,
            "chunks_count": payload["chunks_count"],
            "outcome_code": "ANSWERED_OK",
            "answer_preview": (payload["answer"] or "")[:500],
            "confidence": payload["confidence"],
            "source": "agent_realtime",
        }
        decision = decide_from_live_retest(gap, evidence)
        action = str(decision.get("action") or "unknown")
        new_status = str(decision.get("status") or gap.get("status") or "open").lower()
        prev_status = str(gap.get("status") or "open").lower()
        gap_key = str(gap.get("gap_key") or "")

        if action == "keep_open":
            # 没新状态可改，不写 evidence（避免 schema 噪音）
            return

        evidence_row = repo.insert_evidence(
            gap_key=gap_key,
            evidence_type="agent_realtime",
            actor=payload["actor"],
            evidence=evidence,
            decision=action,
            decision_reason=str(decision.get("reason") or ""),
        )
        repo.project_current_state_from_evidence(
            gap_key=gap_key,
            evidence=evidence,
            actor=payload["actor"],
            decision=action,
            evidence_id=evidence_row.get("id") if evidence_row else None,
        )
        if new_status != prev_status:
            repo.update_gap_status(
                gap_key=gap_key,
                status=new_status,
                reason=str(decision.get("reason") or ""),
                actor=payload["actor"],
                metadata_patch={
                    "triage_action": action,
                    "triage_reason": decision.get("reason"),
                    "triage_actor": payload["actor"],
                    "triage_mode": "agent_realtime",
                },
            )
            repo.insert_transition(
                gap_key=gap_key,
                from_status=prev_status,
                to_status=new_status,
                action=action,
                actor=payload["actor"],
                reason=str(decision.get("reason") or ""),
                evidence_id=evidence_row.get("id") if evidence_row else None,
            )
            logger.info(
                "agent_realtime_resolve gap_key=%s %s→%s action=%s",
                gap_key, prev_status, new_status, action,
            )
    except Exception as exc:
        logger.warning("agent_realtime_resolve_failed: %s", exc)


def _find_matching_active_gap(repo, query: str) -> dict[str, Any] | None:
    """直接打 DB 找 query_text 严格相等的 active gap。

    用 repository 现有连接，避免新开 pool。
    """
    try:
        # repository 暴露了 _get_pg_conn 风格的内部方法；为不污染上层 API，
        # 直接复用它做一次性查询。
        from app.agent.tools import _get_pg_conn, _put_pg_conn  # type: ignore
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        gap_key, problem_id, description, source, affected_route,
                        query_text, status, quality, resolution_plan, confidence,
                        metadata, created_at, updated_at, resolved_at, verified_at,
                        observation_until, last_reopened_at, scope_type, scope_id,
                        cluster_id, cause_type, priority, owner, reopen_count,
                        linked_event_id, first_seen_at, last_seen_at
                    FROM knowledge_gaps
                    WHERE status IN ('open', 'in_progress', 'observing')
                      AND query_text = %s
                    ORDER BY
                      CASE status WHEN 'observing' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END,
                      updated_at DESC
                    LIMIT 1
                    """,
                    (query,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                cols = [d[0] for d in cur.description]
                gap = dict(zip(cols, row))
                # 兼容 lifecycle 期望的 'query' 字段名
                gap["query"] = gap.get("query_text") or query
                return gap
        finally:
            try:
                _put_pg_conn(conn)
            except Exception:
                pass
    except Exception as exc:
        logger.debug("realtime_resolver._find_matching failed: %s", exc)
        return None

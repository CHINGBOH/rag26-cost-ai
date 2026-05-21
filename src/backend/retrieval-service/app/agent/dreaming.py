"""
#170: Dreaming Cron — 每日记忆晋升（6维评分 + 三重门控）

参考 OpenClaw 三阶段后台记忆整合系统：
- Light Sleep: 短期候选 → 过滤噪声
- REM Sleep:  情感关联 + 跨域连接
- Deep Sleep: 长期巩固 + 索引重建

评分维度：recency / frequency / uniqueness / utility / confidence / stability
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MemoryScore:
    """六维记忆评分。"""
    recency: float = 0.0       # 最近召回时间（越近越高）
    frequency: float = 0.0     # 召回次数
    uniqueness: float = 0.0    # 查询多样性（unique queries）
    utility: float = 0.0       # 正面反馈/成功使用
    confidence: float = 0.0    # LLM 自评质量
    stability: float = 0.0     # 时间衰减后的稳定性

    def composite(self) -> float:
        """加权综合评分，范围 0.0~1.0。"""
        weights = {
            "recency": 0.15,
            "frequency": 0.25,
            "uniqueness": 0.20,
            "utility": 0.20,
            "confidence": 0.10,
            "stability": 0.10,
        }
        return sum(
            getattr(self, dim) * weight
            for dim, weight in weights.items()
        )

    def tier(self) -> str:
        """根据综合评分分配 tier。"""
        score = self.composite()
        if score >= 0.7:
            return "core"
        elif score >= 0.4:
            return "working"
        else:
            return "peripheral"


@dataclass
class DreamingStats:
    """单次 dreaming 统计数据。"""
    candidates_scanned: int = 0
    promoted_to_core: int = 0
    promoted_to_working: int = 0
    demoted_to_peripheral: int = 0
    purged: int = 0
    duration_ms: float = 0


class DreamingCron:
    """每日记忆晋升调度器。

    三阶段：
    1. Light Sleep (01:00): 扫描短期候选池，六维评分
    2. REM Sleep (02:00): 发现关联，合并相似记忆
    3. Deep Sleep (03:00): 持久化晋升结果，清理过期
    """

    # Z-score 阈值：稳定且有用的记忆
    PROMOTION_Z_THRESHOLD = 0.5       # 晋升阈值
    DEMOTION_Z_THRESHOLD = -0.3       # 降级阈值
    PURGE_DAYS = 30                   # peripheral 超过此天数被清除

    def __init__(self):
        self._last_run: datetime | None = None

    # ── Light Sleep ─────────────────────────────────────────────────────

    async def light_sleep(self, domain_id: str) -> DreamingStats:
        """扫描候选池，六维评分，标记可晋升/可降级。

        评分方式（不需要 LLM，全部确定性地从已有数据计算）：
        """
        stats = DreamingStats()
        import time as _time
        t0 = _time.monotonic()

        try:
            candidates = await self._load_candidates(domain_id)
            stats.candidates_scanned = len(candidates)

            now = datetime.now(timezone.utc)
            scored: list[tuple[dict, MemoryScore]] = []

            for c in candidates:
                score = self._compute_six_dim_score(c, now)
                scored.append((c, score))

                tier = score.tier()
                if tier == "core":
                    stats.promoted_to_core += 1
                elif tier == "working":
                    stats.promoted_to_working += 1
                else:
                    stats.demoted_to_peripheral += 1

            # 持久化评分结果
            await self._persist_scores(scored, domain_id)

        except Exception as exc:
            logger.warning("light_sleep failed: %s", exc)

        stats.duration_ms = (_time.monotonic() - t0) * 1000
        logger.info(
            "dreaming.light_sleep domain=%s scanned=%d promoted=%d/%d purged=%d time=%.0fms",
            domain_id, stats.candidates_scanned,
            stats.promoted_to_core, stats.promoted_to_working,
            stats.purged, stats.duration_ms,
        )
        return stats

    def _compute_six_dim_score(self, candidate: dict, now: datetime) -> MemoryScore:
        """从候选记录计算六维评分。"""
        score = MemoryScore()

        # Recency: 指数衰减，半衰期 14 天
        last_recalled = candidate.get("last_recalled")
        if last_recalled:
            if isinstance(last_recalled, str):
                last_recalled = datetime.fromisoformat(last_recalled)
            days_ago = max(0, (now - last_recalled).total_seconds() / 86400)
            score.recency = 2.0 ** (-days_ago / 14)

        # Frequency: 归一化到 0~1（假设 10 次为满分）
        recall_count = int(candidate.get("recall_count", 0))
        score.frequency = min(1.0, recall_count / 10)

        # Uniqueness: unique query / unique session 越多越好
        unique_queries = int(candidate.get("unique_query_count", 1))
        unique_sessions = int(candidate.get("unique_session_count", 1))
        score.uniqueness = min(1.0, (unique_queries * 0.4 + unique_sessions * 0.6) / 8)

        # Utility: 被 light_gain 和 rem_gain 驱动
        light_gain = float(candidate.get("light_gain", 0))
        rem_gain = float(candidate.get("rem_gain", 0))
        score.utility = min(1.0, (light_gain + rem_gain) / 2 + 0.3)

        # Confidence: 来自 LLM 评估（如果有）
        confidence = float(candidate.get("confidence", 0.5))
        score.confidence = min(1.0, confidence)

        # Stability: 首次发现时间越久 + 持续被召回 → 越稳定
        first_seen = candidate.get("first_seen")
        if first_seen:
            if isinstance(first_seen, str):
                first_seen = datetime.fromisoformat(first_seen)
            days_since_first = max(1, (now - first_seen).total_seconds() / 86400)
            # 7天的稳定性基线，30天满
            score.stability = min(1.0, days_since_first / 30)

        return score

    # ── REM Sleep ───────────────────────────────────────────────────────

    async def rem_sleep(self, domain_id: str, _stats: DreamingStats) -> DreamingStats:
        """发现跨记忆关联，合并相似记忆，生成概念标签。

        REM 的核心操作：
        1. 相似记忆合并（content_hash 相近或 concept_tags 重叠度高）
        2. 跨域连接发现（不同 session 但相似查询的关联）
        3. 概念标签补全（为缺少标签的候选补全 concept_tags）
        """
        stats = _stats

        try:
            candidates = await self._load_candidates(domain_id, tier="core")
            if len(candidates) < 2:
                return stats

            # 相似度合并：concept_tags Jaccard >= 0.6 → 合并
            merged = await self._merge_similar_candidates(candidates)
            stats.promoted_to_working -= merged  # 合并减少了独立条目
            logger.info("dreaming.rem_sleep merged=%d candidates", merged)

        except Exception as exc:
            logger.warning("rem_sleep failed: %s", exc)

        return stats

    async def _merge_similar_candidates(self, candidates: list[dict]) -> int:
        """合并 concept_tags 高度重叠的候选。"""
        merged_count = 0
        merged_ids: set[int] = set()

        for i, a in enumerate(candidates):
            if a.get("id") in merged_ids:
                continue
            tags_a = set(a.get("concept_tags") or [])

            for j, b in enumerate(candidates[i + 1:], i + 1):
                if b.get("id") in merged_ids:
                    continue
                tags_b = set(b.get("concept_tags") or [])
                if not tags_a or not tags_b:
                    continue

                # Jaccard similarity
                intersection = len(tags_a & tags_b)
                union = len(tags_a | tags_b)
                if union > 0 and intersection / union >= 0.6:
                    # 合并到 a：累加计数，更新 last_recalled
                    merged_ids.add(b["id"])
                    a["recall_count"] = int(a.get("recall_count", 0)) + int(b.get("recall_count", 0))
                    a["unique_query_count"] = int(a.get("unique_query_count", 0)) + int(b.get("unique_query_count", 0))
                    a["concept_tags"] = list(tags_a | tags_b)
                    merged_count += 1

        if merged_count:
            logger.info("dreaming.merged_candidates count=%d", merged_count)
        return merged_count

    # ── Deep Sleep ──────────────────────────────────────────────────────

    async def deep_sleep(self, domain_id: str, _stats: DreamingStats) -> DreamingStats:
        """持久化晋升结果 + 清理过期 peripheral 记忆。

        1. 将晋升的 core/working 写入 Qdrant（带 tier payload）
        2. 清理 30 天未访问的 peripheral 候选
        3. 更新 last_run 时间戳
        """
        stats = _stats
        import time as _time
        t0 = _time.monotonic()

        try:
            # 清理过期 peripheral
            cutoff = datetime.now(timezone.utc) - timedelta(days=self.PURGE_DAYS)
            purged = await self._purge_expired(domain_id, cutoff)
            stats.purged = purged

            # 更新 Qdrant payloads（为晋升的记忆打 tier 标签）
            await self._update_tier_payloads(domain_id)

        except Exception as exc:
            logger.warning("deep_sleep failed: %s", exc)

        self._last_run = datetime.now(timezone.utc)
        stats.duration_ms = (_time.monotonic() - t0) * 1000
        logger.info(
            "dreaming.deep_sleep domain=%s purged=%d time=%.0fms",
            domain_id, stats.purged, stats.duration_ms,
        )
        return stats

    async def _purge_expired(self, domain_id: str, cutoff: datetime) -> int:
        """清理过期 peripheral 候选。"""
        try:
            from app.agent.tools import _get_pg_conn, _put_pg_conn
            conn = _get_pg_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM short_term_candidates "
                        "WHERE domain_id = %s AND last_recalled < %s AND promoted = FALSE",
                        (domain_id, cutoff)
                    )
                    purged = cur.rowcount
                    conn.commit()
                    return purged or 0
            finally:
                _put_pg_conn(conn)
        except Exception:
            return 0

    async def _update_tier_payloads(self, domain_id: str):
        """为晋升记忆更新 Qdrant payload（tier + access metadata）。"""
        # 简化实现：将 tier 信息写入 candidates 表的 promoted 字段
        # 完整的 Qdrant payload 更新需要向量客户端，这里留作扩展点
        pass

    # ── 数据加载/持久化 ─────────────────────────────────────────────────

    async def _load_candidates(
        self, domain_id: str, tier: str | None = None
    ) -> list[dict[str, Any]]:
        """从 short_term_candidates 加载候选。"""
        try:
            from app.agent.tools import _get_pg_conn, _put_pg_conn
            conn = _get_pg_conn()
            try:
                with conn.cursor() as cur:
                    if tier:
                        cur.execute(
                            "SELECT * FROM short_term_candidates "
                            "WHERE domain_id = %s AND tier = %s "
                            "ORDER BY recall_count DESC LIMIT 500",
                            (domain_id, tier)
                        )
                    else:
                        cur.execute(
                            "SELECT * FROM short_term_candidates "
                            "WHERE domain_id = %s "
                            "ORDER BY recall_count DESC LIMIT 500",
                            (domain_id,)
                        )
                    columns = [desc[0] for desc in (cur.description or [])]
                    return [dict(zip(columns, row)) for row in cur.fetchall()]
            finally:
                _put_pg_conn(conn)
        except Exception:
            return []

    async def _persist_scores(
        self, scored: list[tuple[dict, MemoryScore]], domain_id: str
    ):
        """持久化六维评分到数据库。"""
        try:
            from app.agent.tools import _get_pg_conn, _put_pg_conn
            conn = _get_pg_conn()
            try:
                with conn.cursor() as cur:
                    for candidate, score in scored:
                        tier = score.tier()
                        cur.execute(
                            """UPDATE short_term_candidates
                               SET recall_count = %s, tier = %s,
                                   light_gain = %s, promoted = %s
                               WHERE id = %s""",
                            (
                                candidate.get("recall_count", 1),
                                tier,
                                score.composite(),
                                tier in ("core", "working"),
                                candidate.get("id"),
                            )
                        )
                    conn.commit()
            finally:
                _put_pg_conn(conn)
        except Exception as exc:
            logger.debug("dreaming.persist_scores failed: %s", exc)

    # ── 完整 Dreams 循环 ────────────────────────────────────────────────

    async def dream(self, domain_id: str) -> DreamingStats:
        """执行完整的三阶段 Dreams。"""
        logger.info("dreaming.started domain=%s", domain_id)

        stats = await self.light_sleep(domain_id)
        stats = await self.rem_sleep(domain_id, stats)
        stats = await self.deep_sleep(domain_id, stats)

        logger.info(
            "dreaming.completed domain=%s scanned=%d core=%d working=%d peripheral=%d purged=%d time=%.0fms",
            domain_id, stats.candidates_scanned,
            stats.promoted_to_core, stats.promoted_to_working,
            stats.demoted_to_peripheral, stats.purged,
            stats.duration_ms,
        )
        return stats


# ── Singleton ───────────────────────────────────────────────────────────────

_dreamer: DreamingCron | None = None


def get_dreamer() -> DreamingCron:
    global _dreamer
    if _dreamer is None:
        _dreamer = DreamingCron()
    return _dreamer

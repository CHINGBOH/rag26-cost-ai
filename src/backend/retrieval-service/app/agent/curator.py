"""
#174: Curator 每周层 — Skill整合 + Knowledge衰减 + ERRORS晋升STABLE黑名单

每周一次的批量维护任务，协调三个子系统：

1. **Skill整合**
   - 扫描所有 domain 下的 skill，计算活跃度
   - 归档 30天未使用的 skill
   - 生成「本周技能报告」写入审计日志

2. **Knowledge衰减**（基于 #173 Weibull + Tier 系统）
   - 对所有记忆 tier 执行 Weibull 衰减计算
   - 按 domain 生成衰减报告：多少降级、多少晋升、多少清除
   - 清理过期 peripheral 记忆

3. **ERRORS 晋升 STABLE 黑名单**（基于 #166 ERRORS.md）
   - 从 ERRORS.md 和近期背景审查记录统计错误出现频率
   - 出现 ≥3 次的错误模式晋升为 STABLE 黑名单
   - 更新 STABLE 层注入内容（供 prompt_layers 使用）

与其他任务的关系：
- Dreaming (#170): 每日三级记忆评分 → Curator 每周汇总
- BackgroundReview (#168): 每轮审查 → Curator 收集信号统计
- 不与 GapRetestListener 冲突：每周日上午 04:00 UTC 独立运行
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.agent.weibull_decay import (
    MemoryTier,
    TierManager,
    get_tier_params,
    compute_tier_decay_batch,
    PERIPHERAL_WEIBULL,
    WORKING_WEIBULL,
    CORE_WEIBULL,
    TIER_WEIGHTS,
)

logger = logging.getLogger(__name__)

# ── 阈值常量 ────────────────────────────────────────────────────────────────

# Skill 归档：30 天未使用
SKILL_ARCHIVE_DAYS = 30

# ERRORS 晋升：连续出现 ≥3 次才晋升 STABLE
ERRORS_PROMOTION_THRESHOLD = 3

# 到期 peripheral 清理天数
PERIPHERAL_PURGE_DAYS = 7


@dataclass
class CuratorStats:
    """Curator 单次运行统计。"""
    # Skill 统计
    skills_scanned: int = 0
    skills_archived: int = 0
    skills_active: int = 0

    # Knowledge 衰减统计
    memories_scanned: int = 0
    promoted_to_core: int = 0
    promoted_to_working: int = 0
    demoted_to_peripheral: int = 0
    purged_expired: int = 0

    # ERRORS 晋升统计
    errors_patterns_scanned: int = 0
    errors_promoted_to_stable: int = 0

    # 元数据
    domains_processed: list[str] = field(default_factory=list)
    duration_ms: float = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "skills_scanned": self.skills_scanned,
            "skills_archived": self.skills_archived,
            "skills_active": self.skills_active,
            "memories_scanned": self.memories_scanned,
            "promoted_to_core": self.promoted_to_core,
            "promoted_to_working": self.promoted_to_working,
            "demoted_to_peripheral": self.demoted_to_peripheral,
            "purged_expired": self.purged_expired,
            "errors_patterns_scanned": self.errors_patterns_scanned,
            "errors_promoted_to_stable": self.errors_promoted_to_stable,
            "domains_processed": self.domains_processed,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


# ── Curator 主类 ───────────────────────────────────────────────────────────

class WeeklyCurator:
    """每周 Curator — 协调 Skill / Decay / ERRORS 三系统维护。

    调度：每周日上午 04:00 UTC（在 Dreaming 之后，给全天时间完成）。

    使用方式：
        curator = WeeklyCurator()
        stats = await curator.run(domains=["construction-cost"])
    """

    def __init__(self):
        self._tier_manager = TierManager()
        self._last_run: datetime | None = None
        self._run_count: int = 0

    # ── 完整运行 ────────────────────────────────────────────────────────

    async def run(
        self,
        *,
        domains: list[str] | None = None,
        dry_run: bool = False,
    ) -> CuratorStats:
        """执行一次完整的每周 Curator 维护。

        Args:
            domains: 要处理的 domain 列表。默认处理所有已知 domain。
            dry_run: 仅统计不写入（测试用）。
        """
        import time as _time
        t0 = _time.monotonic()
        self._run_count += 1
        stats = CuratorStats()

        if domains is None:
            domains = await self._discover_domains()

        stats.domains_processed = list(domains)

        try:
            logger.info(
                "curator.started run=%d domains=%s dry_run=%s",
                self._run_count, domains, dry_run,
            )

            # Phase 1: Skill 整合
            skill_stats = await self._phase_skill_integration(domains, dry_run)
            stats.skills_scanned = skill_stats["scanned"]
            stats.skills_archived = skill_stats["archived"]
            stats.skills_active = skill_stats["active"]

            # Phase 2: Knowledge 衰减
            decay_stats = await self._phase_knowledge_decay(domains, dry_run)
            stats.memories_scanned = decay_stats["scanned"]
            stats.promoted_to_core = decay_stats["promoted_to_core"]
            stats.promoted_to_working = decay_stats["promoted_to_working"]
            stats.demoted_to_peripheral = decay_stats["demoted_to_peripheral"]
            stats.purged_expired = decay_stats["purged"]

            # Phase 3: ERRORS 晋升 STABLE 黑名单
            errors_stats = await self._phase_errors_promotion(domains, dry_run)
            stats.errors_patterns_scanned = errors_stats["scanned"]
            stats.errors_promoted_to_stable = errors_stats["promoted"]

            self._last_run = datetime.now(timezone.utc)

        except Exception as exc:
            stats.error = str(exc)
            logger.warning("curator.failed run=%d error=%s", self._run_count, exc)

        stats.duration_ms = (_time.monotonic() - t0) * 1000
        logger.info(
            "curator.completed run=%d skills=%d/%d/%d "
            "memories=%d/%d/%d/%d/%d errors=%d/%d "
            "duration=%.0fms",
            self._run_count,
            stats.skills_scanned, stats.skills_archived, stats.skills_active,
            stats.memories_scanned,
            stats.promoted_to_core, stats.promoted_to_working,
            stats.demoted_to_peripheral, stats.purged_expired,
            stats.errors_patterns_scanned, stats.errors_promoted_to_stable,
            stats.duration_ms,
        )
        return stats

    # ── Phase 1: Skill 整合 ─────────────────────────────────────────────

    async def _phase_skill_integration(
        self, domains: list[str], dry_run: bool
    ) -> dict[str, int]:
        """扫描所有 skill，归档过期 skill，生成活跃度报告。

        规则：
        - 30 天未使用 → 归档到 .archive
        - use_count == 0 且创建超过 14 天 → 归档
        - 否则保持 active
        """
        scanned = 0
        archived = 0
        active = 0

        try:
            from app.agent.skills.skill_manager import get_skill_manager

            sm = get_skill_manager()
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(days=SKILL_ARCHIVE_DAYS)
            new_skill_cutoff = now - timedelta(days=14)

            for domain_id in domains:
                index = sm.scan(domain_id)

                for name, meta in index.items():
                    if meta.archived:
                        continue
                    scanned += 1

                    # 解析 last_used_at
                    last_used = None
                    if meta.last_used_at:
                        try:
                            last_used = datetime.fromisoformat(meta.last_used_at)
                        except (ValueError, TypeError):
                            pass

                    should_archive = False

                    if last_used and last_used < cutoff:
                        should_archive = True
                    elif meta.use_count == 0 and meta.created_at:
                        try:
                            created = datetime.fromisoformat(meta.created_at)
                            if created < new_skill_cutoff:
                                should_archive = True
                        except (ValueError, TypeError):
                            pass

                    if should_archive and not dry_run:
                        result = sm.delete(domain_id, name)
                        if result.get("ok"):
                            archived += 1
                            logger.info(
                                "curator.skill.archived domain=%s skill=%s",
                                domain_id, name,
                            )
                    elif not should_archive:
                        active += 1

        except Exception as exc:
            logger.warning("curator.phase1_skill failed: %s", exc)

        logger.info(
            "curator.phase1_skill scanned=%d archived=%d active=%d dry_run=%s",
            scanned, archived, active, dry_run,
        )
        return {"scanned": scanned, "archived": archived, "active": active}

    # ── Phase 2: Knowledge 衰减 ─────────────────────────────────────────

    async def _phase_knowledge_decay(
        self, domains: list[str], dry_run: bool
    ) -> dict[str, int]:
        """对所有 memory candidate 执行 Weibull 衰减 + tier 晋升/降级。

        流程：
        1. 从 short_term_candidates 加载所有候选（含 tier 信息）
        2. 对每个候选计算 Weibull 衰减因子
        3. 根据衰减后的分数重新分配 tier
        4. 清除过期的 peripheral 候选
        """
        scanned = 0
        promoted_core = 0
        promoted_working = 0
        demoted_peripheral = 0
        purged = 0

        try:
            now = datetime.now(timezone.utc)
            peripheral_cutoff = now - timedelta(days=PERIPHERAL_PURGE_DAYS)

            for domain_id in domains:
                candidates = await self._load_candidates(domain_id)
                if not candidates:
                    continue

                scanned += len(candidates)

                # Weibull 批量衰减
                enriched = compute_tier_decay_batch(candidates, now)

                for cand in enriched:
                    adjusted = float(cand.get("adjusted_score", 0))
                    current_tier_raw = cand.get("tier", "peripheral")
                    try:
                        current_tier = MemoryTier(current_tier_raw)
                    except ValueError:
                        current_tier = MemoryTier.PERIPHERAL

                    # 根据 adjusted_score 决定新 tier
                    new_tier = self._tier_manager.classify(adjusted)
                    mem_id = str(cand.get("id", ""))

                    # 使用滞回机制晋升/降级
                    if self._tier_manager.should_promote(mem_id, new_tier, current_tier):
                        if not dry_run:
                            cand["tier"] = new_tier.value

                        if new_tier == MemoryTier.CORE:
                            promoted_core += 1
                        elif new_tier == MemoryTier.WORKING:
                            promoted_working += 1
                        elif new_tier == MemoryTier.PERIPHERAL:
                            demoted_peripheral += 1

                    # 检查是否需要清除
                    if new_tier == MemoryTier.PERIPHERAL:
                        last_recalled = cand.get("last_recalled")
                        expired = False
                        if last_recalled:
                            if isinstance(last_recalled, str):
                                try:
                                    last_recalled = datetime.fromisoformat(last_recalled)
                                except (ValueError, TypeError):
                                    last_recalled = None
                            if last_recalled and last_recalled < peripheral_cutoff:
                                expired = True
                        if expired and not dry_run:
                            await self._delete_candidate(int(mem_id))
                            purged += 1

                # 持久化 tier 变更
                if not dry_run and (promoted_core + promoted_working + demoted_peripheral) > 0:
                    await self._persist_tier_changes(enriched)

        except Exception as exc:
            logger.warning("curator.phase2_decay failed: %s", exc)

        logger.info(
            "curator.phase2_decay scanned=%d core=%d working=%d peripheral=%d purged=%d",
            scanned, promoted_core, promoted_working, demoted_peripheral, purged,
        )
        return {
            "scanned": scanned,
            "promoted_to_core": promoted_core,
            "promoted_to_working": promoted_working,
            "demoted_to_peripheral": demoted_peripheral,
            "purged": purged,
        }

    # ── Phase 3: ERRORS 晋升 STABLE 黑名单 ──────────────────────────────

    async def _phase_errors_promotion(
        self, domains: list[str], dry_run: bool
    ) -> dict[str, int]:
        """统计 ERRORS.md 中的模式出现频率，≥3 次的晋升为 STABLE。

        STABLE 黑名单会被 prompt_layers 注入到 STABLE 层，
        确保每轮问答都检查这些模式。

        流程：
        1. 加载 ERRORS.md 中的黑名单模式
        2. 从后台审查日志统计模式出现次数
        3. 出现 ≥3 次的晋升到 STABLE 集合
        4. 持久化 STABLE 黑名单到文件
        """
        scanned = 0
        promoted = 0

        try:
            from app.agent.error_blacklist import get_error_blacklist

            blacklist = get_error_blacklist()
            patterns = blacklist.get_active_patterns()
            scanned = len(patterns)

            # 统计各模式在审查日志中的出现次数
            pattern_counts: dict[str, int] = await self._count_pattern_occurrences(patterns)

            # 出现 ≥3 次的晋升为 STABLE
            stable_patterns: list[str] = []
            for pattern, count in pattern_counts.items():
                if count >= ERRORS_PROMOTION_THRESHOLD:
                    stable_patterns.append(pattern)
                    promoted += 1

            if stable_patterns and not dry_run:
                # 读取现有 STABLE 黑名单
                stable_set = self._load_stable_blacklist()

                # 合并新模式
                for p in stable_patterns:
                    stable_set.add(p)

                # 持久化
                self._save_stable_blacklist(stable_set)
                logger.info(
                    "curator.phase3_errors promoted=%d patterns=%s",
                    promoted, stable_patterns,
                )

        except Exception as exc:
            logger.warning("curator.phase3_errors failed: %s", exc)

        logger.info(
            "curator.phase3_errors scanned=%d promoted=%d",
            scanned, promoted,
        )
        return {"scanned": scanned, "promoted": promoted}

    # ── 帮助方法 ──────────────────────────────────────────────────────────

    async def _discover_domains(self) -> list[str]:
        """发现所有活跃 domain。"""
        try:
            from app.agent.skills.skill_manager import get_skill_manager
            sm = get_skill_manager()
            # 从 skill 系统发现 domain
            domains: list[str] = []
            for item in sm._root.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    domains.append(item.name)
            if not domains:
                domains = ["construction-cost"]
            return domains
        except Exception:
            return ["construction-cost"]

    async def _load_candidates(self, domain_id: str) -> list[dict[str, Any]]:
        """从数据库加载所有候选记忆。"""
        try:
            from app.agent.tools import _get_pg_conn, _put_pg_conn

            conn = _get_pg_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM short_term_candidates "
                        "WHERE domain_id = %s ORDER BY recall_count DESC LIMIT 1000",
                        (domain_id,),
                    )
                    columns = [desc[0] for desc in (cur.description or [])]
                    return [dict(zip(columns, row)) for row in cur.fetchall()]
            finally:
                _put_pg_conn(conn)
        except Exception:
            return []

    async def _delete_candidate(self, candidate_id: int):
        """删除单个候选。"""
        try:
            from app.agent.tools import _get_pg_conn, _put_pg_conn

            conn = _get_pg_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM short_term_candidates WHERE id = %s",
                        (candidate_id,),
                    )
                    conn.commit()
            finally:
                _put_pg_conn(conn)
        except Exception as exc:
            logger.debug("curator.delete_candidate failed id=%s: %s", candidate_id, exc)

    async def _persist_tier_changes(self, candidates: list[dict]):
        """持久化 tier 变更到数据库。"""
        try:
            from app.agent.tools import _get_pg_conn, _put_pg_conn

            conn = _get_pg_conn()
            try:
                with conn.cursor() as cur:
                    for cand in candidates:
                        tier = cand.get("tier", "peripheral")
                        adj_score = cand.get("adjusted_score", 0)
                        nrd = cand.get("next_review_days", 7)
                        cand_id = cand.get("id")
                        if cand_id is None:
                            continue
                        cur.execute(
                            "UPDATE short_term_candidates "
                            "SET tier = %s, weibull_adjusted_score = %s, next_review_days = %s "
                            "WHERE id = %s",
                            (tier, adj_score, int(nrd), cand_id),
                        )
                    conn.commit()
            finally:
                _put_pg_conn(conn)
        except Exception as exc:
            logger.debug("curator.persist_tier_changes failed: %s", exc)

    async def _count_pattern_occurrences(self, patterns: list[str]) -> dict[str, int]:
        """统计各错误模式在近期审查记录中的出现次数。

        检查 ERRORS.md 文件和 background_review 事件日志。
        """
        counts: dict[str, int] = {}
        if not patterns:
            return counts

        # 从 ERRORS.md 本身统计（每个模式在文件中就算一次）
        try:
            from app.agent.error_blacklist import ERRORS_PATH
            if ERRORS_PATH.exists():
                content = ERRORS_PATH.read_text(encoding="utf-8")
                for pattern in patterns:
                    counts[pattern] = content.count(pattern)
        except Exception:
            pass

        # 检查 event_ledger 中的 ERROR 类型事件
        try:
            from app.agent.tools import _get_pg_conn, _put_pg_conn

            conn = _get_pg_conn()
            try:
                with conn.cursor() as cur:
                    # 查最近 7 天的 ERROR 或 background_review 事件
                    since = datetime.now(timezone.utc) - timedelta(days=7)
                    cur.execute(
                        "SELECT payload FROM agent_event_ledger "
                        "WHERE event_type IN ('error_detected', 'background_review.completed') "
                        "AND created_at >= %s "
                        "ORDER BY created_at DESC LIMIT 500",
                        (since.isoformat(),),
                    )
                    rows = cur.fetchall()
                    for (payload_json,) in rows:
                        try:
                            payload = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
                            text = json.dumps(payload, default=str)
                            for pattern in patterns:
                                if pattern in text:
                                    counts[pattern] = counts.get(pattern, 0) + 1
                        except (json.JSONDecodeError, TypeError):
                            pass
            finally:
                _put_pg_conn(conn)
        except Exception:
            pass

        return counts

    # ── STABLE 黑名单持久化 ──────────────────────────────────────────────

    @staticmethod
    def _stable_blacklist_path() -> str:
        """STABLE 黑名单文件路径。"""
        from pathlib import Path
        return str(Path(__file__).resolve().parents[5] / "config" / "STABLE_BLACKLIST.json")

    def _load_stable_blacklist(self) -> set[str]:
        """加载现有 STABLE 黑名单。"""
        try:
            path = self._stable_blacklist_path()
            import os
            if os.path.exists(path):
                content = open(path, encoding="utf-8").read()
                data = json.loads(content)
                return set(data.get("patterns", []))
        except Exception:
            pass
        return set()

    def _save_stable_blacklist(self, patterns: set[str]):
        """持久化 STABLE 黑名单。"""
        try:
            from pathlib import Path
            path = Path(self._stable_blacklist_path())
            path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "source": "curator_weekly",
                "promotion_threshold": ERRORS_PROMOTION_THRESHOLD,
                "patterns": sorted(patterns),
            }
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(
                "curator.stable_blacklist.saved count=%d path=%s",
                len(patterns), path,
            )
        except Exception as exc:
            logger.warning("curator.stable_blacklist.save failed: %s", exc)

    @staticmethod
    def get_stable_patterns() -> list[str]:
        """获取当前 STABLE 黑名单模式列表。

        供 prompt_layers 调用，注入到 STABLE 层。
        """
        try:
            path = WeeklyCurator._stable_blacklist_path()
            import os
            if os.path.exists(path):
                content = open(path, encoding="utf-8").read()
                data = json.loads(content)
                return data.get("patterns", [])
        except Exception:
            pass
        return []


# ── Singleton ───────────────────────────────────────────────────────────────

_curator: WeeklyCurator | None = None


def get_curator() -> WeeklyCurator:
    global _curator
    if _curator is None:
        _curator = WeeklyCurator()
    return _curator


async def run_weekly_curator(
    *,
    domains: list[str] | None = None,
    dry_run: bool = False,
) -> CuratorStats:
    """快捷入口：运行一次每周 Curator。"""
    curator = get_curator()
    return await curator.run(domains=domains, dry_run=dry_run)


__all__ = [
    "WeeklyCurator",
    "CuratorStats",
    "get_curator",
    "run_weekly_curator",
]

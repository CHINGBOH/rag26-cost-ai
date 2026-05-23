"""
#173: Weibull衰减+Tier分层系统

Weibull 分布提供比简单指数衰减更灵活的衰减曲线：
  F(t) = exp(-(t/scale)**shape)

Tier 分层管理三级记忆：
  - peripheral (外围):  快速衰减，噪声过滤
  - working    (工作):  中等衰减，活跃记忆
  - core       (核心):  慢速衰减，长期巩固

每个 tier 有独立的 Weibull 参数，使不同层级的记忆按不同的时间常数退化。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import ClassVar


class MemoryTier(str, Enum):
    """记忆三级分层。"""
    PERIPHERAL = "peripheral"   # 外围 — 快速衰减
    WORKING = "working"         # 工作 — 中等衰减
    CORE = "core"               # 核心 — 慢速衰减


@dataclass(frozen=True)
class WeibullParams:
    """单个 tier 的 Weibull 衰减参数。

    decay(t) = exp(-(t / scale) ** shape)

    shape < 1:  初期快速衰减（婴儿死亡率模式）
    shape = 1:  标准指数衰减（恒定失效率）
    shape > 1:  初期缓慢衰减，后期加速（老化模式，适合巩固记忆）
    """
    shape: float   # k 参数，控制曲线形状
    scale: float   # λ 参数，特征衰减时间（天）

    def decay(self, days: float) -> float:
        """计算 Weibull 生存概率（0~1）。"""
        if days <= 0:
            return 1.0
        return math.exp(-((days / self.scale) ** self.shape))

    def half_life_days(self) -> float:
        """计算半衰期（天）。

        解 exp(-(t/scale)^shape) = 0.5
        → (t/scale)^shape = ln(2)
        → t = scale * ln(2)^(1/shape)
        """
        return self.scale * (math.log(2) ** (1.0 / self.shape))


# ── 默认 tier Weibull 参数 ────────────────────────────────────────────────

# peripheral: shape=0.8 (初期快速衰减) + scale=7 天 → 半衰期 ≈ 5.2 天
PERIPHERAL_WEIBULL = WeibullParams(shape=0.8, scale=7.0)

# working: shape=1.5 (初期较慢，后期加速) + scale=14 天 → 半衰期 ≈ 9.8 天
WORKING_WEIBULL = WeibullParams(shape=1.5, scale=14.0)

# core: shape=2.5 (高度老化模式) + scale=60 天 → 半衰期 ≈ 50.4 天
CORE_WEIBULL = WeibullParams(shape=2.5, scale=60.0)


# ── Tier 权重映射（用于综合评分）──────────────────────────────────────────

TIER_WEIGHTS: dict[MemoryTier, float] = {
    MemoryTier.PERIPHERAL: 0.55,  # 外围权重最低
    MemoryTier.WORKING: 0.75,      # 工作中等
    MemoryTier.CORE: 0.95,         # 核心最高
}


def get_tier_params(tier: MemoryTier) -> WeibullParams:
    """获取 tier 对应的 Weibull 参数。"""
    mapping = {
        MemoryTier.PERIPHERAL: PERIPHERAL_WEIBULL,
        MemoryTier.WORKING: WORKING_WEIBULL,
        MemoryTier.CORE: CORE_WEIBULL,
    }
    return mapping[tier]


def weibull_decay(days: float, shape: float, scale: float) -> float:
    """通用 Weibull 衰减函数。

    Args:
        days:  距上次访问的天数
        shape: Weibull 形状参数 k
        scale: Weibull 尺度参数 λ（天）

    Returns:
        0.0 ~ 1.0 的衰减因子（1.0 = 完全新鲜）
    """
    if days <= 0:
        return 1.0
    if scale <= 0:
        raise ValueError(f"scale must be > 0, got {scale}")
    if shape <= 0:
        raise ValueError(f"shape must be > 0, got {shape}")
    return math.exp(-((days / scale) ** shape))


# ── Tier 分层管理 ────────────────────────────────────────────────────────


@dataclass
class TierScore:
    """Tier 感知的评分结果，综合原始分数与衰减因子。"""
    raw_composite: float = 0.0       # 原始六维综合评分
    tier: MemoryTier = MemoryTier.PERIPHERAL
    decay_factor: float = 1.0        # 当前 Weibull 衰减因子
    adjusted_score: float = 0.0      # 衰减调整后的评分
    next_review_days: float = 7.0    # 建议下次审查间隔（天）


class TierManager:
    """三级 Tier 管理器。

    职责：
    - 根据综合评分分配/重新分配 tier
    - 计算 tier 感知的衰减因子
    - 决定晋升/降级

    晋升规则：
      composite >= 0.70 → core
      composite >= 0.40 → working
      composite <  0.40 → peripheral

    附加 Tier Stability 逻辑：
      - core → working 降级需要连续 2 次评分低于阈值
      - peripheral → working 晋升只需 1 次评分达标
    """

    # 晋升阈值（与 dreaming.py 保持一致）
    CORE_THRESHOLD: ClassVar[float] = 0.70
    WORKING_THRESHOLD: ClassVar[float] = 0.40

    # 稳定性计数器上限
    STABILITY_WINDOW: ClassVar[int] = 3

    def __init__(self):
        self._stability: dict[str, list[MemoryTier]] = {}  # memory_id → 最近 tier 历史

    def classify(self, composite_score: float) -> MemoryTier:
        """根据综合评分确定初始 tier。"""
        if composite_score >= self.CORE_THRESHOLD:
            return MemoryTier.CORE
        elif composite_score >= self.WORKING_THRESHOLD:
            return MemoryTier.WORKING
        else:
            return MemoryTier.PERIPHERAL

    def classify_with_decay(
        self,
        composite_score: float,
        days_since_recall: float,
        current_tier: MemoryTier | None = None,
    ) -> TierScore:
        """Tier 感知的评分 + Weibull 衰减。

        流程：
        1. 根据 raw composite 确定目标 tier
        2. 使用目标 tier 的 Weibull 参数计算 decay_factor
        3. adjusted_score = raw_composite × decay_factor × tier_weight
        4. 根据 adjusted_score 建议下次审查间隔
        """
        target_tier = self.classify(composite_score)
        params = get_tier_params(target_tier)
        decay_factor = params.decay(days_since_recall)
        tier_weight = TIER_WEIGHTS[target_tier]

        adjusted_score = composite_score * decay_factor * tier_weight

        # 建议审查间隔：与半衰期成比例，除以3确保信息不会丢失
        next_review = max(1.0, params.half_life_days() / 3.0)

        return TierScore(
            raw_composite=composite_score,
            tier=target_tier,
            decay_factor=decay_factor,
            adjusted_score=adjusted_score,
            next_review_days=next_review,
        )

    def should_promote(
        self,
        memory_id: str,
        new_tier: MemoryTier,
        current_tier: MemoryTier,
    ) -> bool:
        """判断是否应该执行晋升。

        带滞回效应防止频繁抖动：
        - 降级 (core→working, working→peripheral): 需要连续 2 次评分低于阈值
        - 晋升 (peripheral→working, working→core): 立即生效
        """
        if new_tier == current_tier:
            return False

        tier_order = {MemoryTier.PERIPHERAL: 0, MemoryTier.WORKING: 1, MemoryTier.CORE: 2}
        is_demotion = tier_order[new_tier] < tier_order[current_tier]

        if not is_demotion:
            # 晋升：立即生效
            self._stability.pop(memory_id, None)
            return True

        # 降级：需要滞回确认
        history = self._stability.get(memory_id, [])
        history.append(new_tier)
        if len(history) > self.STABILITY_WINDOW:
            history = history[-self.STABILITY_WINDOW:]
        self._stability[memory_id] = history

        # 连续 N 次都是目标 tier → 确认降级
        return len(history) >= 2 and all(t == new_tier for t in history)

    def update_stability(self, memory_id: str, tier: MemoryTier):
        """记录 tier 历史（用于稳定性追踪）。"""
        history = self._stability.get(memory_id, [])
        history.append(tier)
        if len(history) > self.STABILITY_WINDOW:
            history = history[-self.STABILITY_WINDOW:]
        self._stability[memory_id] = history

    def is_stable(self, memory_id: str) -> bool:
        """检查记忆是否在 tier 上已经稳定（最近 N 次没有变化）。"""
        history = self._stability.get(memory_id, [])
        if len(history) < self.STABILITY_WINDOW:
            return False
        return len(set(history[-self.STABILITY_WINDOW:])) == 1


# ── 批量衰减计算 ──────────────────────────────────────────────────────────


def compute_tier_decay_batch(
    memories: list[dict],
    now: datetime | None = None,
) -> list[dict]:
    """为一组记忆批量计算 tier 感知的 Weibull 衰减。

    将 decay_factor、adjusted_score 和 tier 写回到每个 dict 中。

    Args:
        memories: 含 last_recalled / last_recalled_at / recall_count 的记忆条目
        now: 参考时间，默认 UTC now

    Returns:
        原地修改后的同一列表
    """
    if now is None:
        now = datetime.now(timezone.utc)

    tier_mgr = TierManager()

    for mem in memories:
        # 计算天数
        last_recalled = mem.get("last_recalled") or mem.get("last_recalled_at")
        days_ago = 0.0
        if last_recalled:
            if isinstance(last_recalled, str):
                try:
                    last_recalled = datetime.fromisoformat(last_recalled)
                except (ValueError, TypeError):
                    last_recalled = None
            if last_recalled is not None:
                days_ago = max(0.0, (now - last_recalled).total_seconds() / 86400.0)

        # 估算 composite score（简化版，不访问完整六维）
        recall_count = int(mem.get("recall_count", 1))
        light_gain = float(mem.get("light_gain", 0))
        rem_gain = float(mem.get("rem_gain", 0))
        confidence = float(mem.get("confidence", 0.5))

        raw_composite = min(1.0, (
            recall_count / 10 * 0.25
            + (light_gain + rem_gain) / 2 * 0.20
            + confidence * 0.10
            + 0.45  # base offset
        ))

        # 读取当前 tier，计算目标 tier 和衰减
        current_tier_raw = mem.get("tier", "")
        try:
            current_tier = MemoryTier(current_tier_raw) if current_tier_raw else None
        except ValueError:
            current_tier = None

        ts = tier_mgr.classify_with_decay(raw_composite, days_ago, current_tier)
        mem["decay_factor"] = ts.decay_factor
        mem["adjusted_score"] = ts.adjusted_score
        mem["tier"] = ts.tier.value
        mem["next_review_days"] = ts.next_review_days

    return memories


# ── 导出 ──────────────────────────────────────────────────────────────────

__all__ = [
    "MemoryTier",
    "WeibullParams",
    "TierScore",
    "TierManager",
    "weibull_decay",
    "get_tier_params",
    "compute_tier_decay_batch",
    "PERIPHERAL_WEIBULL",
    "WORKING_WEIBULL",
    "CORE_WEIBULL",
]

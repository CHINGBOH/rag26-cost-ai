"""
#173: Weibull衰减+Tier分层系统 测试

测试覆盖：
1. Weibull 衰减函数正确性
2. Tier 分层分类
3. Tier 滞回管理
4. MemoryScore 集成
"""
import math

import pytest

from app.agent.weibull_decay import (
    MemoryTier,
    WeibullParams,
    TierScore,
    TierManager,
    weibull_decay,
    get_tier_params,
    compute_tier_decay_batch,
    PERIPHERAL_WEIBULL,
    WORKING_WEIBULL,
    CORE_WEIBULL,
    TIER_WEIGHTS,
)


class TestWeibullDecay:
    """Weibull 衰减函数单元测试。"""

    def test_zero_days_no_decay(self):
        """t=0 时衰减因子应为 1.0。"""
        assert weibull_decay(0, shape=1.5, scale=14) == 1.0
        assert weibull_decay(-1, shape=1.5, scale=14) == 1.0  # 负天数视为 0

    def test_exponential_special_case(self):
        """shape=1 时 Weibull 退化为指数分布。"""
        days = 14
        expected = math.exp(-days / 14)
        result = weibull_decay(days, shape=1.0, scale=14)
        assert abs(result - expected) < 1e-10

    def test_half_life_matches_decay(self):
        """半衰期点处 decay 应约为 0.5。"""
        params = WORKING_WEIBULL
        hl = params.half_life_days()
        decay_at_hl = weibull_decay(hl, params.shape, params.scale)
        assert abs(decay_at_hl - 0.5) < 1e-10

    def test_core_decays_slower(self):
        """core 记忆衰减应比 peripheral 慢得多。"""
        days = 14
        core_decay = CORE_WEIBULL.decay(days)
        peripheral_decay = PERIPHERAL_WEIBULL.decay(days)
        assert core_decay > peripheral_decay

    def test_long_term_limit(self):
        """t→∞ 时衰减趋向 0。"""
        assert weibull_decay(365 * 10, shape=1.0, scale=7) < 1e-10

    def test_invalid_params_raise(self):
        """无效参数应抛出 ValueError。"""
        with pytest.raises(ValueError, match="scale must be"):
            weibull_decay(10, shape=1.0, scale=-1)
        with pytest.raises(ValueError, match="scale must be"):
            weibull_decay(10, shape=1.0, scale=0)
        with pytest.raises(ValueError, match="shape must be"):
            weibull_decay(10, shape=-0.5, scale=7)

    def test_weibull_params_half_life(self):
        """验证各 tier 半衰期数量级正确。"""
        # peripheral: ~5.2 天
        assert 4 <= PERIPHERAL_WEIBULL.half_life_days() <= 7
        # working: ~9.8 天
        assert 8 <= WORKING_WEIBULL.half_life_days() <= 12
        # core: ~50.4 天
        assert 40 <= CORE_WEIBULL.half_life_days() <= 60


class TestTierClassification:
    """Tier 分层单元测试。"""

    def test_classify_core(self):
        """>= 0.7 → core。"""
        mgr = TierManager()
        assert mgr.classify(0.70) == MemoryTier.CORE
        assert mgr.classify(0.85) == MemoryTier.CORE
        assert mgr.classify(1.00) == MemoryTier.CORE

    def test_classify_working(self):
        """>= 0.4, < 0.7 → working。"""
        mgr = TierManager()
        assert mgr.classify(0.40) == MemoryTier.WORKING
        assert mgr.classify(0.55) == MemoryTier.WORKING
        assert mgr.classify(0.69) == MemoryTier.WORKING

    def test_classify_peripheral(self):
        """< 0.4 → peripheral。"""
        mgr = TierManager()
        assert mgr.classify(0.0) == MemoryTier.PERIPHERAL
        assert mgr.classify(0.25) == MemoryTier.PERIPHERAL
        assert mgr.classify(0.39) == MemoryTier.PERIPHERAL

    def test_classify_with_decay_fresh(self):
        """新鲜记忆（0天）decay_factor=1.0。"""
        mgr = TierManager()
        ts = mgr.classify_with_decay(0.75, days_since_recall=0.0)
        assert ts.tier == MemoryTier.CORE
        assert ts.decay_factor == 1.0
        assert ts.adjusted_score > 0

    def test_classify_with_decay_old(self):
        """老化记忆应有较低 adjusted_score。"""
        mgr = TierManager()
        fresh = mgr.classify_with_decay(0.75, days_since_recall=0.0)
        old = mgr.classify_with_decay(0.75, days_since_recall=30)
        assert old.decay_factor < fresh.decay_factor
        assert old.adjusted_score < fresh.adjusted_score

    def test_next_review_days_positive(self):
        """建议审查间隔应为正数。"""
        mgr = TierManager()
        ts = mgr.classify_with_decay(0.80, days_since_recall=0.0)
        assert ts.next_review_days > 0


class TestTierHysteresis:
    """Tier 滞回管理测试。"""

    def test_promotion_immediate(self):
        """晋升应立即可执行。"""
        mgr = TierManager()
        # peripheral → working 应立即晋升
        assert mgr.should_promote(
            "mem1", MemoryTier.WORKING, MemoryTier.PERIPHERAL
        ) is True

        # working → core 应立即晋升
        assert mgr.should_promote(
            "mem2", MemoryTier.CORE, MemoryTier.WORKING
        ) is True

    def test_no_op_same_tier(self):
        """同一 tier 无变化。"""
        mgr = TierManager()
        assert mgr.should_promote(
            "mem1", MemoryTier.CORE, MemoryTier.CORE
        ) is False

    def test_demotion_requires_hysteresis(self):
        """降级需要连续 2 次确认。"""
        mgr = TierManager()
        mem_id = "mem_test"

        # 第一次降级尝试：不通过
        assert mgr.should_promote(
            mem_id, MemoryTier.PERIPHERAL, MemoryTier.WORKING
        ) is False

        # 第二次降级尝试：通过
        assert mgr.should_promote(
            mem_id, MemoryTier.PERIPHERAL, MemoryTier.WORKING
        ) is True

    def test_demotion_reset_after_promotion(self):
        """晋升后重置滞回历史。"""
        mgr = TierManager()
        mem_id = "demoted_mem"

        # 先触发一次降级尝试
        mgr.should_promote(mem_id, MemoryTier.PERIPHERAL, MemoryTier.WORKING)
        # 然后晋升
        mgr.should_promote(mem_id, MemoryTier.WORKING, MemoryTier.PERIPHERAL)
        # 再次降级需要重新累积
        assert mgr.should_promote(
            mem_id, MemoryTier.PERIPHERAL, MemoryTier.WORKING
        ) is False


class TestTierDecayBatch:
    """批量衰减计算测试。"""

    def test_batch_adds_metadata(self):
        """批量计算应添加 decay 元数据。"""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        memories = [
            {
                "id": 1,
                "last_recalled": (now - timedelta(days=3)).isoformat(),
                "recall_count": 5,
                "light_gain": 0.3,
                "rem_gain": 0.2,
                "confidence": 0.6,
                "tier": "working",
            },
            {
                "id": 2,
                "last_recalled": (now - timedelta(days=30)).isoformat(),
                "recall_count": 1,
                "light_gain": 0.1,
                "rem_gain": 0.0,
                "confidence": 0.3,
                "tier": "peripheral",
            },
        ]

        result = compute_tier_decay_batch(memories, now)

        for mem in result:
            assert "decay_factor" in mem
            assert "adjusted_score" in mem
            assert "tier" in mem
            assert "next_review_days" in mem
            assert 0.0 <= mem["decay_factor"] <= 1.0
            assert mem["next_review_days"] > 0

        # 记忆1 更新（3天经过），衰减应比记忆2 高
        assert result[0]["decay_factor"] > result[1]["decay_factor"]


class TestMemoryScoreIntegration:
    """dreaming.MemoryScore Weibull 集成测试。"""

    def test_weibull_adjusted_score(self):
        """验证 Weibull 调整评分。"""
        from app.agent.dreaming import MemoryScore

        score = MemoryScore(
            recency=0.8,
            frequency=0.5,
            uniqueness=0.5,
            utility=0.5,
            confidence=0.5,
            stability=0.5,
            days_since_recall=3.0,
        )

        adjusted = score.weibull_adjusted_score()
        assert 0.0 <= adjusted <= 1.0

    def test_next_review_days(self):
        """验证建议审查间隔。"""
        from app.agent.dreaming import MemoryScore

        score = MemoryScore(
            recency=0.9,
            frequency=0.8,
            uniqueness=0.8,
            utility=0.8,
            confidence=0.8,
            stability=0.8,
            days_since_recall=0.0,
        )

        # 高评分 → core → 长间隔
        nrd = score.next_review_days()
        assert nrd > 0


class TestDefaultParams:
    """默认 Weibull 参数合理性测试。"""

    def test_peripheral_params_values(self):
        """peripheral: shape=0.8, scale=7."""
        assert PERIPHERAL_WEIBULL.shape == 0.8
        assert PERIPHERAL_WEIBULL.scale == 7.0

    def test_working_params_values(self):
        """working: shape=1.5, scale=14."""
        assert WORKING_WEIBULL.shape == 1.5
        assert WORKING_WEIBULL.scale == 14.0

    def test_core_params_values(self):
        """core: shape=2.5, scale=60."""
        assert CORE_WEIBULL.shape == 2.5
        assert CORE_WEIBULL.scale == 60.0

    def test_tier_weights(self):
        """Tier 权重应有合理排序。"""
        assert TIER_WEIGHTS[MemoryTier.PERIPHERAL] < TIER_WEIGHTS[MemoryTier.WORKING]
        assert TIER_WEIGHTS[MemoryTier.WORKING] < TIER_WEIGHTS[MemoryTier.CORE]
        assert 0 < TIER_WEIGHTS[MemoryTier.PERIPHERAL] < 1
        assert 0 < TIER_WEIGHTS[MemoryTier.CORE] <= 1

    def test_get_tier_params(self):
        """验证 get_tier_params 返回正确参数。"""
        assert get_tier_params(MemoryTier.PERIPHERAL) is PERIPHERAL_WEIBULL
        assert get_tier_params(MemoryTier.WORKING) is WORKING_WEIBULL
        assert get_tier_params(MemoryTier.CORE) is CORE_WEIBULL

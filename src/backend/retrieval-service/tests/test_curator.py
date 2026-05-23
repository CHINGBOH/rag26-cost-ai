"""
#174: Curator每周层 测试

测试覆盖：
1. CuratorStats 序列化
2. WeeklyCurator run（dry_run）
3. Phase 1: Skill 整合
4. Phase 2: Knowledge 衰减
5. Phase 3: ERRORS 晋升
6. STABLE 黑名单持久化
"""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.curator import (
    WeeklyCurator,
    CuratorStats,
    get_curator,
    run_weekly_curator,
    SKILL_ARCHIVE_DAYS,
    ERRORS_PROMOTION_THRESHOLD,
    PERIPHERAL_PURGE_DAYS,
)
from app.agent.weibull_decay import MemoryTier


class TestCuratorStats:
    """CuratorStats 序列化测试。"""

    def test_defaults(self):
        stats = CuratorStats()
        assert stats.skills_scanned == 0
        assert stats.memories_scanned == 0
        assert stats.errors_patterns_scanned == 0
        assert stats.domains_processed == []

    def test_to_dict(self):
        stats = CuratorStats(
            skills_scanned=10,
            skills_archived=2,
            skills_active=8,
            memories_scanned=100,
            promoted_to_core=5,
            demoted_to_peripheral=3,
            purged_expired=7,
            errors_patterns_scanned=4,
            errors_promoted_to_stable=2,
            domains_processed=["test-domain"],
            duration_ms=1234.5,
        )
        d = stats.to_dict()
        assert d["skills_scanned"] == 10
        assert d["skills_archived"] == 2
        assert d["promoted_to_core"] == 5
        assert d["errors_promoted_to_stable"] == 2
        assert d["domains_processed"] == ["test-domain"]


class TestWeeklyCuratorDryRun:
    """Curator dry_run 模式测试（不修改持久化状态）。"""

    @pytest.fixture
    def curator(self):
        return WeeklyCurator()

    @pytest.mark.asyncio
    async def test_run_dry_run_returns_stats(self, curator):
        """dry_run 模式应返回有效 stats 且不崩溃。"""
        stats = await curator.run(domains=["test-domain"], dry_run=True)

        assert isinstance(stats, CuratorStats)
        assert stats.duration_ms >= 0
        assert stats.error == ""
        assert "test-domain" in stats.domains_processed
        # dry_run 不应有任何变更
        assert stats.skills_archived == 0
        assert stats.promoted_to_core == 0

    @pytest.mark.asyncio
    async def test_run_without_domains_discovers(self, curator):
        """不传 domains 时自动发现。"""
        with patch.object(curator, "_discover_domains", return_value=["auto-domain"]):
            stats = await curator.run(dry_run=True)
            assert stats.domains_processed == ["auto-domain"]

    @pytest.mark.asyncio
    async def test_run_handles_exceptions_gracefully(self, curator):
        """异常不应崩溃，应记录到 stats.error。"""
        with patch.object(curator, "_discover_domains", side_effect=RuntimeError("boom")):
            stats = await curator.run(dry_run=True)
            assert stats.error != ""


class TestPhaseSkillIntegration:
    """Phase 1: Skill 整合测试。"""

    @pytest.fixture
    def curator(self):
        return WeeklyCurator()

    @pytest.mark.asyncio
    async def test_scans_skills(self, curator):
        """应扫描并统计 skill 数量。"""
        result = await curator._phase_skill_integration(
            domains=["nonexistent-domain"], dry_run=True
        )
        assert "scanned" in result
        assert "archived" in result
        assert "active" in result
        assert result["archived"] == 0  # dry_run 不归档


class TestPhaseKnowledgeDecay:
    """Phase 2: Knowledge 衰减测试。"""

    @pytest.fixture
    def curator(self):
        return WeeklyCurator()

    @pytest.mark.asyncio
    async def test_decay_returns_stats(self, curator):
        """应返回统计信息。"""
        result = await curator._phase_knowledge_decay(
            domains=["test-domain"], dry_run=True
        )
        assert "scanned" in result
        assert "promoted_to_core" in result
        assert "demoted_to_peripheral" in result
        assert "purged" in result

    @pytest.mark.asyncio
    async def test_decay_with_empty_candidates(self, curator):
        """无候选时返回零统计。"""
        with patch.object(curator, "_load_candidates", return_value=[]):
            result = await curator._phase_knowledge_decay(
                domains=["empty-domain"], dry_run=True
            )
        assert result["scanned"] == 0


class TestPhaseErrorsPromotion:
    """Phase 3: ERRORS 晋升测试。"""

    @pytest.fixture
    def curator(self):
        return WeeklyCurator()

    @pytest.mark.asyncio
    async def test_errors_promotion_returns_stats(self, curator):
        """应返回统计信息。"""
        result = await curator._phase_errors_promotion(
            domains=["test-domain"], dry_run=True
        )
        assert "scanned" in result
        assert "promoted" in result

    @pytest.mark.asyncio
    async def test_no_patterns_no_promotion(self, curator):
        """无黑名单模式时 promotion 为 0。"""
        with patch(
            "app.agent.curator.get_error_blacklist"
        ) as mock_bl:
            mock_bl_instance = MagicMock()
            mock_bl_instance.get_active_patterns.return_value = []
            mock_bl.return_value = mock_bl_instance

            result = await curator._phase_errors_promotion(
                domains=["test-domain"], dry_run=True
            )
            assert result["scanned"] == 0
            assert result["promoted"] == 0


class TestStableBlacklist:
    """STABLE 黑名单持久化测试。"""

    @pytest.fixture
    def curator(self):
        return WeeklyCurator()

    def test_load_empty(self, curator):
        """无文件时返回空集。"""
        with patch.object(
            WeeklyCurator, "_stable_blacklist_path", return_value="/nonexistent/path.json"
        ):
            result = curator._load_stable_blacklist()
            assert result == set()

    def test_save_and_load_roundtrip(self):
        """保存后应能正确加载。"""
        tmp = tempfile.mktemp(suffix=".json")
        try:
            with patch.object(
                WeeklyCurator, "_stable_blacklist_path", return_value=tmp
            ):
                curator = WeeklyCurator()
                patterns = {"无法回答", "无法提供", "编造数值"}
                curator._save_stable_blacklist(patterns)

                loaded = curator._load_stable_blacklist()
                assert loaded == patterns
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_get_stable_patterns(self):
        """静态方法应返回模式列表。"""
        tmp = tempfile.mktemp(suffix=".json")
        try:
            data = {
                "version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "source": "curator_weekly",
                "promotion_threshold": 3,
                "patterns": ["pattern-a", "pattern-b"],
            }
            Path(tmp).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            with patch.object(
                WeeklyCurator, "_stable_blacklist_path", return_value=tmp
            ):
                patterns = WeeklyCurator.get_stable_patterns()
                assert "pattern-a" in patterns
                assert "pattern-b" in patterns
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


class TestSingleton:
    """Singleton 模式测试。"""

    def test_get_curator_returns_same_instance(self):
        c1 = get_curator()
        c2 = get_curator()
        assert c1 is c2


class TestThresholdConstants:
    """阈值常量测试。"""

    def test_skill_archive_days(self):
        assert SKILL_ARCHIVE_DAYS == 30

    def test_errors_promotion_threshold(self):
        assert ERRORS_PROMOTION_THRESHOLD == 3

    def test_peripheral_purge_days(self):
        assert PERIPHERAL_PURGE_DAYS == 7


class TestCuratorConfigIntegration:
    """配置集成测试。"""

    def test_config_defaults(self):
        """验证 CuratorConfig 默认值合理。"""
        from app.agent.learning_config import CuratorConfig

        config = CuratorConfig()
        assert config.enabled is True
        assert config.cron_day_of_week == 6   # Sunday
        assert config.cron_hour == 4           # 04:00 UTC
        assert config.skill_archive_days == 30
        assert config.peripheral_purge_days == 7
        assert config.errors_promotion_threshold == 3
        assert config.dry_run is False

    def test_config_validation(self):
        """验证配置边界约束。"""
        from app.agent.learning_config import CuratorConfig

        # 正常值应通过验证
        config = CuratorConfig(
            cron_day_of_week=0,
            cron_hour=0,
            cron_minute=30,
            skill_archive_days=7,
            peripheral_purge_days=1,
            errors_promotion_threshold=2,
            max_candidates_per_domain=100,
        )
        assert config.cron_minute == 30

        # 超出范围应被 Pydantic 拒绝
        with pytest.raises(Exception):
            CuratorConfig(cron_day_of_week=7)   # 超出 0-6

        with pytest.raises(Exception):
            CuratorConfig(cron_hour=24)          # 超出 0-23

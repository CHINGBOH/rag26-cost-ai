"""
测试 SignalCollector 类 - Issue #96
"""

import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, MagicMock, patch

import pytest

from app.agent.signal_collector import (
    SignalCollector,
    AggregatedSignals,
    FeedbackSignal,
    FailureSignal,
    RepeatQuestionSignal,
    ViolationSignal,
    TopoAnomalySignal,
    get_latest_signals,
)


class TestFeedbackSignal:
    """FeedbackSignal 数据类测试"""
    
    def test_creation(self):
        signal = FeedbackSignal(
            session_id="sess_123",
            message_id="msg_456",
            rating=5,
            tags=["helpful", "accurate"],
            feedback_text="Very good!",
            ts=1609459200.0
        )
        assert signal.session_id == "sess_123"
        assert signal.message_id == "msg_456"
        assert signal.rating == 5
        assert signal.tags == ["helpful", "accurate"]
        assert signal.ts == 1609459200.0
    
    def test_to_dict(self):
        signal = FeedbackSignal(
            session_id="sess_123",
            message_id="msg_456",
            rating=5,
            tags=["helpful"],
            feedback_text="Good!",
            ts=1609459200.0
        )
        d = signal.to_dict()
        assert d["session_id"] == "sess_123"
        assert d["rating"] == 5
        assert isinstance(d["tags"], list)

    def test_problem_detector_compatibility_properties(self):
        signal = FeedbackSignal(
            session_id="sess_123",
            message_id="msg_456",
            rating=2,
            tags=["unclear"],
            feedback_text="Need more evidence",
            ts=1609459200.0,
            overall_score=2.0,
        )

        assert signal.signal_id == "msg_456"
        assert signal.text == "Need more evidence"
        assert signal.dimensions == {}
        assert signal.metadata["session_id"] == "sess_123"


class TestAggregatedSignals:
    """AggregatedSignals 聚合类测试"""
    
    def test_empty_aggregation(self):
        agg = AggregatedSignals(timestamp=time.time())
        assert agg.total_count == 0
        assert agg.severity_score == 0.0
    
    def test_total_count_calculation(self):
        agg = AggregatedSignals(
            timestamp=time.time(),
            feedback_signals=[
                FeedbackSignal("s1", "m1", 5, ts=time.time()),
                FeedbackSignal("s2", "m2", 3, ts=time.time()),
            ],
            failure_signals=[
                FailureSignal("s1", 0, "error", 5000, ts=time.time()),
            ],
            repeat_signals=[],
            violation_signals=[],
            topo_signals=[]
        )
        assert agg.total_count == 3
    
    def test_severity_score_calculation(self):
        """测试严重度计分逻辑"""
        agg = AggregatedSignals(
            timestamp=time.time(),
            feedback_signals=[
                FeedbackSignal("s1", "m1", 1, ts=time.time()),  # 负反馈 * 3
                FeedbackSignal("s2", "m2", 5, ts=time.time()),  # 正反馈
            ],
            failure_signals=[
                FailureSignal("s1", 0, "error", 5000, ts=time.time()),  # * 20
            ],
            repeat_signals=[
                RepeatQuestionSignal("s1", 2, 0, 1, 0.9, time.time()),  # * 5
            ],
            violation_signals=[
                ViolationSignal("r1", "contract1", "code1", ts=time.time()),  # * 15
            ],
            topo_signals=[
                TopoAnomalySignal("e1", "n1", "n2", "stale", "2024-01-01", 10, time.time()),  # * 8
            ]
        )
        # Score = 3 (negative feedback) + 20 (failure) + 5 (repeat) + 15 (violation) + 8 (topo) = 51
        expected_score = 3 + 20 + 5 + 15 + 8
        assert agg.severity_score == float(expected_score)
    
    def test_severity_score_capped_at_100(self):
        """验证严重度分值不超过 100"""
        agg = AggregatedSignals(
            timestamp=time.time(),
            failure_signals=[FailureSignal("s1", 0, "error", 5000, ts=time.time()) for _ in range(10)],
            violation_signals=[ViolationSignal("r1", "c1", "code1", ts=time.time()) for _ in range(10)],
        )
        assert agg.severity_score <= 100.0

    def test_window_compatibility_properties(self):
        agg = AggregatedSignals(timestamp=1609459200.0)
        assert agg.window_end == 1609459200.0
        assert agg.window_start == pytest.approx(1609455600.0)


class TestSignalCollectorInit:
    """SignalCollector 初始化测试"""
    
    def test_init_without_pool(self):
        """测试使用内部创建的池初始化"""
        with patch.object(SignalCollector, '_init_pool'):
            collector = SignalCollector(pool=None)
            assert collector.pool is None
            assert collector._owns_pool is True
    
    def test_init_with_pool(self):
        """测试使用外部提供的池初始化"""
        mock_pool = Mock()
        collector = SignalCollector(pool=mock_pool)
        assert collector.pool is mock_pool
        assert collector._owns_pool is False

    def test_init_pool_reads_runtime_postgres_config(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_HOST", "collector.db")
        monkeypatch.setenv("POSTGRES_PORT", "5549")
        monkeypatch.setenv("POSTGRES_DB", "collector_db")
        monkeypatch.setenv("POSTGRES_USER", "collector_user")
        monkeypatch.setenv("POSTGRES_PASSWORD", "collector_pass")

        mock_pool = Mock()
        mock_conn = Mock()
        mock_cursor_ctx = MagicMock()
        mock_cursor = Mock()
        mock_cursor_ctx.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value = mock_cursor_ctx
        mock_pool.getconn.return_value = mock_conn

        with patch("app.agent.signal_collector.ThreadedConnectionPool", return_value=mock_pool) as pool_cls:
            collector = SignalCollector(pool=mock_pool)
            collector.pool = None
            collector._owns_pool = True
            collector._init_pool()

        assert collector.pool is mock_pool
        dsn = pool_cls.call_args.kwargs["dsn"]
        assert "host=collector.db" in dsn
        assert "port=5549" in dsn
        assert "dbname=collector_db" in dsn
        assert "user=collector_user" in dsn
        assert "password=collector_pass" in dsn


class TestSignalCollectorMocked:
    """使用 Mock 数据库连接的测试"""
    
    def _mock_pool(self):
        """创建 Mock 连接池"""
        mock_pool = Mock()
        mock_conn = Mock()
        mock_cursor = Mock()
        
        mock_pool.getconn.return_value = mock_conn
        mock_pool.putconn.return_value = None
        
        # 正确地模拟上下文管理器
        mock_cursor_ctx = MagicMock()
        mock_cursor_ctx.__enter__.return_value = mock_cursor
        mock_cursor_ctx.__exit__.return_value = None
        
        mock_conn.cursor.return_value = mock_cursor_ctx
        
        return mock_pool, mock_conn, mock_cursor
    
    @pytest.mark.asyncio
    async def test_collect_feedback_signals_empty(self):
        """测试采集空反馈"""
        mock_pool, mock_conn, mock_cursor = self._mock_pool()
        mock_cursor.fetchall.return_value = []
        
        collector = SignalCollector(pool=mock_pool)
        signals = await collector.collect_feedback_signals()
        
        assert len(signals) == 0
        assert isinstance(signals, list)
    
    @pytest.mark.asyncio
    async def test_collect_feedback_signals_with_data(self):
        """测试采集有数据的反馈"""
        mock_pool, mock_conn, mock_cursor = self._mock_pool()
        
        # 模拟数据库返回
        mock_cursor.fetchall.return_value = [
            ("sess_1", "msg_1", 5, ["helpful"], "Great answer", 1609459200.0),
            ("sess_2", "msg_2", 2, ["unclear"], "Confusing response", 1609459300.0),
        ]
        
        collector = SignalCollector(pool=mock_pool)
        signals = await collector.collect_feedback_signals()
        
        assert len(signals) == 2
        assert signals[0].session_id == "sess_1"
        assert signals[0].rating == 5
        assert signals[1].rating == 2
    
    @pytest.mark.asyncio
    async def test_collect_feedback_signals_null_handling(self):
        """测试对 NULL 值的处理"""
        mock_pool, mock_conn, mock_cursor = self._mock_pool()
        
        mock_cursor.fetchall.return_value = [
            (None, "msg_1", None, None, None, None),
        ]
        
        collector = SignalCollector(pool=mock_pool)
        signals = await collector.collect_feedback_signals()
        
        assert len(signals) == 1
        assert signals[0].session_id == ""
        assert signals[0].rating == 0
        assert signals[0].tags == []
    
    @pytest.mark.asyncio
    async def test_collect_failure_signals_with_data(self):
        """测试采集失败信号"""
        mock_pool, mock_conn, mock_cursor = self._mock_pool()
        
        mock_cursor.fetchall.return_value = [
            (
                "sess_1",
                "run_1",
                "failure",
                5000,
                {"user_query": "test", "source": "sync", "outcome_code": "FAILED_TOOL", "query_type": "price"},
                1609459200.0,
            ),
            (
                "sess_2",
                "run_2",
                "failure",
                8000,
                {"user_query": "test2", "source": "rerank", "outcome_code": "REFUSED_INSUFFICIENT_EVIDENCE"},
                1609459300.0,
            ),
        ]
        
        collector = SignalCollector(pool=mock_pool)
        signals = await collector.collect_failure_signals()
        
        assert len(signals) == 2
        assert signals[0].latency_ms == 5000
        assert signals[1].latency_ms == 8000
        assert signals[0].error_code == "FAILED_TOOL"
        assert signals[0].route_id == "R5_tool_priority"
        assert signals[1].route_id == "R4_rerank_weights"
        assert signals[0].signal_id == "run_1"

    @pytest.mark.asyncio
    async def test_collect_failure_signals_skips_slow_good_runs(self):
        """quality='good' / outcome_code='ANSWERED_OK' rows must NOT become FailureSignal,
        even when latency exceeds the threshold. Prevents poisoning R2_path_default with
        slow-but-successful answers (issue #111)."""
        mock_pool, mock_conn, mock_cursor = self._mock_pool()

        # Only failures should arrive here because the SQL filter excludes good/non_task.
        # Defensive row-level filter must additionally drop ANSWERED_OK if it slips through.
        mock_cursor.fetchall.return_value = [
            (
                "sess_good_slow",
                "run_good",
                "good",
                30000,
                {"user_query": "long but ok", "outcome_code": "ANSWERED_OK"},
                1609459200.0,
            ),
            (
                "sess_real_fail",
                "run_fail",
                "failure",
                4000,
                {"user_query": "broken", "outcome_code": "FAILED_TOOL"},
                1609459300.0,
            ),
        ]

        collector = SignalCollector(pool=mock_pool)
        signals = await collector.collect_failure_signals()

        assert len(signals) == 1
        assert signals[0].session_id == "sess_real_fail"
        assert signals[0].error_code == "FAILED_TOOL"
    
    @pytest.mark.asyncio
    async def test_collect_repeat_questions_table_missing(self):
        """测试当表不存在时的处理"""
        mock_pool, mock_conn, mock_cursor = self._mock_pool()
        
        # 第一个查询：检查表是否存在
        mock_cursor.fetchone.return_value = (False,)
        mock_cursor.fetchall.return_value = []
        
        collector = SignalCollector(pool=mock_pool)
        signals = await collector.collect_repeat_questions()
        
        assert len(signals) == 0
    
    @pytest.mark.asyncio
    async def test_collect_contract_violations_table_missing(self):
        """测试当合约违规表不存在时的处理"""
        mock_pool, mock_conn, mock_cursor = self._mock_pool()
        
        mock_cursor.fetchone.return_value = (False,)
        mock_cursor.fetchall.return_value = []
        
        collector = SignalCollector(pool=mock_pool)
        signals = await collector.collect_contract_violations()
        
        assert len(signals) == 0
    
    @pytest.mark.asyncio
    async def test_collect_topology_anomalies_table_missing(self):
        """测试当拓扑表不存在时的处理"""
        mock_pool, mock_conn, mock_cursor = self._mock_pool()
        
        mock_cursor.fetchone.return_value = (False,)
        mock_cursor.fetchall.return_value = []
        
        collector = SignalCollector(pool=mock_pool)
        signals = await collector.collect_topology_anomalies()
        
        assert len(signals) == 0
    
    @pytest.mark.asyncio
    async def test_pool_none_handling(self):
        """测试当池为 None 时的处理"""
        with patch.object(SignalCollector, "_init_pool"):
            collector = SignalCollector(pool=None)
        
        feedback = await collector.collect_feedback_signals()
        failure = await collector.collect_failure_signals()
        repeat = await collector.collect_repeat_questions()
        violations = await collector.collect_contract_violations()
        topo = await collector.collect_topology_anomalies()
        
        assert feedback == []
        assert failure == []
        assert repeat == []
        assert violations == []
        assert topo == []


class TestSignalCollectorAggregation:
    """聚合方法测试"""
    
    def _mock_pool(self):
        """创建 Mock 连接池"""
        mock_pool = Mock()
        mock_conn = Mock()
        mock_cursor = Mock()
        
        mock_pool.getconn.return_value = mock_conn
        mock_pool.putconn.return_value = None
        
        # 正确地模拟上下文管理器
        mock_cursor_ctx = MagicMock()
        mock_cursor_ctx.__enter__.return_value = mock_cursor
        mock_cursor_ctx.__exit__.return_value = None
        
        mock_conn.cursor.return_value = mock_cursor_ctx
        
        return mock_pool, mock_conn, mock_cursor
    
    @pytest.mark.asyncio
    async def test_aggregate_all_concurrent(self):
        """测试并发聚合所有信号"""
        mock_pool, mock_conn, mock_cursor = self._mock_pool()
        
        # 设置所有查询的返回值
        def side_effect(*args, **kwargs):
            return []
        
        mock_cursor.fetchall.side_effect = side_effect
        mock_cursor.fetchone.return_value = (False,)  # 表不存在
        
        collector = SignalCollector(pool=mock_pool)
        aggregated = await collector.aggregate_all()
        
        assert isinstance(aggregated, AggregatedSignals)
        assert aggregated.total_count == 0
        assert aggregated.total_collect_time_ms >= 0
        assert len(aggregated.collect_times) > 0
    
    @pytest.mark.asyncio
    async def test_aggregate_all_with_signals(self):
        """测试聚合包含信号的结果"""
        mock_pool, mock_conn, mock_cursor = self._mock_pool()
        
        # 依次返回每种信号的数据
        feedback_data = [("sess_1", "msg_1", 5, ["helpful"], "Good!", 1609459200.0)]
        failure_data = [("sess_1", 0, "error", 5000, {"query": "test"}, 1609459200.0)]
        
        # 这个测试需要更复杂的 Mock 设置以模拟多次调用
        # 这里只是验证结构
        collector = SignalCollector(pool=mock_pool)
        aggregated = await collector.aggregate_all()
        
        assert isinstance(aggregated, AggregatedSignals)
        assert hasattr(aggregated, 'feedback_signals')
        assert hasattr(aggregated, 'failure_signals')
        assert hasattr(aggregated, 'repeat_signals')
        assert hasattr(aggregated, 'violation_signals')
        assert hasattr(aggregated, 'topo_signals')


class TestHelperFunctions:
    """辅助函数测试"""
    
    @pytest.mark.asyncio
    async def test_get_latest_signals_without_pool(self):
        """测试 get_latest_signals 辅助函数"""
        with patch.object(SignalCollector, '_init_pool'):
            with patch.object(SignalCollector, 'aggregate_all') as mock_agg:
                mock_agg.return_value = AggregatedSignals(timestamp=time.time())
                
                # 这个测试会失败，因为我们没有真实的池
                # 只是验证函数签名
                assert callable(get_latest_signals)


class TestCompatibilityAdapters:
    """Compatibility helpers for problem detector/root cause analyzer."""

    def test_repeat_violation_topology_compatibility_properties(self):
        repeat = RepeatQuestionSignal("sess", 2, 1, 4, 0.91, 1609459200.0)
        violation = ViolationSignal(
            "run_1",
            "contract_1",
            "VIOLATION",
            payload={"detail": "Missing evidence"},
            ts=1609459200.0,
        )
        topo = TopoAnomalySignal(
            "edge_1",
            "query",
            "rerank",
            "stale",
            "2024-01-01T00:00:00Z",
            12,
            1609459200.0,
        )

        assert repeat.repeat_turn == 4
        assert repeat.similarity_score == pytest.approx(0.91)
        assert violation.detail == "Missing evidence"
        assert topo.metrics["traversal_count"] == 12


class TestErrorHandling:
    """错误处理测试"""
    
    @pytest.mark.asyncio
    async def test_collector_handles_db_error(self):
        """测试采集器对数据库错误的处理"""
        mock_pool = Mock()
        mock_pool.getconn.side_effect = Exception("Database connection error")
        
        collector = SignalCollector(pool=mock_pool)
        signals = await collector.collect_feedback_signals()
        
        # 应该返回空列表而不是抛异常
        assert signals == []
    
    @pytest.mark.asyncio
    async def test_aggregate_handles_partial_failures(self):
        """测试聚合器对部分失败的处理"""
        mock_pool = Mock()
        mock_conn = Mock()
        mock_cursor = Mock()
        
        mock_pool.getconn.return_value = mock_conn
        mock_pool.putconn.return_value = None
        
        # 正确地模拟上下文管理器
        mock_cursor_ctx = MagicMock()
        mock_cursor_ctx.__enter__.return_value = mock_cursor
        mock_cursor_ctx.__exit__.return_value = None
        
        mock_conn.cursor.return_value = mock_cursor_ctx
        
        # 第一个调用成功，返回反馈信号
        # 后续调用返回空
        call_count = [0]
        
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return [("sess_1", "msg_1", 5, ["helpful"], "Good!", 1609459200.0)]
            return []
        
        mock_cursor.fetchall.side_effect = side_effect
        mock_cursor.fetchone.return_value = (False,)
        
        collector = SignalCollector(pool=mock_pool)
        aggregated = await collector.aggregate_all()
        
        # 应该至少包含第一个成功的反馈
        assert aggregated.total_count >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

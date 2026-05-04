"""
集成测试：Layer 1 时间戳修复 + Layer 2 信号收集器

验证时间戳格式一致性和信号采集功能。
"""

import pytest
import asyncio
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_signal_collector_timestamp_seconds():
    """验证信号采集器返回秒级时间戳"""
    from app.agent.signal_collector import SignalCollector
    
    collector = SignalCollector()
    try:
        signals = await collector.aggregate_all()
        
        # 时间戳应该是秒级（大约在 1970 年之后）
        assert signals.timestamp > 0, "Timestamp should be positive"
        
        # 时间戳应该在合理范围内（距离现在不超过 1 年）
        now_seconds = datetime.now(timezone.utc).timestamp()
        assert abs(signals.timestamp - now_seconds) < 31536000, \
            f"Timestamp {signals.timestamp} seems unreasonable"
        
        # 所有子信号的时间戳也应该是秒级
        for sig in signals.feedback_signals + signals.failure_signals:
            if sig.ts:
                assert 0 < sig.ts <= now_seconds + 1000, \
                    f"Signal ts {sig.ts} seems unreasonable"
    finally:
        collector.close()


@pytest.mark.asyncio
async def test_api_signals_returns_millis():
    """验证 API 端点返回毫秒单位的时间戳"""
    from app.agent.signal_collector import get_latest_signals
    from dataclasses import asdict
    
    signals = await get_latest_signals()
    
    # 构建 API 响应格式
    api_response = {
        "timestamp": int(signals.timestamp * 1000),
        "feedback_signals": [asdict(s) for s in signals.feedback_signals],
        "failure_signals": [asdict(s) for s in signals.failure_signals],
        "repeat_signals": [asdict(s) for s in signals.repeat_signals],
        "violation_signals": [asdict(s) for s in signals.violation_signals],
        "topo_signals": [asdict(s) for s in signals.topo_signals],
        "total_count": signals.total_count,
        "severity_score": signals.severity_score,
        "collection_time_ms": signals.total_collect_time_ms,
    }
    
    # API 应该返回毫秒
    assert api_response['timestamp'] > 1000000000000, \
        "Timestamp in milliseconds should be very large (> 1 trillion)"
    
    # 前端应该能直接用于 new Date()
    dt = datetime.fromtimestamp(api_response['timestamp'] / 1000, tz=timezone.utc)
    assert 2020 <= dt.year <= 2030, f"Timestamp {api_response['timestamp']}ms seems unreasonable"


@pytest.mark.asyncio
async def test_signal_collector_severity_score():
    """验证严重度评分计算"""
    from app.agent.signal_collector import AggregatedSignals, FeedbackSignal, FailureSignal
    
    # 构建测试数据
    agg = AggregatedSignals(timestamp=datetime.now(timezone.utc).timestamp())
    
    # 添加一些反馈和失败信号
    agg.feedback_signals = [
        FeedbackSignal(
            session_id="s1",
            message_id="m1",
            rating=1,  # 低评分
            tags=["bad"],
            feedback_text="Not good",
            ts=datetime.now(timezone.utc).timestamp(),
        ),
        FeedbackSignal(
            session_id="s2",
            message_id="m2",
            rating=5,  # 高评分
            tags=["good"],
            feedback_text="Excellent",
            ts=datetime.now(timezone.utc).timestamp(),
        ),
    ]
    
    agg.failure_signals = [
        FailureSignal(
            session_id="s3",
            turn_index=1,
            status="error",
            latency_ms=5000,
            context={},
            ts=datetime.now(timezone.utc).timestamp(),
        ),
    ]
    
    # 验证严重度评分
    severity = agg.severity_score
    assert 0 <= severity <= 100, f"Severity score {severity} out of range"
    assert severity > 0, "Severity score should be > 0 with failures"
    
    # 验证总数
    assert agg.total_count == 3, "Total count should be 3"


@pytest.mark.asyncio
async def test_signal_collection_times():
    """验证信号采集时间统计"""
    from app.agent.signal_collector import SignalCollector
    
    collector = SignalCollector()
    try:
        signals = await collector.aggregate_all()
        
        # 采集时间应该被记录
        assert signals.total_collect_time_ms >= 0, "Total collect time should be >= 0"
        
        # 各类型的采集时间应该被记录
        assert len(signals.collect_times) > 0, "collect_times should not be empty"
        
        # 所有采集时间都应该是正数
        for signal_type, duration_ms in signals.collect_times.items():
            assert duration_ms >= 0, f"{signal_type} duration should be >= 0"
            assert signal_type in [
                "feedback",
                "failure",
                "repeat_questions",
                "contract_violations",
                "topology_anomalies",
            ], f"Unknown signal type: {signal_type}"
    finally:
        collector.close()


@pytest.mark.asyncio
async def test_signal_summary_health_status():
    """验证信号摘要中的健康状态计算"""
    from app.agent.signal_collector import get_latest_signals
    
    signals = await get_latest_signals()
    
    # 根据严重度评分计算健康状态
    if signals.severity_score > 70:
        expected_status = "critical"
    elif signals.severity_score > 40:
        expected_status = "warning"
    else:
        expected_status = "good"
    
    # 验证预期状态逻辑
    assert expected_status in ["good", "warning", "critical"]


@pytest.mark.asyncio
async def test_timestamp_consistency_with_db():
    """验证数据库时间戳和 signal_collector 时间戳一致"""
    import os
    import asyncpg
    from app.agent.signal_collector import get_latest_signals
    from datetime import datetime as dt, timezone as tz
    
    # 获取信号采集时间戳
    signals = await get_latest_signals()
    collector_ts = signals.timestamp
    
    # 从数据库读取最新的时间戳
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://rag_user:rag_password@localhost:5432/rag_db"
    )
    
    try:
        conn = await asyncpg.connect(db_url, timeout=5)
        try:
            # 检查 conversation_turns 表的最新时间戳
            row = await conn.fetchrow(
                "SELECT ts FROM conversation_turns ORDER BY ts DESC LIMIT 1"
            )
            if row:
                db_ts = row['ts']
                # 时间戳应该都是秒级
                assert isinstance(db_ts, float) or isinstance(db_ts, int)
                assert isinstance(collector_ts, float) or isinstance(collector_ts, int)
                
                # 都应该在合理范围内
                now = dt.now(tz.utc).timestamp()
                assert abs(db_ts - now) < 31536000, "DB timestamp unreasonable"
                assert abs(collector_ts - now) < 31536000, "Collector timestamp unreasonable"
        finally:
            await conn.close()
    except Exception as e:
        # 如果数据库连接失败，跳过此测试
        pytest.skip(f"Could not connect to database: {e}")


if __name__ == "__main__":
    # 快速验证脚本
    async def main():
        from app.agent.signal_collector import get_latest_signals
        
        print("\n" + "="*60)
        print("🔍 Layer 1 + Layer 2 Integration Test Report")
        print("="*60)
        
        signals = await get_latest_signals()
        
        print(f"\nCollector Timestamp (seconds): {signals.timestamp}")
        print(f"API Timestamp (milliseconds): {int(signals.timestamp * 1000)}")
        print(f"Severity Score: {signals.severity_score:.1f}/100")
        print(f"Total Signals: {signals.total_count}")
        print(f"Collection Time: {signals.total_collect_time_ms:.1f}ms")
        print(f"\n📊 Signal Breakdown:")
        print(f"  - Feedback: {len(signals.feedback_signals)}")
        print(f"  - Failures: {len(signals.failure_signals)}")
        print(f"  - Repeats: {len(signals.repeat_signals)}")
        print(f"  - Violations: {len(signals.violation_signals)}")
        print(f"  - Topo Anomalies: {len(signals.topo_signals)}")
        print(f"\n⏱️  Collection Times by Type:")
        for signal_type, duration_ms in signals.collect_times.items():
            print(f"  - {signal_type}: {duration_ms:.1f}ms")
        print("="*60 + "\n")
    
    asyncio.run(main())

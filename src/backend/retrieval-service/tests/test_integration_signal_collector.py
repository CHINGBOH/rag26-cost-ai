"""
集成测试 - Signal Collector 与真实数据库连接
"""

import asyncio
import os
import pytest

# Only run if DATABASE is available
pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_DB_TESTS") == "1",
    reason="Database integration tests skipped"
)


@pytest.mark.asyncio
async def test_signal_collector_with_real_db():
    """测试信号采集器与真实数据库的完整流程"""
    from app.agent.signal_collector import SignalCollector, AggregatedSignals
    
    collector = SignalCollector()
    try:
        if collector.pool is None:
            pytest.skip("Database connection failed")
        
        # 采集信号
        signals = await collector.aggregate_all()
        
        # 验证返回类型
        assert isinstance(signals, AggregatedSignals)
        
        # 验证采集时间
        assert signals.total_collect_time_ms >= 0
        
        # 验证严重度分值在有效范围内
        assert 0 <= signals.severity_score <= 100
        
        # 验证各类型信号都被采集
        assert hasattr(signals, 'feedback_signals')
        assert hasattr(signals, 'failure_signals')
        assert hasattr(signals, 'repeat_signals')
        assert hasattr(signals, 'violation_signals')
        assert hasattr(signals, 'topo_signals')
        
        # 验证采集时间记录
        assert len(signals.collect_times) == 5
        
        print(f"\n✅ Integration test passed!")
        print(f"   Total signals: {signals.total_count}")
        print(f"   Severity: {signals.severity_score:.1f}/100")
        print(f"   Duration: {signals.total_collect_time_ms:.1f}ms")
    
    finally:
        collector.close()


@pytest.mark.asyncio
async def test_signal_collector_concurrent_performance():
    """测试并发采集的性能"""
    from app.agent.signal_collector import get_latest_signals
    import time
    
    # 运行多次采集以测试并发性能
    start = time.time()
    
    tasks = [get_latest_signals() for _ in range(3)]
    results = await asyncio.gather(*tasks)
    
    duration = time.time() - start
    
    # 验证所有结果都成功返回
    assert len(results) == 3
    for signals in results:
        assert signals.total_count >= 0
    
    print(f"\n✅ Concurrent performance test passed!")
    print(f"   3 concurrent collections in {duration:.2f}s")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

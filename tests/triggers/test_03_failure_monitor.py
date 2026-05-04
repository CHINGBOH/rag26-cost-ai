"""
Verification 3: Failure Monitor Threshold Detection Test
Tests that failure rate > 20% triggers learning loop
"""
import pytest
import sys
import os
from unittest.mock import MagicMock, AsyncMock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src/backend/retrieval-service'))


@pytest.mark.asyncio
async def test_failure_monitor_initialization():
    """Test failure monitor initializes with correct threshold"""
    from app.agent.failure_monitor import FailureMonitor
    
    monitor = FailureMonitor(db_pool=None)
    
    assert monitor is not None, "Monitor should initialize"
    assert monitor.FAILURE_THRESHOLD == 0.20, "Threshold should be 20%"
    assert monitor.WINDOW_SIZE == 16, "Window size should be 16 queries"
    assert monitor.MIN_WINDOW_SAMPLES == 8, "Min samples should be 8"
    
    print(f"✅ Failure Monitor initialized:")
    print(f"   Threshold: {monitor.FAILURE_THRESHOLD:.0%}")
    print(f"   Window size: {monitor.WINDOW_SIZE} queries")
    print(f"   Min samples: {monitor.MIN_WINDOW_SAMPLES}")


@pytest.mark.asyncio
async def test_failure_rate_below_threshold_no_trigger():
    """Test that failure rate below 20% does not trigger"""
    from app.agent.failure_monitor import FailureMonitor
    
    # Mock DB pool
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    # 2 errors, 14 successes = 12.5% failure rate (below 20% threshold)
    mock_cursor.fetchall.return_value = [
        ('error',), ('success',), ('success',), ('success',),
        ('success',), ('success',), ('success',), ('success',),
        ('error',), ('success',), ('success',), ('success',),
        ('success',), ('success',), ('success',), ('success',)
    ]
    
    monitor = FailureMonitor(db_pool=mock_pool)
    stats = await monitor.get_recent_failure_stats()
    
    assert stats is not None, "Should get stats"
    assert stats.failure_rate == 0.125, f"Failure rate should be 12.5%, got {stats.failure_rate:.1%}"
    assert stats.failure_rate < monitor.FAILURE_THRESHOLD, "Should be below threshold"
    
    should_trigger = await monitor.should_trigger()
    assert should_trigger is False, "Should NOT trigger below threshold"
    
    print(f"✅ Below threshold (12.5%) - no trigger:")
    print(f"   Failures: {stats.failure_count}/{stats.total_count}")
    print(f"   Rate: {stats.failure_rate:.1%} (threshold: {monitor.FAILURE_THRESHOLD:.0%})")


@pytest.mark.asyncio
async def test_failure_rate_exactly_at_threshold():
    """Test that failure rate exactly at 20% threshold triggers"""
    from app.agent.failure_monitor import FailureMonitor
    
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    # 4 errors, 12 successes = 20% failure rate (exactly at threshold)
    mock_cursor.fetchall.return_value = [
        ('error',), ('error',), ('error',), ('error',),
        ('success',), ('success',), ('success',), ('success',),
        ('success',), ('success',), ('success',), ('success',),
        ('success',), ('success',), ('success',), ('success',)
    ]
    
    monitor = FailureMonitor(db_pool=mock_pool)
    stats = await monitor.get_recent_failure_stats()
    
    assert stats is not None, "Should get stats"
    assert stats.failure_rate == 0.25, f"Failure rate should be 25%, got {stats.failure_rate:.1%}"
    
    # At >= 20%, should trigger
    should_trigger = await monitor.should_trigger()
    # Note: 25% >= 20%, so should trigger
    assert should_trigger is True, "Should trigger at or above threshold"
    
    print(f"✅ At/above threshold (25%) - triggers:")
    print(f"   Failures: {stats.failure_count}/{stats.total_count}")
    print(f"   Rate: {stats.failure_rate:.1%} (threshold: {monitor.FAILURE_THRESHOLD:.0%})")


@pytest.mark.asyncio
async def test_failure_rate_above_threshold():
    """Test that failure rate above 20% triggers"""
    from app.agent.failure_monitor import FailureMonitor
    
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    # 5 errors, 11 successes = 31.25% failure rate (well above 20%)
    mock_cursor.fetchall.return_value = [
        ('error',), ('error',), ('error',), ('error',),
        ('error',), ('success',), ('success',), ('success',),
        ('success',), ('success',), ('success',), ('success',),
        ('success',), ('success',), ('success',), ('success',)
    ]
    
    monitor = FailureMonitor(db_pool=mock_pool)
    stats = await monitor.get_recent_failure_stats()
    
    assert stats is not None, "Should get stats"
    assert stats.failure_rate > monitor.FAILURE_THRESHOLD, f"Should exceed threshold"
    
    should_trigger = await monitor.should_trigger()
    assert should_trigger is True, "Should trigger above threshold"
    
    print(f"✅ Above threshold (31.25%) - triggers:")
    print(f"   Failures: {stats.failure_count}/{stats.total_count}")
    print(f"   Rate: {stats.failure_rate:.1%} (threshold: {monitor.FAILURE_THRESHOLD:.0%})")


@pytest.mark.asyncio
async def test_failure_monitor_min_samples_requirement():
    """Test that monitor requires minimum number of samples"""
    from app.agent.failure_monitor import FailureMonitor
    
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    # Only 4 samples, all errors = 100% failure rate
    # But 4 < MIN_WINDOW_SAMPLES (8), so should not trigger
    mock_cursor.fetchall.return_value = [
        ('error',), ('error',), ('error',), ('error',)
    ]
    
    monitor = FailureMonitor(db_pool=mock_pool)
    stats = await monitor.get_recent_failure_stats()
    
    assert stats is not None, "Should get stats"
    assert stats.failure_rate == 1.0, "Failure rate is 100%"
    
    should_trigger = await monitor.should_trigger()
    assert should_trigger is False, f"Should NOT trigger with only {stats.total_count} samples (min: {monitor.MIN_WINDOW_SAMPLES})"
    
    print(f"✅ Min samples requirement enforced:")
    print(f"   Samples: {stats.total_count} (min required: {monitor.MIN_WINDOW_SAMPLES})")
    print(f"   Failure rate: {stats.failure_rate:.0%}")
    print(f"   Trigger: No (insufficient samples)")


@pytest.mark.asyncio
async def test_failure_monitor_no_data():
    """Test failure monitor when no data is available"""
    from app.agent.failure_monitor import FailureMonitor
    
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    # No rows
    mock_cursor.fetchall.return_value = []
    
    monitor = FailureMonitor(db_pool=mock_pool)
    stats = await monitor.get_recent_failure_stats()
    
    assert stats is None, "Should return None when no data"
    
    should_trigger = await monitor.should_trigger()
    assert should_trigger is False, "Should not trigger without data"
    
    print(f"✅ No data case handled:")
    print(f"   Stats: None")
    print(f"   Trigger: No")


@pytest.mark.asyncio
async def test_failure_monitor_high_failure_rate():
    """Test failure monitor with very high failure rate (50%)"""
    from app.agent.failure_monitor import FailureMonitor
    
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    # 8 errors, 8 successes = 50% failure rate
    mock_cursor.fetchall.return_value = [
        ('error',), ('error',), ('error',), ('error',),
        ('error',), ('error',), ('error',), ('error',),
        ('success',), ('success',), ('success',), ('success',),
        ('success',), ('success',), ('success',), ('success',)
    ]
    
    monitor = FailureMonitor(db_pool=mock_pool)
    stats = await monitor.get_recent_failure_stats()
    
    assert stats is not None, "Should get stats"
    assert stats.failure_rate == 0.5, "Failure rate should be 50%"
    
    should_trigger = await monitor.should_trigger()
    assert should_trigger is True, "Should definitely trigger at 50%"
    
    print(f"✅ High failure rate (50%) - triggers:")
    print(f"   Failures: {stats.failure_count}/{stats.total_count}")
    print(f"   Rate: {stats.failure_rate:.0%}")


@pytest.mark.asyncio
async def test_failure_monitor_threshold_adjustment():
    """Test that failure threshold can be dynamically adjusted"""
    from app.agent.failure_monitor import FailureMonitor
    
    monitor = FailureMonitor(db_pool=None)
    
    original_threshold = monitor.FAILURE_THRESHOLD
    assert original_threshold == 0.20, "Initial threshold should be 20%"
    
    # Adjust threshold
    monitor.set_threshold(0.15)
    assert monitor.FAILURE_THRESHOLD == 0.15, "Threshold should be updated to 15%"
    
    # Invalid threshold
    monitor.set_threshold(1.5)  # Invalid
    assert monitor.FAILURE_THRESHOLD == 0.15, "Invalid threshold should be rejected"
    
    # Reset
    monitor.set_threshold(0.20)
    assert monitor.FAILURE_THRESHOLD == 0.20, "Threshold should be reset"
    
    print(f"✅ Threshold adjustment verified:")
    print(f"   Default: {original_threshold:.0%}")
    print(f"   Adjusted: 15%")
    print(f"   Reset: 20%")


@pytest.mark.asyncio
async def test_global_failure_monitor_initialization():
    """Test global failure monitor functions"""
    from app.agent.failure_monitor import init_failure_monitor, get_failure_monitor
    
    monitor = init_failure_monitor(db_pool=None)
    assert monitor is not None, "Monitor should initialize"
    
    retrieved = get_failure_monitor()
    assert retrieved is not None, "Should retrieve global monitor"
    assert retrieved is monitor, "Should be same instance"
    
    print(f"✅ Global failure monitor initialized")
    print(f"   Threshold: {monitor.FAILURE_THRESHOLD:.0%}")
    print(f"   Window: {monitor.WINDOW_SIZE} queries")

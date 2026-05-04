"""
Shared test fixtures for trigger verification tests
"""
import pytest
import asyncio
import sys
import os
from unittest.mock import Mock, MagicMock, AsyncMock
from datetime import datetime, timedelta

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src/backend/retrieval-service'))


@pytest.fixture
def mock_db_pool():
    """Create a mock database pool for testing"""
    pool = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()
    
    pool.getconn.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = None
    
    return pool, conn, cursor


@pytest.fixture
def mock_pool_with_learning_runs(mock_db_pool):
    """Mock pool that returns learning_runs data"""
    pool, conn, cursor = mock_db_pool
    
    # Mock learning_runs table queries
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    cursor.fetch.return_value = []
    
    return pool


@pytest.fixture
def event_loop():
    """Create an event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def signal_collector_mock():
    """Mock SignalCollector for testing"""
    collector = AsyncMock()
    collector.aggregate_all = AsyncMock()
    collector.aggregate_all.return_value = MagicMock(
        total_count=10,
        severity_score=45.5,
        total_collect_time_ms=250.0
    )
    return collector


@pytest.fixture
async def problem_detector_mock():
    """Mock ProblemDetector for testing"""
    detector = AsyncMock()
    detector.detect_problems = AsyncMock(return_value=[])
    return detector


@pytest.fixture
def scheduler_mock():
    """Mock scheduler instance"""
    from app.agent.scheduler import LearningScheduler
    scheduler = MagicMock(spec=LearningScheduler)
    scheduler.trigger_manual = AsyncMock(return_value='run_manual_test_20240505_120000')
    return scheduler


@pytest.fixture
def failure_monitor_mock():
    """Mock failure monitor instance"""
    from app.agent.failure_monitor import FailureMonitor
    monitor = MagicMock(spec=FailureMonitor)
    monitor.check_and_trigger = AsyncMock(return_value=None)
    monitor.get_recent_failure_stats = AsyncMock(return_value=None)
    monitor.should_trigger = AsyncMock(return_value=False)
    return monitor


@pytest.fixture
def feedback_analyzer_mock():
    """Mock feedback analyzer instance"""
    from app.agent.feedback_analyzer import FeedbackAnalyzer
    analyzer = MagicMock(spec=FeedbackAnalyzer)
    analyzer.analyze_feedback_trends = AsyncMock(return_value=None)
    analyzer.trigger_if_needed = AsyncMock(return_value=None)
    analyzer.get_insights = AsyncMock(return_value=None)
    return analyzer

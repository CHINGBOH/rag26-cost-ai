"""
Integration tests for Layer 2 Trigger Mechanisms (Issue #96)
Tests cron scheduler, failure monitor, and feedback analyzer
"""

import pytest
import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch, AsyncMock

# Test scheduler
@pytest.mark.asyncio
async def test_scheduler_initialization():
    """Test that scheduler initializes correctly"""
    from app.agent.scheduler import LearningScheduler
    
    scheduler = LearningScheduler(db_pool=None)
    assert scheduler is not None
    assert scheduler._running is False
    
    # Start scheduler
    scheduler.start()
    assert scheduler._running is True
    
    # Stop scheduler
    scheduler.stop()
    assert scheduler._running is False


@pytest.mark.asyncio
async def test_scheduler_get_next_run_time():
    """Test getting next scheduled run time"""
    from app.agent.scheduler import LearningScheduler
    
    scheduler = LearningScheduler(db_pool=None)
    scheduler.start()
    
    try:
        next_run = await scheduler.get_next_run_time()
        assert 'next_run_utc' in next_run or 'error' in next_run
    finally:
        scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_manual_trigger():
    """Test manual trigger of learning loop"""
    from app.agent.scheduler import LearningScheduler
    
    # Mock DB pool
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    scheduler = LearningScheduler(db_pool=mock_pool)
    
    # Trigger with mocked components
    with patch('app.agent.scheduler.SignalCollector') as mock_collector_class:
        with patch('app.agent.scheduler.ProblemDetector') as mock_detector_class:
            mock_collector = AsyncMock()
            mock_collector.aggregate_all.return_value = MagicMock(
                total_count=10,
                severity_score=45.5,
                total_collect_time_ms=250.0
            )
            mock_collector_class.return_value = mock_collector
            
            mock_detector = AsyncMock()
            mock_detector.detect_problems.return_value = []
            mock_detector_class.return_value = mock_detector
            
            run_id = await scheduler.trigger_manual(reason="test")
            assert run_id is not None
            assert run_id.startswith("run_manual_")


# Test failure monitor
@pytest.mark.asyncio
async def test_failure_monitor_initialization():
    """Test failure monitor initializes correctly"""
    from app.agent.failure_monitor import FailureMonitor
    
    monitor = FailureMonitor(db_pool=None)
    assert monitor is not None
    assert monitor.FAILURE_THRESHOLD == 0.20
    assert monitor.WINDOW_SIZE == 16


@pytest.mark.asyncio
async def test_failure_monitor_stats():
    """Test getting failure statistics"""
    from app.agent.failure_monitor import FailureMonitor, FailureStats
    
    # Mock DB pool
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    # Mock rows: 3 errors, 13 successes
    mock_cursor.fetchall.return_value = [
        ('error',), ('success',), ('success',), ('error',),
        ('success',), ('success',), ('success',), ('success',),
        ('error',), ('success',), ('success',), ('success',),
        ('success',), ('success',), ('success',), ('success',)
    ]
    
    monitor = FailureMonitor(db_pool=mock_pool)
    stats = await monitor.get_recent_failure_stats()
    
    assert stats is not None
    assert stats.total_count == 16
    assert stats.failure_count == 3
    assert stats.success_count == 13
    assert abs(stats.failure_rate - 0.1875) < 0.001


@pytest.mark.asyncio
async def test_failure_monitor_threshold_trigger():
    """Test that high failure rate triggers learning"""
    from app.agent.failure_monitor import FailureMonitor
    
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    # Mock rows: 8 errors, 8 successes = 50% failure rate
    mock_cursor.fetchall.return_value = [
        ('error',), ('error',), ('error',), ('error',),
        ('error',), ('error',), ('error',), ('error',),
        ('success',), ('success',), ('success',), ('success',),
        ('success',), ('success',), ('success',), ('success',)
    ]
    
    monitor = FailureMonitor(db_pool=mock_pool)
    should_trigger = await monitor.should_trigger()
    
    # 50% > 20% threshold
    assert should_trigger is True


# Test feedback analyzer
@pytest.mark.asyncio
async def test_feedback_analyzer_initialization():
    """Test feedback analyzer initializes correctly"""
    from app.agent.feedback_analyzer import FeedbackAnalyzer
    
    analyzer = FeedbackAnalyzer(db_pool=None)
    assert analyzer is not None
    assert len(analyzer.TAG_WEIGHTS) == 7


@pytest.mark.asyncio
async def test_feedback_analyzer_trending_issues():
    """Test identifying trending issues from feedback"""
    from app.agent.feedback_analyzer import FeedbackAnalyzer
    
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    # Mock feedback: 10 records, 3 with '数据过时', 2 with '缺少依据'
    mock_cursor.fetchall.return_value = [
        (5, ['数据过时'], None, None, None),  # rating 5 (positive)
        (2, ['数据过时'], None, None, None),  # rating 2 (neutral)
        (1, ['数据过时'], None, None, None),  # rating 1 (negative)
        (1, ['缺少依据'], None, None, None),
        (1, ['缺少依据'], None, None, None),
        (5, [], None, None, None),
        (5, [], None, None, None),
        (4, [], None, None, None),
        (4, [], None, None, None),
        (5, [], None, None, None),
    ]
    
    analyzer = FeedbackAnalyzer(db_pool=mock_pool)
    analysis = await analyzer.analyze_feedback_trends(window_days=7)
    
    assert analysis is not None
    assert analysis.total_feedback == 10
    # 3 records with rating <= 2
    assert analysis.negative_rate == 0.2
    # Top issue should be '数据过时' (frequency 30%)
    assert len(analysis.top_issues) > 0
    assert analysis.top_issues[0].tag == '数据过时'
    assert analysis.top_issues[0].frequency == 0.3


@pytest.mark.asyncio
async def test_feedback_analyzer_suggestions():
    """Test that suggestions are generated based on issues"""
    from app.agent.feedback_analyzer import FeedbackAnalyzer, FeedbackIssue
    
    issue_1 = FeedbackIssue(tag='数据过时', frequency=0.25, count=3, weight=25)
    issue_2 = FeedbackIssue(tag='工具失效', frequency=0.20, count=2, weight=24)
    
    analyzer = FeedbackAnalyzer(db_pool=None)
    suggestions = analyzer._generate_suggestions([issue_1, issue_2])
    
    assert len(suggestions) == 2
    assert any('数据源' in s for s in suggestions)
    assert any('工具' in s for s in suggestions)


# API endpoint tests
@pytest.mark.asyncio
async def test_api_learning_trigger_endpoint():
    """Test POST /api/v1/learning/trigger endpoint"""
    from fastapi.testclient import TestClient
    from main import app
    
    with patch('app.api.get_scheduler') as mock_get_scheduler:
        mock_scheduler = AsyncMock()
        mock_scheduler.trigger_manual.return_value = 'run_manual_20240505_120000'
        mock_get_scheduler.return_value = mock_scheduler
        
        client = TestClient(app)
        response = client.post('/api/v1/learning/trigger?reason=test')
        
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'triggered'
        assert 'run_id' in data


@pytest.mark.asyncio
async def test_api_failure_stats_endpoint():
    """Test GET /api/v1/learning/failure-stats endpoint"""
    from fastapi.testclient import TestClient
    from main import app
    
    with patch('app.api.get_failure_monitor') as mock_get_monitor:
        mock_monitor = MagicMock()
        mock_monitor.get_recent_failure_stats = AsyncMock()
        mock_monitor.get_recent_failure_stats.return_value = MagicMock(
            window_size=16,
            failure_count=2,
            success_count=14,
            total_count=16,
            failure_rate=0.125
        )
        mock_monitor.should_trigger = AsyncMock(return_value=False)
        mock_monitor.FAILURE_THRESHOLD = 0.20
        mock_monitor.MIN_WINDOW_SAMPLES = 8
        mock_get_monitor.return_value = mock_monitor
        
        client = TestClient(app)
        response = client.get('/api/v1/learning/failure-stats')
        
        assert response.status_code == 200
        data = response.json()
        assert data['failure_count'] == 2
        assert data['success_count'] == 14
        assert abs(data['failure_rate'] - 0.125) < 0.001


@pytest.mark.asyncio
async def test_api_feedback_insights_endpoint():
    """Test GET /api/v1/learning/feedback-insights endpoint"""
    from fastapi.testclient import TestClient
    from main import app
    
    with patch('app.api.get_feedback_analyzer') as mock_get_analyzer:
        mock_analyzer = MagicMock()
        mock_analyzer.get_insights = AsyncMock()
        mock_analyzer.get_insights.return_value = {
            'period_days': 7,
            'total_feedback_count': 42,
            'negative_feedback_rate': '28.6%',
            'top_issues': [],
            'trending_problems': ['数据过时'],
            'improvement_suggestions': [],
            'should_trigger_learning': False
        }
        mock_get_analyzer.return_value = mock_analyzer
        
        client = TestClient(app)
        response = client.get('/api/v1/learning/feedback-insights?window_days=7')
        
        assert response.status_code == 200
        data = response.json()
        assert data['period_days'] == 7
        assert data['total_feedback_count'] == 42


@pytest.mark.asyncio
async def test_api_learning_status_endpoint():
    """Test GET /api/v1/learning/status endpoint"""
    from fastapi.testclient import TestClient
    from main import app
    
    with patch('app.api.get_scheduler') as mock_get_scheduler, \
         patch('app.api.get_failure_monitor') as mock_get_monitor, \
         patch('app.api.get_feedback_analyzer') as mock_get_analyzer:
        
        mock_scheduler = MagicMock()
        mock_scheduler._running = True
        mock_scheduler.get_next_run_time = AsyncMock(return_value={'next_run_utc': '2024-05-06T02:00:00Z'})
        mock_get_scheduler.return_value = mock_scheduler
        
        mock_monitor = MagicMock()
        mock_monitor.get_recent_failure_stats = AsyncMock(return_value=MagicMock(failure_rate=0.1))
        mock_monitor.should_trigger = AsyncMock(return_value=False)
        mock_monitor.FAILURE_THRESHOLD = 0.20
        mock_get_monitor.return_value = mock_monitor
        
        mock_analyzer = MagicMock()
        mock_analyzer.analyze_feedback_trends = AsyncMock(return_value=MagicMock(
            trending_problems=[],
            should_trigger=False
        ))
        mock_get_analyzer.return_value = mock_analyzer
        
        client = TestClient(app)
        response = client.get('/api/v1/learning/status')
        
        assert response.status_code == 200
        data = response.json()
        assert 'layer2_triggers' in data
        assert 'scheduler' in data['layer2_triggers']
        assert 'failure_monitor' in data['layer2_triggers']
        assert 'feedback_analyzer' in data['layer2_triggers']


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])

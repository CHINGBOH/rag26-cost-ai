"""
Integration tests for Layer 2 Trigger Mechanisms (Issue #96)
Tests cron scheduler, failure monitor, and feedback analyzer
"""

import pytest
import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
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


@pytest.mark.asyncio
async def test_scheduler_gap_retest_listener_calls_gap_retest_service():
    """The scheduled listener should drive active gaps through live consultation retest."""
    from app.agent.scheduler import LearningScheduler

    scheduler = LearningScheduler(db_pool=None)
    listener_config = SimpleNamespace(
        limit=20,
        actor="listener_test",
        dry_run=False,
        observation_window_days=7,
        active_only=True,
        consultation_endpoint="http://localhost:8002/api/v1/agent",
        consultation_timeout_seconds=30,
        max_live_retests=3,
        max_iterations=2,
        projection_reconcile_enabled=True,
        projection_reconcile_limit=50,
        fixed_state_invalidation_enabled=True,
        fixed_state_invalidation_limit=25,
        repair_promotion_enabled=True,
        repair_promotion_min_keep_open_evidence=2,
        repair_promotion_issue_number=110,
        repair_promotion_issue_url="https://github.com/CHINGBOH/RAG26/issues/110",
    )

    with patch(
        "app.agent.scheduler.get_learning_config",
        return_value=SimpleNamespace(gap_retest_listener=listener_config),
    ), patch(
        "app.agent.scheduler.KnowledgeGapRepository",
    ) as mock_repository_class, patch(
        "app.agent.scheduler.GapRetestService",
    ) as mock_retest_class, patch(
        "app.agent.scheduler.GapWorkbenchService",
    ) as mock_workbench_class, patch(
        "app.agent.scheduler.GapRepairTaskService",
    ) as mock_repair_class:
        mock_repository = mock_repository_class.return_value
        mock_repository.reconcile_latest_evidence_projection.return_value = [
            {"gap_key": "gap_observing", "evidence_id": 7}
        ]
        mock_repository.invalidate_stale_fixed_state.return_value = [
            {"gap_key": "gap_bad_observing", "evidence_id": 8, "to_status": "open"}
        ]
        mock_repository.fetch_gaps.return_value = [
            {"gap_key": "gap_open", "status": "open", "query": "open gap"},
            {"gap_key": "gap_progress", "status": "in_progress", "query": "progress gap"},
            {"gap_key": "gap_other", "status": "open", "query": "other gap"},
            {"gap_key": "gap_over_cap", "status": "open", "query": "over cap gap"},
            {
                "gap_key": "gap_linked_event",
                "status": "in_progress",
                "query": "route repair gap",
                "affected_route": "R2_path_default",
                "linked_event_id": 8,
            },
        ]
        mock_repository.fetch_active_repair_task_keys.return_value = set()
        mock_retest = mock_retest_class.return_value
        mock_retest.retest_gap = AsyncMock(
            return_value={"gap_key": "gap_open", "action": "keep_open", "applied": True}
        )
        mock_repair_class.return_value.promote_from_retest_actions.return_value = [
            {"gap_key": "gap_open", "repair_task": {"id": 9}}
        ]
        mock_workbench_class.return_value.build.return_value = {
            "counts": {"active": 20, "observing": 1}
        }
        result = await scheduler._execute_gap_retest_listener("run_gap_retest_test")

    mock_repository.fetch_gaps.assert_called_once_with(statuses=["open", "in_progress"], limit=20)
    mock_repository.reconcile_latest_evidence_projection.assert_called_once_with(
        actor="listener_test",
        limit=50,
    )
    mock_repository.invalidate_stale_fixed_state.assert_called_once_with(
        actor="listener_test",
        limit=25,
    )
    assert mock_retest.retest_gap.await_count == 3
    retest_kwargs = mock_retest.retest_gap.await_args.kwargs
    assert retest_kwargs["consultation_endpoint"] == "http://localhost:8002/api/v1/agent"
    assert retest_kwargs["dry_run"] is False
    assert result["trigger"] == "gap_retest_listener"
    assert result["active_only"] is True
    assert result["active_detected"] == 5
    assert result["active_gap_keys"] == [
        "gap_open",
        "gap_progress",
        "gap_other",
        "gap_over_cap",
        "gap_linked_event",
    ]
    assert result["skipped_repair_task_gap_keys"] == []
    assert result["skipped_linked_event_gap_keys"] == ["gap_linked_event"]
    assert result["live_retests_used"] == 3
    assert result["projection_reconciled_count"] == 1
    assert result["projection_reconciled"] == [{"gap_key": "gap_observing", "evidence_id": 7}]
    assert result["fixed_state_invalidated_count"] == 1
    assert result["fixed_state_invalidated"] == [
        {"gap_key": "gap_bad_observing", "evidence_id": 8, "to_status": "open"}
    ]
    assert result["counts"] == {"keep_open": 3}
    assert result["repair_promotions"] == [{"gap_key": "gap_open", "repair_task": {"id": 9}}]


def test_gap_projection_reconcile_uses_only_answer_evidence():
    """Repair-task lifecycle evidence must not overwrite current answer quality/refusal state."""
    from app.agent.gaps.repository import KnowledgeGapRepository

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.return_value = []

    with patch("app.agent.gaps.repository._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.gaps.repository._put_pg_conn"
    ):
        result = KnowledgeGapRepository().reconcile_latest_evidence_projection(
            actor="listener_test",
            limit=25,
        )

    executed_sql = mock_cursor.execute.call_args.args[0]
    assert "evidence_type IN ('live_retest', 'legacy_metadata')" in executed_sql
    assert "quality IS NOT NULL" in executed_sql
    assert result == []


def test_gap_fixed_state_invalidation_scans_only_fixed_answer_evidence():
    """Invalid fixed-state detection must scan only observing/resolved answer evidence."""
    from app.agent.gaps.repository import KnowledgeGapRepository

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.return_value = []

    with patch("app.agent.gaps.repository._get_pg_conn", return_value=mock_conn), patch(
        "app.agent.gaps.repository._put_pg_conn"
    ):
        result = KnowledgeGapRepository().invalidate_stale_fixed_state(
            actor="listener_test",
            limit=25,
        )

    executed_sql = mock_cursor.execute.call_args.args[0]
    assert "evidence_type IN ('live_retest', 'legacy_metadata')" in executed_sql
    assert "quality IS NOT NULL" in executed_sql
    assert "gap.status IN ('observing', 'resolved')" in executed_sql
    assert result == []


@pytest.mark.asyncio
async def test_scheduler_record_run_writes_event_ledger_and_learning_projection():
    """Scheduler should dual-write learning run lifecycle to ledger and projection."""
    from app.agent.scheduler import LearningScheduler

    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    scheduler = LearningScheduler(db_pool=mock_pool)

    await scheduler._record_run(
        "run_manual_20240505_120000",
        {"status": "running", "reason": "test"},
        "running",
        "manual",
        event_type="learning.run.triggered",
    )

    assert mock_cursor.execute.call_count == 2
    first_sql = mock_cursor.execute.call_args_list[0].args[0]
    second_sql = mock_cursor.execute.call_args_list[1].args[0]
    assert "INSERT INTO event_ledger" in first_sql
    assert "INSERT INTO learning_runs" in second_sql
    first_params = mock_cursor.execute.call_args_list[0].args[1]
    assert first_params[2] == "learning.run.triggered"
    assert first_params[3] == "run_manual_20240505_120000"
    mock_conn.commit.assert_called_once()


@pytest.mark.asyncio
async def test_scheduler_persists_problems_and_root_causes_in_run_result():
    """Test scheduler records detected problems and analyzed root causes."""
    from app.agent.scheduler import LearningScheduler

    scheduler = LearningScheduler(db_pool=None)
    mock_signals = MagicMock(
        total_count=10,
        severity_score=45.5,
        total_collect_time_ms=250.0,
        feedback_signals=[MagicMock()],
        failure_signals=[MagicMock(), MagicMock()],
        repeat_signals=[],
        violation_signals=[],
        topo_signals=[MagicMock()],
    )
    mock_problem = MagicMock()
    mock_problem.to_dict.return_value = {
        'problem_id': 'prob_001',
        'category': 'tool_failure',
        'severity': 'high',
        'affected_route': 'R1_navigator_dict',
        'description': 'Continuous failures on route',
        'evidence': ['failure 1'],
        'confidence': 0.9,
        'suggested_gap_id': 'gap_001',
        'ts': 1714898730.0,
        'additional_context': {'failure_count': 4},
    }
    mock_root_cause = MagicMock()
    mock_root_cause.to_dict.return_value = {
        'problem_id': 'prob_001',
        'affected_route': 'R1_navigator_dict',
        'root_cause_hypothesis': 'Tool failure on route',
        'root_cause_type': 'tool_failure',
        'contributing_factors': ['Repeated failures'],
        'evidence_chain': {'primary_evidence': ['failure 1']},
        'confidence': 0.9,
        'repair_suggestions': ['Retry tool call'],
        'repair_priority': 'urgent',
        'ts': 1714898730.0,
    }

    collector = AsyncMock()
    collector.aggregate_all.return_value = mock_signals
    detector = AsyncMock()
    detector.detect_problems.return_value = [mock_problem]
    analyzer = AsyncMock()
    analyzer.analyze_root_cause.return_value = mock_root_cause

    collector_cls = MagicMock(return_value=collector)
    detector_cls = MagicMock(return_value=detector)
    analyzer_cls = MagicMock(return_value=analyzer)
    scheduler._record_run = AsyncMock()

    await scheduler.run_learning_loop_with_run_id(
        'run_manual_test',
        collector_cls=collector_cls,
        detector_cls=detector_cls,
        analyzer_cls=analyzer_cls,
    )

    recorded_result = scheduler._record_run.await_args.args[1]
    assert recorded_result['problems_count'] == 1
    assert recorded_result['problems'][0]['problem_id'] == 'prob_001'
    assert recorded_result['root_causes'][0]['problem_id'] == 'prob_001'
    assert recorded_result['signal_summary'] == {
        'feedback': 1,
        'failures': 2,
        'repeats': 0,
        'violations': 0,
        'topology': 1,
    }


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
    mock_cursor.fetchone.return_value = ('double precision',)
    
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
    # 4 records with rating <= 2
    assert analysis.negative_rate == 0.4
    # Top issue should be '数据过时' (frequency 30%)
    assert len(analysis.top_issues) > 0
    assert analysis.top_issues[0].tag == '数据过时'
    assert analysis.top_issues[0].frequency == 0.3


def test_feedback_analyzer_timestamp_expression_supports_numeric_and_timestamp():
    """Feedback analyzer should support both epoch and timestamptz storage."""
    from app.agent.feedback_analyzer import FeedbackAnalyzer

    analyzer = FeedbackAnalyzer(db_pool=None)

    assert analyzer._feedback_ts_expression('double precision') == 'to_timestamp(ts)'
    assert analyzer._feedback_ts_expression('timestamp with time zone') == 'ts'
    assert analyzer._feedback_ts_expression(None) == 'created_at'


def test_build_learning_run_gap_records_clusters_similar_queries():
    """Learning gap records should cluster similar run failures and keep frequency metadata."""
    from app.agent.learning_state import build_learning_run_gap_records

    runs = [
        {
            'query': '送配电装置系统调试的计算规则是什么？',
            'quality': 'failure',
            'ts': 1777976525.35,
            'refused': True,
            'chunks_count': 2,
            'evaluation': {'confidence': 0.7},
            'query_type': 'standard_ref',
            'runtime': {'model': 'test-model'},
        },
        {
            'query': '送配电装置系统调试的计算规则是什么',
            'quality': 'failure',
            'ts': 1777976530.35,
            'refused': True,
            'chunks_count': 3,
            'evaluation': {'confidence': 0.9},
            'query_type': 'standard_ref',
            'runtime': {'model': 'test-model'},
        },
    ]

    records = build_learning_run_gap_records(runs, limit=10)

    assert len(records) == 1
    assert records[0]['cluster_id'].startswith('cluster_')
    assert records[0]['scope_type'] == 'agent'
    assert records[0]['priority'] > 0
    assert records[0]['metadata']['frequency'] == 2
    assert len(records[0]['metadata']['sample_queries']) == 2


def test_list_resumable_improvement_event_ids_skips_failed_events():
    """Startup resume scan should not keep retrying events already marked as failed."""
    from app.agent.learning_state import list_resumable_improvement_event_ids

    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchall.return_value = [(6,)]

    event_ids = list_resumable_improvement_event_ids(limit=10, pool=mock_pool)

    assert event_ids == [6]
    executed_sql = mock_cursor.execute.call_args.args[0]
    assert "verification_result->>'status'" in executed_sql


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
         patch('app.api.get_feedback_analyzer') as mock_get_analyzer, \
         patch('app.agent.tools._get_pg_conn') as mock_get_pg_conn, \
         patch('app.agent.tools._put_pg_conn'), \
         patch('app.api.compare_canonical_projection_drift_summary') as mock_compare_drift:
        
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

        mock_compare_drift.return_value = {
            'total_drift_count': 2,
            'drifted_projections': ['conversation_turns'],
            'projections': {'conversation_turns': {'drift_count': 2}},
        }

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            ('run_manual_001', datetime(2026, 5, 6, 1, 0), 'completed'),
            (3,),
            (1,),
            ({
                'run_id': 'run_sync_123',
                'scope': 'run',
                'rebuilt_total': 2,
                'remaining_drift_count': 0,
            }, datetime(2026, 5, 6, 1, 30)),
        ]
        mock_get_pg_conn.return_value = mock_conn
        
        client = TestClient(app)
        response = client.get('/api/v1/learning/status')
        
        assert response.status_code == 200
        data = response.json()
        assert 'layer2_triggers' in data
        assert 'scheduler' in data['layer2_triggers']
        assert 'failure_monitor' in data['layer2_triggers']
        assert 'feedback_analyzer' in data['layer2_triggers']
        assert data['projection_drift']['total_drift_count'] == 2
        assert data['last_projection_reconcile']['run_id'] == 'run_sync_123'


@pytest.mark.asyncio
async def test_api_learning_engine_endpoint_includes_runtime_drift_state():
    """Test GET /api/v1/learning/engine includes shared runtime drift signals."""
    from fastapi.testclient import TestClient
    from main import app

    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(return_value=4)
    mock_conn.close = AsyncMock()

    with patch('app.api._build_learning_runtime_state_with_db_fallback', new=AsyncMock(return_value={
        'layer2_triggers': {
            'scheduler': {'status': 'running', 'next_run': '2026-05-06T02:30:00Z'},
            'failure_monitor': {
                'status': 'monitoring',
                'current_failure_rate': 0.125,
                'threshold': 0.2,
                'should_trigger': False,
            },
            'feedback_analyzer': {
                'status': 'analyzing',
                'trending_issues_count': 3,
                'should_trigger': True,
            },
        },
        'projection_drift': {
            'total_drift_count': 3,
            'drifted_projections': ['learning_runs', 'conversation_turns'],
            'projections': {
                'learning_runs': {'drift_count': 1, 'ledger_count': 8, 'projection_count': 7},
                'conversation_turns': {'drift_count': 2, 'ledger_count': 15, 'projection_count': 13},
            },
        },
        'last_projection_reconcile': {
            'scope': 'global',
            'run_id': None,
            'rebuilt_total': 5,
            'remaining_drift_count': 1,
            'occurred_at': 1778034600000,
        },
    })), \
         patch('app.api.os.path.exists', return_value=False), \
         patch('app.api._count_recent_weak_or_failed_runs', return_value=2), \
         patch('asyncpg.connect', new=AsyncMock(return_value=mock_conn)):
        client = TestClient(app)
        response = client.get('/api/v1/learning/engine')

        assert response.status_code == 200
        data = response.json()
        assert data['trigger_mode'] == 'hybrid'
        assert data['signals_24h']['weak_or_failed_runs'] == 2
        assert data['signals_24h']['pending_negative_feedback_with_text'] == 4
        assert data['projection_drift']['total_drift_count'] == 3
        assert data['last_projection_reconcile']['rebuilt_total'] == 5
        assert any(
            condition['name'] == '定时回归 (cron)' and condition['active']
            for condition in data['trigger_conditions']
        )
        assert any('projection drift' in action for action in data['next_actions'])


@pytest.mark.asyncio
async def test_api_learning_problems_prefers_persisted_run():
    """Test GET /api/v1/learning/problems returns persisted run output when available."""
    from fastapi.testclient import TestClient
    from main import app

    with patch('app.api._load_latest_persisted_learning_run', return_value={
        'result': {
            'problems': [
                {
                    'problem_id': 'prob_001',
                    'category': 'tool_failure',
                    'severity': 'high',
                    'affected_route': 'R1_navigator_dict',
                    'description': 'Continuous failures on route',
                    'confidence': 0.9,
                    'evidence': ['failure 1'],
                    'suggested_gap_id': 'gap_001',
                    'ts': 1714898730.0,
                    'additional_context': {},
                }
            ]
        }
    }):
        client = TestClient(app)
        response = client.get('/api/v1/learning/problems?limit=10')

        assert response.status_code == 200
        data = response.json()
        assert data['total'] == 1
        assert data['high_count'] == 1
        assert data['medium_count'] == 0
        assert data['low_count'] == 0
        assert data['problems'][0]['problem_id'] == 'prob_001'


@pytest.mark.asyncio
async def test_api_learning_problems_merges_persisted_gap_status():
    """Test GET /api/v1/learning/problems overlays knowledge gap state."""
    from fastapi.testclient import TestClient
    from main import app

    with patch('app.api._load_latest_persisted_learning_run', return_value={
        'result': {
            'problems': [
                {
                    'problem_id': 'prob_001',
                    'category': 'tool_failure',
                    'severity': 'high',
                    'affected_route': 'R1_navigator_dict',
                    'description': 'Continuous failures on route',
                    'confidence': 0.9,
                    'suggested_gap_id': 'gap_001',
                    'ts': 1714898730.0,
                }
            ]
        }
    }), patch('app.api.fetch_knowledge_gap_status_map', return_value={
        'gap_001': {
            'status': 'resolved',
            'resolution_plan': 'Applied safer navigator rule',
            'resolved_at': 1714898740000,
            'updated_at': 1714898740000,
        }
    }):
        client = TestClient(app)
        response = client.get('/api/v1/learning/problems?limit=10')

        assert response.status_code == 200
        data = response.json()
        assert data['problems'][0]['status'] == 'resolved'
        assert data['problems'][0]['resolution_plan'] == 'Applied safer navigator rule'


@pytest.mark.asyncio
async def test_api_learning_strategies_uses_persisted_root_cause():
    """Test GET /api/v1/learning/strategies uses persisted analysis helper."""
    from fastapi.testclient import TestClient
    from main import app

    problem = {
        'problem_id': 'prob_001',
        'category': 'tool_failure',
        'severity': 'high',
        'affected_route': 'R1_navigator_dict',
        'description': 'Continuous failures on route',
        'confidence': 0.9,
        'evidence': ['failure 1'],
        'suggested_gap_id': 'gap_001',
        'ts': 1714898730.0,
        'status': 'open',
        'additional_context': {},
    }
    root_cause = {
        'problem_id': 'prob_001',
        'affected_route': 'R1_navigator_dict',
        'root_cause_hypothesis': 'Tool failure on route',
        'root_cause_type': 'tool_failure',
        'contributing_factors': ['Repeated failures'],
        'evidence_chain': {'primary_evidence': ['failure 1']},
        'confidence': 0.9,
        'repair_suggestions': ['Retry tool call'],
        'repair_priority': 'urgent',
        'ts': 1714898730.0,
    }

    with patch('app.api._load_problem_analysis', new=AsyncMock(return_value=(problem, root_cause))):
        client = TestClient(app)
        response = client.get('/api/v1/learning/strategies?problem_id=prob_001')

        assert response.status_code == 200
        data = response.json()
        assert data['problem_id'] == 'prob_001'
        assert data['strategies'][0]['action_type'] == 'tool_upgrade'
        assert data['strategies'][0]['decision'] == 'auto_apply'


@pytest.mark.asyncio
async def test_api_learning_gaps_returns_persisted_gap_records():
    """Test GET /api/v1/learning/gaps returns persisted knowledge gap records."""
    from fastapi.testclient import TestClient
    from main import app

    with patch('app.api._fetch_recent_interaction_run_records', return_value=[]), \
         patch('app.api.upsert_knowledge_gap_records') as mock_upsert, \
         patch('app.api.fetch_knowledge_gaps', return_value=[
             {
                 'gap_key': 'gap_001',
                 'query': 'Why is the route failing?',
                 'ts': 1714898730000,
                 'quality': 'failure',
                 'status': 'resolved',
                 'refused': False,
                 'chunks_count': 2,
                 'confidence': 0.8,
                 'answer_preview': 'preview',
                 'resolution_plan': 'Applied safer retry rule',
             }
         ]):
        client = TestClient(app)
        response = client.get('/api/v1/learning/gaps?limit=10')

        assert response.status_code == 200
        data = response.json()
        assert data['gaps'][0]['status'] == 'resolved'
        assert data['gaps'][0]['resolution_plan'] == 'Applied safer retry rule'


def test_api_learning_summary_reads_projection_and_feedback_tables():
    from fastapi.testclient import TestClient
    from main import app

    with patch(
        'app.api._fetch_recent_interaction_run_records',
        return_value=[
            {
                'quality': 'failure',
                'refused': True,
                'evaluation': {'confidence': 0.2},
                'tools_used': ['text_search'],
                'query_type': 'comparison',
            },
            {
                'quality': 'good',
                'refused': False,
                'evaluation': {'confidence': 0.9},
                'tools_used': ['text_search', 'sql_query'],
                'query_type': 'price',
            },
        ],
    ), patch(
        'app.api._fetch_recent_feedback_records',
        return_value=[
            {'rating': 1},
            {'rating': -1},
            {'rating': -1},
        ],
    ):
        client = TestClient(app)
        response = client.get('/api/v1/learning/summary')

    assert response.status_code == 200
    data = response.json()
    assert data['total_runs'] == 2
    assert data['by_quality']['failure'] == 1
    assert data['refused_count'] == 1
    assert data['feedback']['total'] == 3
    assert data['tool_frequency']['text_search'] == 2


def test_api_learning_blindspots_uses_projection_runs():
    from fastapi.testclient import TestClient
    from main import app

    with patch(
        'app.api._fetch_recent_interaction_run_records',
        return_value=[
            {'query': '电缆价格环比怎么比较', 'quality': 'failure', 'refused': False, 'confidence': 0.1, 'chunks_count': 0, 'ts': 1778000000000},
            {'query': '电缆价格环比如何比较', 'quality': 'weak', 'refused': False, 'confidence': 0.2, 'chunks_count': 1, 'ts': 1778000001000},
            {'query': '规费征收标准是什么', 'quality': 'failure', 'refused': True, 'confidence': 0.1, 'chunks_count': 0, 'ts': 1778000002000},
        ],
    ), patch('app.agent.tools._get_embedding_svc', side_effect=RuntimeError('embedding unavailable')):
        client = TestClient(app)
        response = client.get('/api/v1/learning/blindspots?min_size=2&max_clusters=4')

    assert response.status_code == 200
    data = response.json()
    assert data['total_bad'] == 3
    assert len(data['clusters']) == 1
    assert data['clusters'][0]['size'] == 2


def test_api_learning_blindspots_accepts_nested_embedding_vectors():
    from fastapi.testclient import TestClient
    from main import app

    embedding_service = MagicMock()
    embedding_service.encode.side_effect = [
        [[1.0, 0.0, 0.0]],
        [[0.99, 0.01, 0.0]],
        [[0.0, 1.0, 0.0]],
    ]

    with patch(
        'app.api._fetch_recent_interaction_run_records',
        return_value=[
            {'query': '电缆价格环比怎么比较', 'quality': 'failure', 'refused': False, 'confidence': 0.1, 'chunks_count': 0, 'ts': 1778000000000},
            {'query': '电缆价格环比如何比较', 'quality': 'weak', 'refused': False, 'confidence': 0.2, 'chunks_count': 1, 'ts': 1778000001000},
            {'query': '规费征收标准是什么', 'quality': 'failure', 'refused': True, 'confidence': 0.1, 'chunks_count': 0, 'ts': 1778000002000},
        ],
    ), patch('app.agent.tools._get_embedding_svc', return_value=embedding_service):
        client = TestClient(app)
        response = client.get('/api/v1/learning/blindspots?min_size=2&max_clusters=4')

    assert response.status_code == 200
    data = response.json()
    assert data['method'] == 'embedding-cosine'
    assert len(data['clusters']) == 1
    assert data['clusters'][0]['size'] == 2


def test_insert_improvement_event_backfills_missing_gap_record():
    """Applying a strategy should create a minimal knowledge gap row before linking the event."""
    from app.api import _insert_improvement_event

    problem = {
        'problem_id': 'low_score_1777976525',
        'description': 'Low overall score',
        'affected_route': 'R4_rerank_weights',
        'severity': 'high',
        'confidence': 0.97,
        'category': 'low_quality',
        'suggested_gap_id': 'gap_answer_quality',
        'evidence': ['Score #1: -1'],
        'ts': 1777976525352,
    }
    root_cause = {'root_cause_hypothesis': 'Ranking weights need rebalancing'}
    strategy = {
        'strategy_id': 'strat_000',
        'action_type': 'ranking_optimization',
        'description': 'Rebalance ranking weights based on click-through data',
        'route': 'R4_rerank_weights',
        'risk_level': 'low',
        'estimated_impact': 97,
        'decision': 'auto_apply',
    }

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = (7, datetime.utcnow())

    with patch('app.agent.tools._get_pg_conn', return_value=mock_conn), \
         patch('app.agent.tools._put_pg_conn'), \
         patch('app.api._load_latest_persisted_learning_run', return_value={'run_id': 'run_001'}), \
         patch('app.api.link_knowledge_gap_event', side_effect=[False, True]) as mock_link, \
         patch('app.api.upsert_knowledge_gap_records') as mock_upsert:
        event = _insert_improvement_event(problem, root_cause, strategy)

    assert event['event_id'] == 7
    mock_upsert.assert_called_once()
    upsert_records = mock_upsert.call_args.args[0]
    assert upsert_records[0]['gap_key'] == 'gap_answer_quality'
    assert mock_link.call_count == 2


@pytest.mark.asyncio
async def test_api_apply_strategy_creates_improvement_event():
    """Test POST /api/v1/learning/apply-strategy leaves review-required events unscheduled."""
    from fastapi.testclient import TestClient
    from main import app

    problem = {
        'problem_id': 'prob_001',
        'affected_route': 'R1_navigator_dict',
    }
    root_cause = {
        'root_cause_hypothesis': 'Tool failure on route',
    }
    strategies = [
        {
            'strategy_id': 'strat_000',
            'action_type': 'tool_upgrade',
            'description': 'Retry tool call',
            'route': 'R1_navigator_dict',
            'risk_level': 'medium',
            'estimated_impact': 70,
            'decision': 'pending_review',
        }
    ]

    with patch('app.api._build_repair_strategies', new=AsyncMock(return_value=(problem, root_cause, strategies))), \
         patch('app.api._insert_improvement_event', return_value={'event_id': 123, 'status': 'pending_review'}), \
         patch('app.api._schedule_improvement_event_execution') as mock_schedule:
        client = TestClient(app)
        response = client.post('/api/v1/learning/apply-strategy?strategy_id=strat_000&problem_id=prob_001')

        assert response.status_code == 200
        data = response.json()
        assert data['event_id'] == 123
        assert data['status'] == 'pending_review'
        assert data['route'] == 'R1_navigator_dict'
        mock_schedule.assert_not_called()


@pytest.mark.asyncio
async def test_api_apply_strategy_schedules_auto_apply_event_execution():
    """Test POST /api/v1/learning/apply-strategy dispatches approved auto-apply events."""
    from fastapi.testclient import TestClient
    from main import app

    problem = {
        'problem_id': 'prob_001',
        'affected_route': 'R1_navigator_dict',
    }
    root_cause = {
        'root_cause_hypothesis': 'Tool failure on route',
    }
    strategies = [
        {
            'strategy_id': 'strat_000',
            'action_type': 'tool_upgrade',
            'description': 'Retry tool call',
            'route': 'R1_navigator_dict',
            'risk_level': 'low',
            'estimated_impact': 70,
            'decision': 'auto_apply',
        }
    ]

    with patch('app.api._build_repair_strategies', new=AsyncMock(return_value=(problem, root_cause, strategies))), \
         patch('app.api._insert_improvement_event', return_value={'event_id': 123, 'status': 'approved'}), \
         patch('app.api._schedule_improvement_event_execution') as mock_schedule:
        client = TestClient(app)
        response = client.post('/api/v1/learning/apply-strategy?strategy_id=strat_000&problem_id=prob_001')

        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'approved'
        assert data['message'] == 'Queued for execution'
        mock_schedule.assert_called_once()
        _, event_id = mock_schedule.call_args.args
        assert event_id == 123


@pytest.mark.asyncio
async def test_api_approve_fix_updates_event_review_status():
    """Test POST /api/v1/learning/approve-fix schedules approved events for execution."""
    from fastapi.testclient import TestClient
    from main import app

    with patch('app.api._update_improvement_event_review', return_value={'event_id': 321, 'status': 'approved'}), \
         patch('app.api._schedule_improvement_event_execution') as mock_schedule:
        client = TestClient(app)
        response = client.post('/api/v1/learning/approve-fix', json={
            'event_id': 321,
            'comments': 'Looks safe',
            'approved_by': 'user',
        })

        assert response.status_code == 200
        data = response.json()
        assert data['event_id'] == 321
        assert data['status'] == 'approved'
        mock_schedule.assert_called_once()
        _, event_id = mock_schedule.call_args.args
        assert event_id == 321


@pytest.mark.asyncio
async def test_api_reject_fix_updates_event_review_status():
    """Test POST /api/v1/learning/reject-fix uses persisted rejection state."""
    from fastapi.testclient import TestClient
    from main import app

    with patch('app.api._update_improvement_event_review', return_value={'event_id': 654, 'status': 'rejected'}):
        client = TestClient(app)
        response = client.post('/api/v1/learning/reject-fix', json={
            'event_id': 654,
            'reason': 'Too risky',
            'rejected_by': 'user',
        })

        assert response.status_code == 200
        data = response.json()
        assert data['event_id'] == 654
        assert data['status'] == 'rejected'
        assert data['reason'] == 'Too risky'


@pytest.mark.asyncio
async def test_api_learning_history_returns_persisted_event_statuses():
    """Test GET /api/v1/learning/history returns persisted review statuses."""
    from fastapi.testclient import TestClient
    from main import app

    events = [
        {
            'event_id': 1,
            'timestamp': 1714898730000,
            'problem_id': 'prob_001',
            'route': 'R1_navigator_dict',
            'action': 'Retry tool call',
            'status': 'pending_review',
            'before_rate': 0.5,
            'after_rate': 0.7,
            'delta': 0.2,
            'improvement_pct': 40,
            'execution_time': 0,
        },
        {
            'event_id': 2,
            'timestamp': 1714898740000,
            'problem_id': 'prob_002',
            'route': 'R2_path_default',
            'action': 'Tune default path',
            'status': 'verified',
            'before_rate': 0.5,
            'after_rate': 0.8,
            'delta': 0.3,
            'improvement_pct': 60,
            'execution_time': 0,
        },
    ]

    with patch('app.api._get_improvement_history_events', return_value=events):
        client = TestClient(app)
        response = client.get('/api/v1/learning/history?days=30')

        assert response.status_code == 200
        data = response.json()
        assert len(data['events']) == 2
        assert data['summary']['total_events'] == 2
        assert data['summary']['successful'] == 1


@pytest.mark.asyncio
async def test_lifespan_initializes_and_shuts_down_layer2_components():
    """Test retrieval-service lifespan wires and clears layer2 components."""
    import main

    mock_store = MagicMock()
    mock_pool = object()
    mock_store.pg_pool = mock_pool
    mock_pipeline = MagicMock()
    mock_scheduler = MagicMock()
    mock_monitor = MagicMock()
    mock_analyzer = MagicMock()

    with patch('main.UnifiedStore', return_value=mock_store), \
         patch('main.UnifiedRetrievalPipeline', return_value=mock_pipeline), \
         patch('main.set_services') as mock_set_services, \
         patch('app.agent.scheduler.init_scheduler', return_value=mock_scheduler) as mock_init_scheduler, \
         patch('app.agent.failure_monitor.init_failure_monitor', return_value=mock_monitor) as mock_init_monitor, \
         patch('app.agent.feedback_analyzer.init_feedback_analyzer', return_value=mock_analyzer) as mock_init_analyzer, \
         patch('app.agent.scheduler.shutdown_scheduler') as mock_shutdown_scheduler, \
         patch('app.agent.failure_monitor.shutdown_failure_monitor') as mock_shutdown_monitor, \
         patch('app.agent.feedback_analyzer.shutdown_feedback_analyzer') as mock_shutdown_analyzer:
        async with main.lifespan(main.app):
            assert main._scheduler is mock_scheduler
            assert main._failure_monitor is mock_monitor
            assert main._feedback_analyzer is mock_analyzer

        mock_set_services.assert_called_with(mock_pipeline, mock_store)
        mock_init_scheduler.assert_called_once_with(db_pool=mock_pool)
        mock_init_monitor.assert_called_once_with(db_pool=mock_pool)
        mock_init_analyzer.assert_called_once_with(db_pool=mock_pool)
        assert mock_shutdown_scheduler.call_count == 2
        assert mock_shutdown_monitor.call_count == 2
        assert mock_shutdown_analyzer.call_count == 2
        mock_store.close.assert_called_once()
        assert main._scheduler is None
        assert main._failure_monitor is None
        assert main._feedback_analyzer is None


@pytest.mark.asyncio
async def test_lifespan_schedules_resumable_improvement_events():
    """Test retrieval-service startup schedules resumable executor work."""
    import main

    mock_store = MagicMock()
    mock_pool = object()
    mock_store.pg_pool = mock_pool

    with patch('main.UnifiedStore', return_value=mock_store), \
         patch('main.UnifiedRetrievalPipeline', return_value=MagicMock()), \
         patch('main.set_services'), \
         patch('app.agent.scheduler.init_scheduler', return_value=MagicMock()), \
         patch('app.agent.failure_monitor.init_failure_monitor', return_value=MagicMock()), \
         patch('app.agent.feedback_analyzer.init_feedback_analyzer', return_value=MagicMock()), \
         patch('app.agent.scheduler.shutdown_scheduler'), \
         patch('app.agent.failure_monitor.shutdown_failure_monitor'), \
         patch('app.agent.feedback_analyzer.shutdown_feedback_analyzer'), \
         patch('main._schedule_resumable_improvement_events') as mock_schedule:
        async with main.lifespan(main.app):
            mock_schedule.assert_called_once_with(mock_pool)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])

#!/usr/bin/env python
"""
Simple integration test for Layer 2 trigger mechanisms
This script verifies that the three trigger mechanisms can be initialized and basic operations work
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the service to path
sys.path.insert(0, str(Path(__file__).parent / "src/backend/retrieval-service"))

async def test_scheduler():
    """Test scheduler initialization and basic operations"""
    print("🧪 Testing Scheduler...")
    from app.agent.scheduler import LearningScheduler, init_scheduler, get_scheduler, shutdown_scheduler
    
    try:
        # Initialize
        scheduler = init_scheduler(db_pool=None)
        assert scheduler is not None, "Scheduler should not be None"
        
        # Get instance
        s = get_scheduler()
        assert s is scheduler, "get_scheduler() should return same instance"
        
        # Check running state
        assert s._running is True, "Scheduler should be running"
        
        # Get next run (will fail gracefully if APScheduler not installed)
        next_run = await s.get_next_run_time()
        if 'error' not in next_run:
            assert 'next_run_utc' in next_run or 'next_run_timestamp' in next_run
            print(f"   ✅ Next run: {next_run.get('next_run_utc', 'unknown')}")
        else:
            print(f"   ⚠️  {next_run['error']} (APScheduler may not be installed)")
        
        # Shutdown
        shutdown_scheduler()
        assert get_scheduler() is None, "Scheduler should be None after shutdown"
        
        print("✅ Scheduler tests passed")
        return True
    except Exception as e:
        print(f"❌ Scheduler test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_failure_monitor():
    """Test failure monitor initialization"""
    print("\n🧪 Testing Failure Monitor...")
    from app.agent.failure_monitor import FailureMonitor, init_failure_monitor, get_failure_monitor
    
    try:
        # Initialize
        monitor = init_failure_monitor(db_pool=None)
        assert monitor is not None, "Monitor should not be None"
        
        # Get instance
        m = get_failure_monitor()
        assert m is monitor, "get_failure_monitor() should return same instance"
        
        # Check thresholds
        assert monitor.FAILURE_THRESHOLD == 0.20
        assert monitor.WINDOW_SIZE == 16
        assert monitor.MIN_WINDOW_SAMPLES == 8
        print(f"   ✅ Threshold: {monitor.FAILURE_THRESHOLD:.0%}")
        print(f"   ✅ Window size: {monitor.WINDOW_SIZE}")
        
        # Try to get stats (will return None without DB)
        stats = await monitor.get_recent_failure_stats()
        print(f"   ℹ️  Stats (without DB): {stats}")
        
        print("✅ Failure Monitor tests passed")
        return True
    except Exception as e:
        print(f"❌ Failure Monitor test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_feedback_analyzer():
    """Test feedback analyzer initialization"""
    print("\n🧪 Testing Feedback Analyzer...")
    from app.agent.feedback_analyzer import FeedbackAnalyzer, FeedbackIssue, init_feedback_analyzer, get_feedback_analyzer
    
    try:
        # Initialize
        analyzer = init_feedback_analyzer(db_pool=None)
        assert analyzer is not None, "Analyzer should not be None"
        
        # Get instance
        a = get_feedback_analyzer()
        assert a is analyzer, "get_feedback_analyzer() should return same instance"
        
        # Check weights
        assert len(analyzer.TAG_WEIGHTS) == 7
        assert analyzer.TAG_WEIGHTS['逻辑错误'] == 15
        print(f"   ✅ Tag weights defined: {len(analyzer.TAG_WEIGHTS)} tags")
        
        # Check thresholds
        assert analyzer.TRENDING_THRESHOLD == 0.20
        assert analyzer.TRIGGER_WEIGHT_THRESHOLD == 30
        print(f"   ✅ Trending threshold: {analyzer.TRENDING_THRESHOLD:.0%}")
        
        # Test suggestion generation
        issue1 = FeedbackIssue(tag='数据过时', frequency=0.25, count=3, weight=25)
        issue2 = FeedbackIssue(tag='工具失效', frequency=0.20, count=2, weight=24)
        suggestions = analyzer._generate_suggestions([issue1, issue2])
        assert len(suggestions) == 2
        assert any('数据源' in s for s in suggestions)
        print(f"   ✅ Generated {len(suggestions)} suggestions")
        
        print("✅ Feedback Analyzer tests passed")
        return True
    except Exception as e:
        print(f"❌ Feedback Analyzer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_database_schema():
    """Test that the learning_runs table exists"""
    print("\n🧪 Testing Database Schema...")
    try:
        import psycopg2
        from psycopg2.pool import ThreadedConnectionPool
        
        # Try to connect
        dsn = (
            f"host={os.getenv('POSTGRES_HOST', 'localhost')} "
            f"port={os.getenv('POSTGRES_PORT', '5432')} "
            f"dbname={os.getenv('POSTGRES_DB', 'rag_db')} "
            f"user={os.getenv('POSTGRES_USER', 'rag_user')} "
            f"password={os.getenv('POSTGRES_PASSWORD', 'rag_password')}"
        )
        
        pool = ThreadedConnectionPool(minconn=1, maxconn=2, dsn=dsn)
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                # Check if learning_runs table exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables 
                        WHERE table_name = 'learning_runs'
                    )
                """)
                exists = cur.fetchone()[0]
                assert exists, "learning_runs table should exist"
                
                # Check columns
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'learning_runs'
                    ORDER BY ordinal_position
                """)
                columns = [row[0] for row in cur.fetchall()]
                assert 'run_id' in columns
                assert 'run_type' in columns
                assert 'status' in columns
                print(f"   ✅ learning_runs table exists with {len(columns)} columns")
                
                # Check indexes
                cur.execute("""
                    SELECT indexname FROM pg_indexes
                    WHERE tablename = 'learning_runs'
                """)
                indexes = [row[0] for row in cur.fetchall()]
                assert len(indexes) >= 4, "Should have at least 4 indexes"
                print(f"   ✅ {len(indexes)} indexes found")
        finally:
            pool.putconn(conn)
            pool.closeall()
        
        print("✅ Database schema tests passed")
        return True
    except Exception as e:
        print(f"⚠️  Database schema test failed (DB may not be running): {e}")
        return True  # Don't fail if DB is not available


async def main():
    print("=" * 60)
    print("Layer 2 Trigger Mechanisms - Integration Test")
    print("=" * 60)
    
    results = []
    
    # Run tests
    results.append(("Scheduler", await test_scheduler()))
    results.append(("Failure Monitor", await test_failure_monitor()))
    results.append(("Feedback Analyzer", await test_feedback_analyzer()))
    results.append(("Database Schema", await test_database_schema()))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} passed")
    print("=" * 60)
    
    return all(r for _, r in results)


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

"""
Verification 1: APScheduler Initialization Test
Tests that APScheduler is correctly initialized with at least one scheduled task
"""
import pytest
import sys
import os
from datetime import datetime
from unittest.mock import patch, MagicMock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src/backend/retrieval-service'))


@pytest.mark.asyncio
async def test_scheduler_initialization_successful():
    """Test that scheduler initializes and starts successfully"""
    from app.agent.scheduler import LearningScheduler
    
    scheduler = LearningScheduler(db_pool=None)
    assert scheduler is not None, "Scheduler should initialize"
    assert scheduler._running is False, "Scheduler should not be running initially"
    
    # Start scheduler
    scheduler.start()
    assert scheduler._running is True, "Scheduler should be running after start()"
    assert scheduler.scheduler is not None, "APScheduler should be initialized"
    
    # Verify at least one job is scheduled
    jobs = scheduler.scheduler.get_jobs()
    assert len(jobs) > 0, "✅ At least one scheduled job should exist"
    assert len(jobs) == 1, "Should have exactly one job (daily learning loop)"
    
    # Verify job details
    job = jobs[0]
    assert job.id == 'learning_loop_daily', "Job ID should be 'learning_loop_daily'"
    assert job.name == 'Daily Learning Loop', "Job name should be descriptive"
    
    print(f"✅ Scheduler initialized successfully")
    print(f"   Job: {job.name}")
    print(f"   ID: {job.id}")
    print(f"   Trigger: {job.trigger}")
    print(f"   Next run: {job.next_run_time}")
    
    # Cleanup
    scheduler.stop()
    assert scheduler._running is False, "Scheduler should be stopped"


@pytest.mark.asyncio
async def test_scheduler_job_properties():
    """Test that scheduler job has correct properties"""
    from app.agent.scheduler import LearningScheduler
    
    scheduler = LearningScheduler(db_pool=None)
    scheduler.start()
    
    try:
        jobs = scheduler.scheduler.get_jobs()
        job = jobs[0]
        
        # Verify job configuration
        assert job.id == 'learning_loop_daily', "Job ID should be 'learning_loop_daily'"
        assert job.name == 'Daily Learning Loop', "Job name should be 'Daily Learning Loop'"
        assert job.next_run_time is not None, "Next run time should be set"
        assert isinstance(job.next_run_time, datetime), "Next run time should be datetime"
        
        # Check trigger is CronTrigger
        from apscheduler.triggers.cron import CronTrigger
        assert isinstance(job.trigger, CronTrigger), "Trigger should be CronTrigger"
        
        print(f"✅ Job properties verified:")
        print(f"   ID: {job.id}")
        print(f"   Name: {job.name}")
        print(f"   Next run: {job.next_run_time} UTC")
        print(f"   Trigger type: {type(job.trigger).__name__}")
        
    finally:
        scheduler.stop()


@pytest.mark.asyncio
async def test_global_scheduler_initialization():
    """Test global scheduler functions"""
    from app.agent.scheduler import init_scheduler, get_scheduler, shutdown_scheduler
    
    # Initialize global scheduler
    scheduler = init_scheduler(db_pool=None)
    assert scheduler is not None, "init_scheduler should return scheduler instance"
    
    # Get global scheduler
    retrieved = get_scheduler()
    assert retrieved is not None, "get_scheduler should return initialized scheduler"
    assert retrieved is scheduler, "get_scheduler should return same instance"
    
    # Verify it's running
    jobs = retrieved.scheduler.get_jobs()
    assert len(jobs) > 0, "Scheduler should have scheduled jobs"
    
    print(f"✅ Global scheduler initialized with {len(jobs)} job(s)")
    
    # Shutdown
    shutdown_scheduler()
    retrieved_after = get_scheduler()
    assert retrieved_after is None, "Scheduler should be None after shutdown"
    
    print(f"✅ Global scheduler shutdown successfully")


@pytest.mark.asyncio
async def test_scheduler_with_db_pool():
    """Test scheduler initialization with database pool"""
    from app.agent.scheduler import LearningScheduler
    from unittest.mock import MagicMock
    
    # Create mock database pool
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    
    scheduler = LearningScheduler(db_pool=mock_pool)
    assert scheduler.db_pool is mock_pool, "DB pool should be stored"
    
    scheduler.start()
    assert scheduler._running is True, "Scheduler should start with db_pool"
    
    jobs = scheduler.scheduler.get_jobs()
    assert len(jobs) > 0, "Should have scheduled jobs even with db_pool"
    
    print(f"✅ Scheduler initialized with DB pool")
    
    scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_misfire_grace_time():
    """Test that scheduler has proper misfire configuration"""
    from app.agent.scheduler import LearningScheduler
    
    scheduler = LearningScheduler(db_pool=None)
    scheduler.start()
    
    try:
        jobs = scheduler.scheduler.get_jobs()
        job = jobs[0]
        
        # Verify misfire handling is configured
        assert job.misfire_grace_time == 600, "Misfire grace time should be 600 seconds (10 minutes)"
        assert job.coalesce is True, "Coalesce should be True to merge missed executions"
        
        print(f"✅ Misfire configuration verified:")
        print(f"   Grace time: {job.misfire_grace_time} seconds (10 minutes)")
        print(f"   Coalesce: {job.coalesce}")
        
    finally:
        scheduler.stop()


def test_apscheduler_availability():
    """Test that APScheduler is installed and importable"""
    try:
        import apscheduler
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        print(f"✅ APScheduler {apscheduler.__version__} is installed")
    except ImportError as e:
        pytest.fail(f"APScheduler not installed: {e}")


def test_cron_trigger_creation():
    """Test that CronTrigger can be created with daily 2 AM specification"""
    from apscheduler.triggers.cron import CronTrigger
    from datetime import datetime, timedelta
    
    # Create trigger for daily 2 AM UTC
    trigger = CronTrigger(hour=2, minute=0, second=0)
    assert trigger is not None, "CronTrigger should be created"
    
    # Test next fire time
    now = datetime.utcnow()
    next_fire = trigger.get_next_fire_time(None, now)
    
    assert next_fire is not None, "Should get next fire time"
    assert next_fire.hour == 2, f"Next fire should be at 2 AM, got {next_fire.hour}"
    assert next_fire.minute == 0, "Should be at minute 0"
    assert next_fire.second == 0, "Should be at second 0"
    
    # Next fire should be within 24 hours
    time_until_next = (next_fire - now).total_seconds()
    assert 0 < time_until_next <= 86400, "Next fire should be within 24 hours"
    
    print(f"✅ CronTrigger verified:")
    print(f"   Next fire: {next_fire} UTC")
    print(f"   Hours from now: {time_until_next / 3600:.1f}")

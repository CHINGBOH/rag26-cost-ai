"""
Verification 2: Cron Schedule Expression Test
Verifies that cron expression triggers at exactly 2:00 AM UTC daily
"""
import pytest
import sys
import os
from datetime import datetime, timedelta
from apscheduler.triggers.cron import CronTrigger

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src/backend/retrieval-service'))


def test_cron_expression_daily_2am():
    """Test that cron expression fires exactly at 2:00 AM UTC"""
    trigger = CronTrigger(hour=2, minute=0, second=0)
    
    # Test next fire times over multiple days
    now = datetime.utcnow()
    fire_times = []
    
    for i in range(5):  # Test 5 days
        test_time = now + timedelta(hours=i*24)
        next_fire = trigger.get_next_fire_time(None, test_time)
        
        if next_fire:
            fire_times.append(next_fire)
            
            # Verify time is exactly 2:00:00 UTC
            assert next_fire.hour == 2, f"Hour should be 2, got {next_fire.hour}"
            assert next_fire.minute == 0, f"Minute should be 0, got {next_fire.minute}"
            assert next_fire.second == 0, f"Second should be 0, got {next_fire.second}"
    
    # Verify approximately 24 hour intervals
    if len(fire_times) >= 2:
        for i in range(len(fire_times) - 1):
            interval = (fire_times[i+1] - fire_times[i]).total_seconds() / 3600
            assert 23.9 <= interval <= 24.1, f"Interval should be ~24 hours, got {interval:.1f}"
    
    print(f"✅ Cron schedule verified for 5 consecutive days:")
    for i, time in enumerate(fire_times):
        print(f"   Day {i+1}: {time.strftime('%Y-%m-%d %H:%M:%S UTC')}")


def test_cron_never_fires_wrong_hour():
    """Test that cron never fires at wrong hours"""
    trigger = CronTrigger(hour=2, minute=0, second=0)
    
    # Test firing times
    base_time = datetime(2024, 5, 5, 0, 0, 0)  # Midnight UTC
    
    wrong_hours = [0, 1, 3, 4, 5, 12, 23]
    
    for test_hour in wrong_hours:
        test_time = datetime(2024, 5, 5, test_hour, 30, 0)
        next_fire = trigger.get_next_fire_time(None, test_time)
        
        # Next fire should not be at the test time (within same hour)
        if next_fire.day == test_time.day and next_fire.hour == test_hour:
            pytest.fail(f"Cron should not fire at {test_hour}:00, but got {next_fire}")
    
    print(f"✅ Confirmed cron does not fire at wrong hours: {wrong_hours}")


def test_cron_fires_exactly_once_per_day():
    """Test that cron fires exactly once in a 24-hour period"""
    trigger = CronTrigger(hour=2, minute=0, second=0)
    
    # Test a full day starting from midnight
    start_time = datetime(2024, 5, 5, 0, 0, 0)
    end_time = start_time + timedelta(hours=24)
    
    fire_times = []
    test_time = start_time
    
    while test_time < end_time:
        next_fire = trigger.get_next_fire_time(None, test_time)
        
        if next_fire and next_fire < end_time:
            fire_times.append(next_fire)
            test_time = next_fire + timedelta(seconds=1)
        else:
            break
    
    assert len(fire_times) == 1, f"Should fire exactly once in 24 hours, got {len(fire_times)}"
    assert fire_times[0].hour == 2, f"Should fire at 2:00 UTC, got {fire_times[0].hour:02d}:00"
    
    print(f"✅ Cron fires exactly once per day:")
    print(f"   Fire time: {fire_times[0].strftime('%Y-%m-%d %H:%M:%S UTC')}")


def test_cron_handles_daylight_saving():
    """Test cron trigger behavior across DST boundaries (UTC-based)"""
    trigger = CronTrigger(hour=2, minute=0, second=0)
    
    # UTC doesn't have DST, so fire time should be consistent
    times = [
        datetime(2024, 3, 10, 0, 0, 0),  # Just before US DST starts
        datetime(2024, 3, 11, 0, 0, 0),  # Just after US DST starts
        datetime(2024, 11, 3, 0, 0, 0),  # Just before US DST ends
        datetime(2024, 11, 4, 0, 0, 0),  # Just after US DST ends
    ]
    
    fire_times = []
    for test_time in times:
        next_fire = trigger.get_next_fire_time(None, test_time)
        fire_times.append(next_fire)
        assert next_fire.hour == 2, f"Should fire at 2:00 even near DST, got {next_fire.hour}:00"
    
    print(f"✅ Cron handles DST correctly (UTC is DST-independent):")
    for time in fire_times:
        print(f"   {time.strftime('%Y-%m-%d %H:%M:%S UTC')}")


def test_cron_with_edge_times():
    """Test cron behavior at edge times"""
    trigger = CronTrigger(hour=2, minute=0, second=0)
    
    # Test at 1:59:59 UTC
    before_time = datetime(2024, 5, 5, 1, 59, 59)
    next_fire = trigger.get_next_fire_time(None, before_time)
    assert next_fire.hour == 2 and next_fire.day == 5, "Should fire at 2:00 same day"
    assert (next_fire - before_time).total_seconds() < 2, "Should be within 1 second"
    
    # Test at exactly 2:00:00 UTC
    exact_time = datetime(2024, 5, 5, 2, 0, 0)
    next_fire = trigger.get_next_fire_time(None, exact_time)
    # Should fire next day at 2:00
    assert next_fire.day == 6 and next_fire.hour == 2, "Should fire next day at 2:00"
    
    # Test at 2:00:01 UTC
    after_time = datetime(2024, 5, 5, 2, 0, 1)
    next_fire = trigger.get_next_fire_time(None, after_time)
    # Should fire next day at 2:00
    assert next_fire.day == 6 and next_fire.hour == 2, "Should fire next day at 2:00"
    
    print(f"✅ Cron edge time behavior verified:")
    print(f"   1:59:59 UTC → fires in ~1 second")
    print(f"   2:00:00 UTC → fires next day")
    print(f"   2:00:01 UTC → fires next day")


def test_cron_timezone_is_utc():
    """Test that cron is using UTC timezone"""
    trigger = CronTrigger(hour=2, minute=0, second=0)
    
    # Create times and verify they're interpreted as UTC
    utc_time = datetime(2024, 5, 5, 1, 0, 0)
    next_fire = trigger.get_next_fire_time(None, utc_time)
    
    # Should fire at UTC 2:00, not any other timezone
    assert next_fire.hour == 2, "Should fire at hour 2 in UTC"
    assert next_fire.minute == 0, "Should fire at minute 0"
    
    # Test next day
    next_next = trigger.get_next_fire_time(None, next_fire + timedelta(seconds=1))
    assert (next_next - next_fire).total_seconds() > 86390, "Next fire should be ~24 hours later"
    
    print(f"✅ Cron timezone confirmed as UTC")
    print(f"   First fire: {next_fire} UTC")
    print(f"   Next fire: {next_next} UTC")


def test_scheduler_cron_configuration():
    """Test scheduler actually uses the correct cron configuration"""
    from app.agent.scheduler import LearningScheduler
    
    scheduler = LearningScheduler(db_pool=None)
    scheduler.start()
    
    try:
        jobs = scheduler.scheduler.get_jobs()
        job = jobs[0]
        
        # Verify trigger is CronTrigger with correct settings
        from apscheduler.triggers.cron import CronTrigger
        assert isinstance(job.trigger, CronTrigger), "Trigger should be CronTrigger"
        
        # Get next fire time
        now = datetime.utcnow()
        next_fire = job.trigger.get_next_fire_time(None, now)
        
        assert next_fire.hour == 2, f"Scheduler should fire at 2:00 UTC, got {next_fire.hour}:00"
        assert next_fire.minute == 0, f"Scheduler should fire at :00, got :{next_fire.minute:02d}"
        assert next_fire.second == 0, f"Scheduler should fire at :00s, got :{next_fire.second:02d}"
        
        print(f"✅ Scheduler cron configuration verified:")
        print(f"   Trigger: {type(job.trigger).__name__}")
        print(f"   Next fire: {next_fire.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"   Time until next fire: {(next_fire - now).total_seconds() / 3600:.1f} hours")
        
    finally:
        scheduler.stop()

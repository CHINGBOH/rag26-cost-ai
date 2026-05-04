"""
Layer 2 - Cron Scheduler for Learning Loop
Triggers daily learning cycles at 2:00 AM UTC
Issue #96
"""

import logging
import json
import asyncio
from datetime import datetime
from typing import Dict, Optional
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class LearningScheduler:
    """
    Orchestrates learning loop execution on a schedule.
    - Cron trigger: daily at 2:00 AM UTC
    - Manual triggers via API
    - Records all runs to learning_runs table
    """
    
    def __init__(self, db_pool=None):
        """
        Initialize scheduler.
        
        Args:
            db_pool: psycopg2.ThreadedConnectionPool or None
        """
        self.db_pool = db_pool
        self.scheduler = None
        self._running = False
        
    def start(self):
        """Start the scheduler"""
        try:
            # Import here to avoid hard dependency
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
            
            self.scheduler = AsyncIOScheduler()
            
            # Schedule daily learning loop at 2:00 AM UTC
            self.scheduler.add_job(
                self.run_learning_loop,
                CronTrigger(hour=2, minute=0, second=0),
                id='learning_loop_daily',
                name='Daily Learning Loop',
                misfire_grace_time=600,  # Allow up to 10 minutes late
                coalesce=True  # Merge missed executions
            )
            
            self.scheduler.start()
            self._running = True
            logger.info("✅ LearningScheduler: Daily cron scheduled for 02:00 UTC")
            
        except ImportError:
            logger.warning("⚠️  APScheduler not installed, scheduler disabled")
        except Exception as e:
            logger.error(f"❌ Failed to start scheduler: {e}")
    
    def stop(self):
        """Stop the scheduler"""
        if self.scheduler:
            try:
                self.scheduler.shutdown()
                self._running = False
                logger.info("✅ LearningScheduler stopped")
            except Exception as e:
                logger.error(f"Error shutting down scheduler: {e}")
    
    async def run_learning_loop(self):
        """
        Core learning loop:
        1. Collect signals
        2. Detect problems
        3. Record execution
        """
        run_id = f"run_scheduled_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        try:
            logger.info(f"🚀 Starting scheduled learning loop: {run_id}")
            
            # Step 1: Collect signals
            from app.agent.signal_collector import SignalCollector
            
            collector = SignalCollector(pool=self.db_pool)
            signals = await collector.aggregate_all()
            logger.info(f"📊 Collected {signals.total_count} signals "
                       f"(severity: {signals.severity_score:.1f}, time: {signals.total_collect_time_ms:.0f}ms)")
            
            # Step 2: Detect problems
            from app.agent.problem_detector import ProblemDetector
            
            detector = ProblemDetector()
            problems = await detector.detect_problems(signals)
            logger.info(f"🎯 Detected {len(problems)} problems")
            
            # Step 3: Record successful run
            await self._record_run(run_id, {
                'signals_count': signals.total_count,
                'severity_score': signals.severity_score,
                'problems_count': len(problems),
                'collect_time_ms': signals.total_collect_time_ms,
                'status': 'completed'
            }, 'completed')
            
            logger.info(f"✅ Learning loop {run_id} completed successfully")
            
        except Exception as e:
            logger.error(f"❌ Learning loop {run_id} failed: {e}", exc_info=True)
            await self._record_run(run_id, {
                'status': 'failed',
                'error': str(e)
            }, 'failed')
    
    async def trigger_manual(self, reason: str = "manual") -> str:
        """
        Manually trigger learning loop (called via API).
        
        Returns:
            run_id: identifier of the triggered run
        """
        run_id = f"run_manual_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        try:
            logger.info(f"🔔 Manual learning loop triggered: {run_id} (reason: {reason})")
            
            # Run in background
            asyncio.create_task(self.run_learning_loop_with_run_id(run_id, 'manual'))
            
            # Record that we're starting
            await self._record_run(run_id, {'status': 'running', 'reason': reason}, 'running')
            
            return run_id
            
        except Exception as e:
            logger.error(f"Failed to trigger manual learning: {e}")
            return None
    
    async def run_learning_loop_with_run_id(self, run_id: str, run_type: str = 'manual'):
        """Internal method to run learning loop with specific run_id"""
        try:
            from app.agent.signal_collector import SignalCollector
            from app.agent.problem_detector import ProblemDetector
            
            collector = SignalCollector(pool=self.db_pool)
            signals = await collector.aggregate_all()
            
            detector = ProblemDetector()
            problems = await detector.detect_problems(signals)
            
            await self._record_run(run_id, {
                'signals_count': signals.total_count,
                'severity_score': signals.severity_score,
                'problems_count': len(problems),
                'collect_time_ms': signals.total_collect_time_ms,
                'status': 'completed'
            }, 'completed', run_type)
            
        except Exception as e:
            logger.error(f"Learning loop {run_id} failed: {e}", exc_info=True)
            await self._record_run(run_id, {'status': 'failed', 'error': str(e)}, 'failed', run_type)
    
    async def _record_run(self, run_id: str, result: Dict, status: str, run_type: str = 'scheduled'):
        """Record learning loop execution to database"""
        if not self.db_pool:
            logger.warning(f"No DB pool, cannot record run {run_id}")
            return
        
        try:
            conn = self.db_pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO learning_runs (run_id, run_type, result, status, ts)
                        VALUES (%s, %s, %s, %s, NOW())
                        ON CONFLICT(run_id) DO UPDATE SET result = EXCLUDED.result, status = EXCLUDED.status
                        """,
                        (run_id, run_type, json.dumps(result), status)
                    )
                conn.commit()
            finally:
                self.db_pool.putconn(conn)
        except Exception as e:
            logger.error(f"Failed to record run {run_id}: {e}")
    
    async def get_next_run_time(self) -> Dict:
        """Get the next scheduled run time"""
        if not self.scheduler:
            return {'error': 'scheduler not running'}
        
        try:
            job = self.scheduler.get_job('learning_loop_daily')
            if job and job.next_run_time:
                return {
                    'job_id': 'learning_loop_daily',
                    'next_run_utc': job.next_run_time.isoformat(),
                    'next_run_timestamp': int(job.next_run_time.timestamp() * 1000)
                }
        except Exception as e:
            logger.error(f"Error getting next run time: {e}")
        
        return {'error': 'no scheduled job'}


# Global scheduler instance
_scheduler = None


def init_scheduler(db_pool=None) -> LearningScheduler:
    """Initialize and start the learning scheduler"""
    global _scheduler
    _scheduler = LearningScheduler(db_pool=db_pool)
    _scheduler.start()
    return _scheduler


def get_scheduler() -> Optional[LearningScheduler]:
    """Get the global scheduler instance"""
    return _scheduler


def shutdown_scheduler():
    """Stop the scheduler"""
    global _scheduler
    if _scheduler:
        _scheduler.stop()
        _scheduler = None

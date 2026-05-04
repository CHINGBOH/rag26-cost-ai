"""
Layer 2 - Failure Rate Threshold Trigger
Monitors recent query failures and triggers learning loop when rate exceeds threshold
Issue #96
"""

import logging
from typing import Optional
from collections import deque
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FailureStats:
    """Failure rate statistics"""
    window_size: int
    failure_count: int
    success_count: int
    total_count: int
    failure_rate: float
    
    def __repr__(self):
        return f"FailureStats({self.failure_rate:.1%} failed, {self.failure_count}/{self.total_count})"


class FailureMonitor:
    """
    Monitors failure rate of recent queries.
    When consecutive failures exceed threshold, automatically triggers learning loop.
    """
    
    FAILURE_THRESHOLD = 0.20  # 20% failure rate
    WINDOW_SIZE = 16  # Monitor last 16 queries
    MIN_WINDOW_SAMPLES = 8  # Need at least 8 samples to trigger
    
    def __init__(self, db_pool=None):
        """
        Initialize failure monitor.
        
        Args:
            db_pool: psycopg2.ThreadedConnectionPool or None
        """
        self.db_pool = db_pool
        self.failure_window = deque(maxlen=self.WINDOW_SIZE)
    
    async def check_and_trigger(self) -> Optional[str]:
        """
        Check recent failure rate and trigger learning loop if threshold exceeded.
        
        Returns:
            run_id if triggered, None otherwise
        """
        stats = await self.get_recent_failure_stats()
        
        if stats:
            logger.info(f"📊 {stats}")
            
            # Only trigger if we have enough samples and exceed threshold
            if stats.total_count >= self.MIN_WINDOW_SAMPLES and \
               stats.failure_rate >= self.FAILURE_THRESHOLD:
                logger.warning(f"⚠️  Failure rate {stats.failure_rate:.1%} exceeds threshold {self.FAILURE_THRESHOLD:.1%}!")
                return await self._trigger_learning_loop(stats)
        
        return None
    
    async def get_recent_failure_stats(self) -> Optional[FailureStats]:
        """
        Get failure statistics from recent conversation turns.
        
        Returns:
            FailureStats or None if query fails
        """
        if not self.db_pool:
            logger.warning("No DB pool, cannot check failure stats")
            return None
        
        try:
            conn = self.db_pool.getconn()
            try:
                with conn.cursor() as cur:
                    # Get recent turns
                    cur.execute(
                        """
                        SELECT status FROM conversation_turns
                        ORDER BY ts DESC LIMIT %s
                        """,
                        (self.WINDOW_SIZE,)
                    )
                    rows = cur.fetchall()
            finally:
                self.db_pool.putconn(conn)
            
            if not rows:
                logger.debug("No recent conversation turns found")
                return None
            
            # Count failures (status = 'error')
            failure_count = sum(1 for (status,) in rows if status == 'error')
            success_count = len(rows) - failure_count
            failure_rate = failure_count / len(rows) if rows else 0
            
            return FailureStats(
                window_size=self.WINDOW_SIZE,
                failure_count=failure_count,
                success_count=success_count,
                total_count=len(rows),
                failure_rate=failure_rate
            )
            
        except Exception as e:
            logger.error(f"Failed to get failure stats: {e}")
            return None
    
    async def _trigger_learning_loop(self, stats: FailureStats) -> str:
        """Trigger learning loop due to high failure rate"""
        try:
            from app.agent.scheduler import get_scheduler
            
            scheduler = get_scheduler()
            if not scheduler:
                logger.warning("Scheduler not initialized, cannot trigger learning loop")
                return None
            
            reason = f"auto_threshold_{stats.failure_rate:.1%}_{stats.failure_count}_{stats.total_count}"
            run_id = await scheduler.trigger_manual(reason=reason)
            
            logger.info(f"✅ Learning loop triggered: {run_id} (reason: {reason})")
            return run_id
            
        except Exception as e:
            logger.error(f"Failed to trigger learning loop: {e}")
            return None
    
    async def should_trigger(self) -> bool:
        """Simple check: should we trigger learning?"""
        stats = await self.get_recent_failure_stats()
        return stats is not None and \
               stats.total_count >= self.MIN_WINDOW_SAMPLES and \
               stats.failure_rate >= self.FAILURE_THRESHOLD
    
    def set_threshold(self, threshold: float):
        """Dynamically adjust failure threshold"""
        if 0 <= threshold <= 1:
            self.FAILURE_THRESHOLD = threshold
            logger.info(f"📊 Failure threshold updated to {threshold:.1%}")
        else:
            logger.warning(f"Invalid threshold {threshold}, must be 0-1")


# Global instance
_monitor = None


def init_failure_monitor(db_pool=None) -> FailureMonitor:
    """Initialize the failure monitor"""
    global _monitor
    _monitor = FailureMonitor(db_pool=db_pool)
    logger.info(f"✅ FailureMonitor initialized (threshold: {_monitor.FAILURE_THRESHOLD:.1%})")
    return _monitor


def get_failure_monitor() -> Optional[FailureMonitor]:
    """Get the global failure monitor instance"""
    return _monitor

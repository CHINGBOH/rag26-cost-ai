"""
Layer 2 - Failure Rate Threshold Trigger
Monitors recent query failures and triggers learning loop when rate exceeds threshold
Issue #96
"""

import logging
from typing import Optional
from collections import deque
from dataclasses import dataclass

from app.agent.learning_config import get_learning_config

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
    
    def __init__(self, db_pool=None):
        """
        Initialize failure monitor.
        
        Args:
            db_pool: psycopg2.ThreadedConnectionPool or None
        """
        config = get_learning_config().failure_monitor
        self.db_pool = db_pool
        self.FAILURE_THRESHOLD = config.failure_threshold
        self.WINDOW_SIZE = config.window_size
        self.MIN_WINDOW_SAMPLES = config.min_window_samples
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
        Get failure statistics from recent projection-backed runs.
        
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
                    try:
                        cur.execute(
                            """
                            SELECT quality
                            FROM agent_run_projection
                            WHERE learning_eligible = TRUE
                            ORDER BY completed_at DESC
                            LIMIT %s
                            """,
                            (self.WINDOW_SIZE,),
                        )
                        rows = cur.fetchall()
                    except Exception:
                        conn.rollback()
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
            
            # Projection path uses quality='failure'; legacy path uses status='error'.
            failure_count = sum(
                1 for (status_or_quality,) in rows
                if str(status_or_quality or "").lower() in {"error", "failure"}
            )
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
        """
        Trigger learning loop due to high failure rate
        
        Sprint 3: Routes through AdaptiveRetestScheduler if Feature Flag enabled.
        """
        from config.observability import log_decision, DecisionType  # Phase 1 #115
        try:
            # Sprint 3: Feature Flag control (#117)
            from config.feature_flags import is_feature_enabled
            from main import get_adaptive_retest_scheduler
            
            adaptive_scheduler = get_adaptive_retest_scheduler()
            
            if is_feature_enabled("LEARNING_USE_ADAPTIVE_SCHEDULER") and adaptive_scheduler:
                # 新路径：通过 AdaptiveRetestScheduler
                from app.agent.adaptive_retest_scheduler import RetestRequest, RetestPriority
                from datetime import datetime, timezone
                
                try:
                    question = f"High failure rate: {stats.failure_rate:.1%} ({stats.failure_count}/{stats.total_count})"
                    question_hash = await adaptive_scheduler.request_retest(RetestRequest(
                        question=question,
                        source="repeated",
                        priority=RetestPriority.REPEATED_QUESTION,
                        metadata={
                            "trigger": "failure_rate_threshold",
                            "failure_rate": stats.failure_rate,
                            "threshold": self.FAILURE_THRESHOLD,
                            "failure_count": stats.failure_count,
                            "total_count": stats.total_count,
                            "window_size": stats.window_size,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ))
                    
                    logger.info(f"✅ Failure threshold trigger queued via AdaptiveRetestScheduler: {question[:50]}... (hash={question_hash[:8]}...)")
                    log_decision(
                        decision_type=DecisionType.LEARNING_TRIGGER,
                        rationale=f"Failure rate {stats.failure_rate:.1%} exceeded threshold {self.FAILURE_THRESHOLD:.1%}, queued for learning",
                        inputs={"stats": str(stats), "threshold": self.FAILURE_THRESHOLD},
                        outputs={"triggered": True, "question_hash": question_hash, "method": "adaptive_scheduler"},
                        confidence=min(1.0, stats.failure_rate / self.FAILURE_THRESHOLD),
                        metadata={"window_size": stats.window_size, "failure_count": stats.failure_count}
                    )
                    return f"queued_{question_hash[:8]}"
                    
                except Exception as e:
                    logger.warning(f"Failed to queue via AdaptiveRetestScheduler, falling back to direct trigger: {e}")
            
            # 旧路径：直接触发（fallback）
            from app.agent.scheduler import get_scheduler
            
            scheduler = get_scheduler()
            if not scheduler:
                logger.warning("Scheduler not initialized, cannot trigger learning loop")
                log_decision(
                    decision_type=DecisionType.LEARNING_TRIGGER,
                    rationale="Learning trigger skipped: scheduler not initialized",
                    inputs={"stats": str(stats)},
                    outputs={"triggered": False, "reason": "no_scheduler"},
                    confidence=0.0,
                    metadata={"failure_rate": stats.failure_rate, "threshold": self.FAILURE_THRESHOLD}
                )
                return None
            
            reason = f"auto_threshold_{stats.failure_rate:.1%}_{stats.failure_count}_{stats.total_count}"
            run_id = await scheduler.trigger_manual(reason=reason)
            
            logger.info(f"✅ Learning loop triggered (direct): {run_id} (reason: {reason})")
            log_decision(
                decision_type=DecisionType.LEARNING_TRIGGER,
                rationale=f"Failure rate {stats.failure_rate:.1%} exceeded threshold {self.FAILURE_THRESHOLD:.1%}",
                inputs={"stats": str(stats), "threshold": self.FAILURE_THRESHOLD},
                outputs={"triggered": True, "run_id": run_id, "reason": reason, "method": "direct_trigger"},
                confidence=min(1.0, stats.failure_rate / self.FAILURE_THRESHOLD),
                metadata={"window_size": stats.window_size, "failure_count": stats.failure_count}
            )
            return run_id
            
        except Exception as e:
            logger.error(f"Failed to trigger learning loop: {e}")
            log_decision(
                decision_type=DecisionType.LEARNING_TRIGGER,
                rationale=f"Learning trigger failed with error: {str(e)}",
                inputs={"stats": str(stats)},
                outputs={"triggered": False, "error": str(e)},
                confidence=0.0,
                metadata={"failure_rate": stats.failure_rate}
            )
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


def shutdown_failure_monitor():
    """Reset the global failure monitor instance."""
    global _monitor
    _monitor = None

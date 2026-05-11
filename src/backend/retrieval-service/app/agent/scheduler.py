"""
Layer 2 - Cron Scheduler for Learning Loop
Triggers daily learning cycles at 2:00 AM UTC
Issue #96
"""

import logging
import json
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from contextlib import asynccontextmanager

from app.agent.event_ledger import insert_learning_run_event
from app.agent.gaps.repository import KnowledgeGapRepository
from app.agent.gaps.repair_tasks import GapRepairTaskService
from app.agent.gaps.retest import GapRetestService
from app.agent.gaps.workbench import GapWorkbenchService
from app.agent.learning_config import get_learning_config
from app.agent.learning_state import build_problem_gap_records, upsert_knowledge_gap_records

logger = logging.getLogger(__name__)

try:
    from app.agent.signal_collector import SignalCollector  # type: ignore
except Exception:  # pragma: no cover - fallback for patching/tests
    SignalCollector = None

try:
    from app.agent.problem_detector import ProblemDetector  # type: ignore
except Exception:  # pragma: no cover - fallback for patching/tests
    ProblemDetector = None

try:
    from app.agent.root_cause_analyzer import RootCauseAnalyzer  # type: ignore
except Exception:  # pragma: no cover - fallback for patching/tests
    RootCauseAnalyzer = None


class LearningScheduler:
    """
    Orchestrates learning loop execution on a schedule.
    - Cron trigger: daily at 2:00 AM UTC
    - Manual triggers via API
    - Records all runs to learning_runs table
    """
    
    def __init__(self, db_pool=None, adaptive_scheduler=None):
        """
        Initialize scheduler.
        
        Args:
            db_pool: psycopg2.ThreadedConnectionPool or None
            adaptive_scheduler: AdaptiveRetestScheduler instance (Sprint 2: #117)
        """
        self.db_pool = db_pool
        self.adaptive_scheduler = adaptive_scheduler
        self.scheduler = None
        self._running = False

    @staticmethod
    def _utc_timestamp() -> str:
        return datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        
    def start(self):
        """Start the scheduler"""
        try:
            # Import here to avoid hard dependency
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
            from apscheduler.triggers.interval import IntervalTrigger
            
            self.scheduler = AsyncIOScheduler()
            listener_config = get_learning_config().gap_retest_listener
            
            # Schedule daily learning loop at 2:00 AM UTC
            self.scheduler.add_job(
                self.run_learning_loop,
                CronTrigger(hour=2, minute=0, second=0),
                id='learning_loop_daily',
                name='Daily Learning Loop',
                misfire_grace_time=600,  # Allow up to 10 minutes late
                coalesce=True  # Merge missed executions
            )
            if listener_config.enabled:
                self.scheduler.add_job(
                    self.run_gap_retest_listener,
                    IntervalTrigger(seconds=listener_config.interval_seconds),
                    id='knowledge_gap_live_retest_listener',
                    name='Knowledge Gap Live Retest Listener',
                    next_run_time=datetime.now(timezone.utc)
                    + timedelta(seconds=listener_config.startup_delay_seconds),
                    misfire_grace_time=max(30, listener_config.consultation_timeout_seconds),
                    coalesce=True,
                    max_instances=1,
                )
            
            self.scheduler.start()
            self._running = True
            logger.info("✅ LearningScheduler: Daily cron scheduled for 02:00 UTC")
            if listener_config.enabled:
                logger.info(
                    "learning_gap_listener.scheduled interval_seconds=%s limit=%s "
                    "max_live_retests=%s actor=%s",
                    listener_config.interval_seconds,
                    listener_config.limit,
                    listener_config.max_live_retests,
                    listener_config.actor,
                )
            
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
        
        Sprint 2: Routes through AdaptiveRetestScheduler if Feature Flag enabled.
        """
        run_id = f"run_scheduled_{self._utc_timestamp()}"
        
        try:
            logger.info(f"🚀 Starting scheduled learning loop: {run_id}")
            
            # Sprint 2: Feature Flag control (#117)
            from config.feature_flags import is_feature_enabled
            
            if is_feature_enabled("LEARNING_USE_ADAPTIVE_SCHEDULER") and self.adaptive_scheduler:
                # 新路径：通过 AdaptiveRetestScheduler
                from app.agent.adaptive_retest_scheduler import RetestRequest, RetestPriority
                
                try:
                    question_hash = await self.adaptive_scheduler.request_retest(RetestRequest(
                        question=f"Scheduled learning loop: {run_id}",
                        source="timer",
                        priority=RetestPriority.TIMER,
                        metadata={
                            "run_id": run_id,
                            "trigger": "cron",
                            "schedule": "daily_02:00_UTC",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ))
                    
                    logger.info(f"✅ Scheduled learning loop queued via AdaptiveRetestScheduler: {run_id} (hash={question_hash[:8]}...)")
                    
                    await self._record_run(
                        run_id,
                        {"status": "queued", "started_by": "cron", "question_hash": question_hash, "method": "adaptive_scheduler"},
                        "queued",
                        "scheduled",
                        event_type="learning.run.queued",
                    )
                    
                    return
                    
                except Exception as e:
                    logger.warning(f"Failed to queue via AdaptiveRetestScheduler, falling back to direct execution: {e}")
            
            # 旧路径：直接执行（fallback）
            await self._record_run(
                run_id,
                {"status": "running", "started_by": "cron", "method": "direct_execution"},
                "running",
                "scheduled",
                event_type="learning.run.started",
            )
            result = await self._execute_learning_loop(
                run_id,
                run_type='scheduled',
                collector_cls=SignalCollector,
                detector_cls=ProblemDetector,
                analyzer_cls=RootCauseAnalyzer,
            )
            await self._record_run(run_id, result, 'completed')
            
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
        
        Sprint 2: Routes through AdaptiveRetestScheduler if Feature Flag enabled.
        
        Returns:
            run_id: identifier of the triggered run
        """
        run_id = f"run_manual_{self._utc_timestamp()}"
        
        try:
            logger.info(f"🔔 Manual learning loop triggered: {run_id} (reason: {reason})")
            
            # Sprint 2: Feature Flag control (#117)
            from config.feature_flags import is_feature_enabled
            
            if is_feature_enabled("LEARNING_USE_ADAPTIVE_SCHEDULER") and self.adaptive_scheduler:
                # 新路径：通过 AdaptiveRetestScheduler
                from app.agent.adaptive_retest_scheduler import RetestRequest, RetestPriority
                
                try:
                    question_hash = await self.adaptive_scheduler.request_retest(RetestRequest(
                        question=f"Manual learning trigger: {reason}",
                        source="manual",
                        priority=RetestPriority.MANUAL,
                        metadata={
                            "run_id": run_id,
                            "reason": reason,
                            "actor": "manual",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ))
                    
                    logger.info(f"✅ Manual trigger queued via AdaptiveRetestScheduler: {run_id} (hash={question_hash[:8]}...)")
                    
                    # Record to ledger
                    await self._record_run(
                        run_id,
                        {'status': 'queued', 'reason': reason, 'question_hash': question_hash, 'method': 'adaptive_scheduler'},
                        'queued',
                        'manual',
                        event_type='learning.run.queued',
                    )
                    
                    return run_id
                    
                except Exception as e:
                    logger.warning(f"Failed to queue via AdaptiveRetestScheduler, falling back to direct trigger: {e}")
            
            # 旧路径：直接触发（fallback）
            asyncio.create_task(
                self.run_learning_loop_with_run_id(
                    run_id,
                    'manual',
                    collector_cls=SignalCollector,
                    detector_cls=ProblemDetector,
                    analyzer_cls=RootCauseAnalyzer,
                )
            )
            
            # Record that we're starting
            await self._record_run(
                run_id,
                {'status': 'running', 'reason': reason, 'method': 'direct_trigger'},
                'running',
                'manual',
                event_type='learning.run.triggered',
            )
            
            return run_id
            
        except Exception as e:
            logger.error(f"Failed to trigger manual learning: {e}")
            return None

    async def run_gap_retest_listener(self):
        """Run one configured live consultation retest cycle for active knowledge gaps."""
        run_id = f"run_gap_retest_{self._utc_timestamp()}"
        try:
            logger.info("learning_gap_listener.started run_id=%s", run_id)
            await self._record_run(
                run_id,
                {"status": "running", "started_by": "gap_retest_listener"},
                "running",
                "auto_threshold",
                event_type="learning.gap_retest.started",
            )
            result = await self._execute_gap_retest_listener(run_id)
            await self._record_run(
                run_id,
                result,
                "completed",
                "auto_threshold",
                event_type="learning.gap_retest.completed",
            )
            logger.info(
                "learning_gap_listener.completed run_id=%s live_retests_used=%s counts=%s",
                run_id,
                result.get("live_retests_used"),
                result.get("counts"),
            )
        except Exception as exc:
            logger.error("learning_gap_listener.failed run_id=%s error=%s", run_id, exc, exc_info=True)
            await self._record_run(
                run_id,
                {"status": "failed", "error": str(exc), "started_by": "gap_retest_listener"},
                "failed",
                "auto_threshold",
                event_type="learning.gap_retest.failed",
            )

    async def _execute_gap_retest_listener(self, run_id: str) -> Dict[str, Any]:
        config = get_learning_config().gap_retest_listener
        repository = KnowledgeGapRepository()
        projection_reconciled: List[Dict[str, Any]] = []
        if (
            getattr(config, "projection_reconcile_enabled", True)
            and not getattr(config, "dry_run", False)
        ):
            projection_reconciled = repository.reconcile_latest_evidence_projection(
                actor=config.actor,
                limit=getattr(config, "projection_reconcile_limit", 200),
            )
        fixed_state_invalidated: List[Dict[str, Any]] = []
        if (
            getattr(config, "fixed_state_invalidation_enabled", True)
            and not getattr(config, "dry_run", False)
        ):
            fixed_state_invalidated = repository.invalidate_stale_fixed_state(
                actor=config.actor,
                limit=getattr(config, "fixed_state_invalidation_limit", 100),
            )
        statuses = ["open", "in_progress"] if config.active_only else None
        active_gaps = repository.fetch_gaps(
            statuses=statuses,
            limit=int(config.limit or 20),
        )
        queued_gap_keys = [str(gap.get("gap_key") or "") for gap in active_gaps]
        skipped_repair_task_gap_keys = sorted(repository.fetch_active_repair_task_keys(queued_gap_keys))
        skipped_linked_event_gap_keys = sorted(
            str(gap.get("gap_key") or "")
            for gap in active_gaps
            if gap.get("linked_event_id") is not None or gap.get("affected_route")
        )
        skipped_gap_keys = set(skipped_repair_task_gap_keys) | set(skipped_linked_event_gap_keys)
        active_gaps = [
            gap
            for gap in active_gaps
            if str(gap.get("gap_key") or "") not in skipped_gap_keys
        ]
        retest_limit = max(0, min(int(config.max_live_retests or 0), len(active_gaps)))
        actions: List[Dict[str, Any]] = []
        counts: Dict[str, int] = {}
        
        # Sprint 3: Feature Flag control - Route through AdaptiveRetestScheduler if enabled (#117)
        from config.feature_flags import is_feature_enabled
        
        if is_feature_enabled("LEARNING_USE_ADAPTIVE_SCHEDULER") and self.adaptive_scheduler:
            # 新路径：通过 AdaptiveRetestScheduler 统一调度
            from app.agent.adaptive_retest_scheduler import RetestRequest, RetestPriority
            from datetime import datetime, timezone
            
            try:
                queued_count = 0
                for gap in active_gaps[:retest_limit]:
                    gap_key = str(gap.get("gap_key") or "")
                    query = str(gap.get("query") or gap.get("query_text") or gap.get("description") or f"gap_{gap_key}")
                    
                    await self.adaptive_scheduler.request_retest(RetestRequest(
                        question=query[:500],  # Limit length
                        source="patch",
                        priority=RetestPriority.PATCH,
                        metadata={
                            "trigger": "gap_retest_listener",
                            "gap_key": gap_key,
                            "gap_status": gap.get("status"),
                            "cause_type": gap.get("cause_type"),
                            "run_id": run_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ))
                    queued_count += 1
                
                logger.info(f"✅ Gap retest listener queued {queued_count} gaps via AdaptiveRetestScheduler")
                counts["queued_via_adaptive_scheduler"] = queued_count
                
            except Exception as e:
                logger.warning(f"Failed to queue gaps via AdaptiveRetestScheduler, falling back to direct execution: {e}")
                # Fallback to direct execution
                retester = GapRetestService(repository=repository)
                for gap in active_gaps[:retest_limit]:
                    result = await retester.retest_gap(
                        gap,
                        actor=config.actor,
                        consultation_endpoint=config.consultation_endpoint,
                        timeout_seconds=config.consultation_timeout_seconds,
                        max_iterations=config.max_iterations,
                        observation_window_days=config.observation_window_days,
                        dry_run=config.dry_run,
                    )
                    action = str(result.get("action") or "unknown")
                    counts[action] = counts.get(action, 0) + 1
                    actions.append(result)
        else:
            # 旧路径：直接执行 gap retest（fallback）
            retester = GapRetestService(repository=repository)
            for gap in active_gaps[:retest_limit]:
                result = await retester.retest_gap(
                    gap,
                    actor=config.actor,
                    consultation_endpoint=config.consultation_endpoint,
                    timeout_seconds=config.consultation_timeout_seconds,
                    max_iterations=config.max_iterations,
                    observation_window_days=config.observation_window_days,
                    dry_run=config.dry_run,
                )
                action = str(result.get("action") or "unknown")
                counts[action] = counts.get(action, 0) + 1
                actions.append(result)
        repair_promotions: list[dict[str, Any]] = []
        if config.repair_promotion_enabled and not config.dry_run:
            repair_promotions = GapRepairTaskService(repository=repository).promote_from_retest_actions(
                active_gaps=active_gaps,
                actions=actions,
                actor=config.actor,
                min_keep_open_evidence=config.repair_promotion_min_keep_open_evidence,
                issue_number=config.repair_promotion_issue_number,
                issue_url=config.repair_promotion_issue_url,
            )

        # F2 (#135): 扫描 observation_window 已过期的 observing gap，复测决策是否 resolve
        # 没有这一步，gap 会永远卡在 observing 状态，前端「待解决问题」永远不减少
        observation_resolutions: list[dict[str, Any]] = []
        if not config.dry_run:
            try:
                observation_resolutions = await self._resolve_expired_observing_gaps(
                    repository=repository,
                    actor=config.actor,
                    config=config,
                )
                if observation_resolutions:
                    logger.info(
                        "learning_gap_listener.observation_window_check resolved=%s actions=%s",
                        sum(1 for r in observation_resolutions if r.get("action") == "resolve_after_observation"),
                        [r.get("action") for r in observation_resolutions],
                    )
            except Exception as exc:
                logger.warning("observation_window_check failed: %s", exc)

        summary = GapWorkbenchService(repository=repository).build(
            include_resolved=False,
            limit=int(config.limit or 20),
        ).get("counts", {})
        return {
            "run_id": run_id,
            "status": "completed",
            "trigger": "gap_retest_listener",
            "active_only": config.active_only,
            "live_retest": True,
            "limit": config.limit,
            "max_live_retests": config.max_live_retests,
            "active_detected": len(queued_gap_keys),
            "active_gap_keys": queued_gap_keys,
            "projection_reconciled": projection_reconciled,
            "projection_reconciled_count": len(projection_reconciled),
            "fixed_state_invalidated": fixed_state_invalidated,
            "fixed_state_invalidated_count": len(fixed_state_invalidated),
            "skipped_repair_task_gap_keys": skipped_repair_task_gap_keys,
            "skipped_linked_event_gap_keys": skipped_linked_event_gap_keys,
            "live_retests_used": len(actions),
            "counts": counts,
            "repair_promotions": repair_promotions,
            "observation_resolutions": observation_resolutions,
            "observation_resolutions_count": len(observation_resolutions),
            "summary": summary,
            "actions": actions,
        }

    async def _resolve_expired_observing_gaps(
        self,
        *,
        repository: "KnowledgeGapRepository",
        actor: str,
        config,
    ) -> list[dict[str, Any]]:
        """F2 (#135): 扫描 observation_window 已过期的 observing gap，复测后决策是否 resolve。

        Without this, gaps stay stuck in observing forever even when the system has
        clearly fixed them, because decide_from_live_retest 永远只会把 observing 复测
        结果继续返回 observing 状态。
        """
        expired_gaps = repository.fetch_gaps(
            statuses=["observing"],
            limit=int(getattr(config, "limit", 20) or 20),
        )
        # 客户端过滤过期窗口（避免后端 SQL 改动）
        from app.agent.gaps.lifecycle import _observation_window_expired
        expired_gaps = [g for g in expired_gaps if _observation_window_expired(g)]
        if not expired_gaps:
            return []

        # 限制本轮处理数量（避免一次性把所有过期 gap 全跑）
        retest_limit = max(1, int(getattr(config, "max_live_retests", 3) or 3))
        retester = GapRetestService(repository=repository)
        results: list[dict[str, Any]] = []
        for gap in expired_gaps[:retest_limit]:
            try:
                result = await retester.retest_gap(
                    gap,
                    actor=actor,
                    consultation_endpoint=config.consultation_endpoint,
                    timeout_seconds=config.consultation_timeout_seconds,
                    max_iterations=config.max_iterations,
                    observation_window_days=config.observation_window_days,
                    dry_run=config.dry_run,
                )
                results.append(result)
            except Exception as exc:
                logger.warning("expired_observing_retest_failed gap_key=%s err=%s", gap.get("gap_key"), exc)
        return results
    
    async def run_learning_loop_with_run_id(
        self,
        run_id: str,
        run_type: str = 'manual',
        collector_cls=None,
        detector_cls=None,
        analyzer_cls=None,
    ):
        """Internal method to run learning loop with specific run_id"""
        try:
            await self._record_run(
                run_id,
                {'status': 'running'},
                'running',
                run_type,
                event_type='learning.run.started',
            )
            result = await self._execute_learning_loop(
                run_id,
                run_type=run_type,
                collector_cls=collector_cls or SignalCollector,
                detector_cls=detector_cls or ProblemDetector,
                analyzer_cls=analyzer_cls or RootCauseAnalyzer,
            )
            await self._record_run(run_id, result, 'completed', run_type)
            
        except Exception as e:
            logger.error(f"Learning loop {run_id} failed: {e}", exc_info=True)
            await self._record_run(run_id, {'status': 'failed', 'error': str(e)}, 'failed', run_type)

    async def _execute_learning_loop(
        self,
        run_id: str,
        run_type: str,
        collector_cls,
        detector_cls,
        analyzer_cls,
    ) -> Dict[str, Any]:
        collector = collector_cls(pool=self.db_pool)
        signals = await collector.aggregate_all()
        logger.info(
            f"📊 Collected {signals.total_count} signals "
            f"(severity: {signals.severity_score:.1f}, time: {signals.total_collect_time_ms:.0f}ms)"
        )

        detector = detector_cls()
        problems = await detector.detect_problems(signals)
        logger.info(f"🎯 Detected {len(problems)} problems")

        if problems and self.db_pool:
            try:
                upsert_knowledge_gap_records(
                    build_problem_gap_records([problem.to_dict() for problem in problems], run_id=run_id),
                    pool=self.db_pool,
                )
            except Exception as exc:
                logger.warning("Knowledge gap persistence skipped for %s: %s", run_id, exc)

        root_causes = await self._analyze_root_causes(
            problems,
            signals,
            analyzer_cls=analyzer_cls,
        )

        return {
            'run_id': run_id,
            'run_type': run_type,
            'signals_count': signals.total_count,
            'severity_score': signals.severity_score,
            'problems_count': len(problems),
            'collect_time_ms': signals.total_collect_time_ms,
            'status': 'completed',
            'signal_summary': self._build_signal_summary(signals),
            'problems': [problem.to_dict() for problem in problems],
            'root_causes': root_causes,
        }

    async def _analyze_root_causes(
        self,
        problems: List[Any],
        signals: Any,
        analyzer_cls,
    ) -> List[Dict[str, Any]]:
        if not analyzer_cls:
            return []

        analyzer = analyzer_cls()
        context = {
            'signal_counts': self._build_signal_summary(signals),
            'severity_score': signals.severity_score,
            'total_collect_time_ms': signals.total_collect_time_ms,
        }

        root_causes: List[Dict[str, Any]] = []
        for problem in problems:
            report = await analyzer.analyze_root_cause(problem, signals_context=context)
            root_causes.append(report.to_dict())

        return root_causes

    def _build_signal_summary(self, signals: Any) -> Dict[str, int]:
        return {
            'feedback': len(getattr(signals, 'feedback_signals', [])),
            'failures': len(getattr(signals, 'failure_signals', [])),
            'repeats': len(getattr(signals, 'repeat_signals', [])),
            'violations': len(getattr(signals, 'violation_signals', [])),
            'topology': len(getattr(signals, 'topo_signals', [])),
        }
    
    async def _record_run(
        self,
        run_id: str,
        result: Dict,
        status: str,
        run_type: str = 'scheduled',
        *,
        event_type: Optional[str] = None,
    ):
        """Record learning loop execution to database"""
        if not self.db_pool:
            logger.warning(f"No DB pool, cannot record run {run_id}")
            return
        
        normalized_event_type = event_type or {
            'running': 'learning.run.started',
            'completed': 'learning.run.completed',
            'failed': 'learning.run.failed',
        }.get(status, 'learning.run.updated')
        try:
            conn = self.db_pool.getconn()
            try:
                with conn.cursor() as cur:
                    insert_learning_run_event(
                        cur,
                        run_id=run_id,
                        run_type=run_type,
                        status=status,
                        event_type=normalized_event_type,
                        result=result,
                    )
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


def init_scheduler(db_pool=None, adaptive_scheduler=None) -> LearningScheduler:
    """Initialize and start the learning scheduler
    
    Args:
        db_pool: Database connection pool
        adaptive_scheduler: AdaptiveRetestScheduler instance (Sprint 2: #117)
    """
    global _scheduler
    _scheduler = LearningScheduler(db_pool=db_pool, adaptive_scheduler=adaptive_scheduler)
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

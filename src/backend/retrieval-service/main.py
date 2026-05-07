"""
Retrieval Service - FastAPI 入口
端口: 8002
"""

import logging
import os
import sys
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

# Add repo root to Python path for config modules
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.runtime_config import bootstrap_runtime_environment

bootstrap_runtime_environment()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router, set_services
from app.agent.learning_state import list_resumable_improvement_event_ids
from app.tools_api import router as tools_router
from app.pipeline import UnifiedRetrievalPipeline
from infrastructure.adapters.unified import UnifiedStore

# Prometheus metrics for observability
try:
    from prometheus_client import make_asgi_app
    PROMETHEUS_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ prometheus_client not installed, /metrics endpoint will not be available")
    PROMETHEUS_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局服务实例
_pipeline = None
_store = None
_scheduler = None
_failure_monitor = None
_feedback_analyzer = None
_adaptive_retest_scheduler = None  # Phase 1+ Task 3: #117
_learning_resume_tasks = set()


async def _resume_improvement_event(event_id: int):
    from app.agent.executor import execute_improvement_event

    try:
        result = await execute_improvement_event(event_id)
        if not result.get("success"):
            logger.error("Executor resume failed: event_id=%s error=%s", event_id, result.get("error"))
    except Exception as exc:
        logger.error("Executor resume crashed: event_id=%s error=%s", event_id, exc, exc_info=True)


def _track_learning_resume_task(task: asyncio.Task) -> asyncio.Task:
    _learning_resume_tasks.add(task)
    task.add_done_callback(_learning_resume_tasks.discard)
    return task


def _schedule_resumable_improvement_events(db_pool) -> list[int]:
    if not db_pool:
        return []

    try:
        event_ids = list_resumable_improvement_event_ids(pool=db_pool, limit=50)
    except Exception as exc:
        logger.warning("Skipping resumable improvement event scan: %s", exc)
        return []

    for event_id in event_ids:
        _track_learning_resume_task(asyncio.create_task(_resume_improvement_event(event_id)))

    if event_ids:
        logger.info("Scheduled %d resumable improvement events on startup", len(event_ids))

    return event_ids


def _initialize_layer2_components(db_pool, asyncpg_pool=None):
    """Initialize scheduler and monitors against the current DB pool."""
    global _scheduler, _failure_monitor, _feedback_analyzer, _adaptive_retest_scheduler

    logger.info("Initializing Layer 2 trigger mechanisms...")
    
    # Phase 1+ Task 3: Initialize AdaptiveRetestScheduler (#117)
    try:
        from app.agent.adaptive_retest_scheduler import AdaptiveRetestScheduler
        from app.adaptive_retest_api import set_scheduler
        
        if asyncpg_pool:
            _adaptive_retest_scheduler = AdaptiveRetestScheduler(asyncpg_pool, max_concurrent=3)
            set_scheduler(_adaptive_retest_scheduler)  # 注入到 API 模块
            logger.info("✅ AdaptiveRetestScheduler initialized with asyncpg pool (Sprint 2, ready for triggers)")
        else:
            logger.warning("⚠️ AdaptiveRetestScheduler skipped: asyncpg pool not available")
    except Exception as e:
        _adaptive_retest_scheduler = None
        logger.warning(f"⚠️ Failed to initialize AdaptiveRetestScheduler: {e}")
        import traceback
        logger.warning(traceback.format_exc())

    try:
        from app.agent.scheduler import init_scheduler

        # Sprint 2: 传递 AdaptiveRetestScheduler 到 LearningScheduler
        _scheduler = init_scheduler(
            db_pool=db_pool,
            adaptive_scheduler=_adaptive_retest_scheduler
        )
    except Exception as e:
        _scheduler = None
        logger.warning(f"⚠️  Failed to initialize learning scheduler: {e}")

    try:
        from app.agent.failure_monitor import init_failure_monitor

        _failure_monitor = init_failure_monitor(db_pool=db_pool)
    except Exception as e:
        _failure_monitor = None
        logger.warning(f"⚠️  Failed to initialize failure monitor: {e}")

    try:
        from app.agent.feedback_analyzer import init_feedback_analyzer

        _feedback_analyzer = init_feedback_analyzer(db_pool=db_pool)
    except Exception as e:
        _feedback_analyzer = None
        logger.warning(f"⚠️  Failed to initialize feedback analyzer: {e}")

    logger.info("✅ Layer 2 trigger mechanisms initialized")


def _shutdown_layer2_components():
    """Shutdown and clear scheduler and monitor globals."""
    global _scheduler, _failure_monitor, _feedback_analyzer, _adaptive_retest_scheduler

    logger.info("Shutting down Layer 2 trigger mechanisms...")
    
    # Phase 1+ Task 3: Shutdown AdaptiveRetestScheduler (#117)
    if _adaptive_retest_scheduler:
        try:
            logger.info("Shutting down AdaptiveRetestScheduler...")
            _adaptive_retest_scheduler = None
        except Exception as e:
            logger.warning(f"Error shutting down AdaptiveRetestScheduler: {e}")

    try:
        from app.agent.scheduler import shutdown_scheduler

        shutdown_scheduler()
    except Exception as e:
        logger.warning(f"Error shutting down scheduler: {e}")
    finally:
        _scheduler = None

    try:
        from app.agent.failure_monitor import shutdown_failure_monitor

        shutdown_failure_monitor()
    except Exception as e:
        logger.warning(f"Error shutting down failure monitor: {e}")
    finally:
        _failure_monitor = None

    try:
        from app.agent.feedback_analyzer import shutdown_feedback_analyzer

        shutdown_feedback_analyzer()
    except Exception as e:
        logger.warning(f"Error shutting down feedback analyzer: {e}")
    finally:
        _feedback_analyzer = None

    for task in list(_learning_resume_tasks):
        task.cancel()
    _learning_resume_tasks.clear()


def get_adaptive_retest_scheduler():
    """Sprint 2: Global getter for AdaptiveRetestScheduler (#117)"""
    return _adaptive_retest_scheduler


async def _update_prometheus_metrics_loop():
    """
    Background task to periodically update Prometheus metrics
    Updates queue metrics every 30 seconds
    """
    while True:
        try:
            if _adaptive_retest_scheduler and PROMETHEUS_AVAILABLE:
                from app.observability.prometheus_metrics import update_queue_metrics
                await update_queue_metrics(_adaptive_retest_scheduler)
            
            # Wait 30 seconds before next update
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            # Task cancelled during shutdown
            break
        except Exception as e:
            logger.warning(f"⚠️ Error updating Prometheus metrics: {e}")
            await asyncio.sleep(30)  # Continue even if update fails



@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pipeline, _store, _scheduler, _failure_monitor, _feedback_analyzer, _adaptive_retest_scheduler
    try:
        # Phase 1: Initialize Parameter Registry and Observability (#114, #115)
        logger.info("Initializing Phase 1 infrastructure...")
        try:
            from config.default_params import register_all
            register_all()
            logger.info("✅ Parameter Registry initialized")
        except Exception as e:
            logger.warning(f"⚠️ Parameter Registry initialization failed: {e}")
        
        try:
            from config.observability import DecisionLogger
            DecisionLogger.initialize(log_dir="logs/decisions", max_buffer_size=100)
            logger.info("✅ Observability Layer initialized")
        except Exception as e:
            logger.warning(f"⚠️ Observability Layer initialization failed: {e}")
        
        logger.info("Initializing UnifiedStore...")
        _store = UnifiedStore()
        logger.info("UnifiedStore initialized")
        logger.info("Initializing UnifiedRetrievalPipeline...")
        _pipeline = UnifiedRetrievalPipeline(_store)
        logger.info("UnifiedRetrievalPipeline initialized")
        set_services(_pipeline, _store)
        logger.info("✅ Retrieval Service ready on port 8002")

        # Sprint 2: Create asyncpg pool for AdaptiveRetestScheduler
        asyncpg_pool = None
        try:
            import asyncpg
            asyncpg_pool = await asyncpg.create_pool(
                host='localhost',
                port=5432,
                user='rag_user',
                password='rag_password',
                database='rag_db',
                min_size=2,
                max_size=10
            )
            logger.info("✅ Asyncpg pool created for AdaptiveRetestScheduler")
        except Exception as e:
            logger.warning(f"⚠️ Failed to create asyncpg pool: {e}")

        db_pool = _get_db_pool()
        _shutdown_layer2_components()
        _initialize_layer2_components(db_pool, asyncpg_pool)
        _schedule_resumable_improvement_events(db_pool)
        
        # Start background task to update Prometheus metrics
        metrics_task = None
        if PROMETHEUS_AVAILABLE and _adaptive_retest_scheduler:
            metrics_task = asyncio.create_task(_update_prometheus_metrics_loop())
            logger.info("✅ Prometheus metrics updater started")
        
    except Exception as e:
        import traceback
        logger.warning(f"⚠️ Failed to initialize some services: {e}")
        logger.warning(f"Traceback: {traceback.format_exc()}")
        _shutdown_layer2_components()
        set_services(None, _store)
    
    yield

    # Stop Prometheus metrics updater
    if 'metrics_task' in locals() and metrics_task and not metrics_task.done():
        metrics_task.cancel()
        try:
            await metrics_task
        except asyncio.CancelledError:
            pass
        logger.info("✅ Prometheus metrics updater stopped")

    _shutdown_layer2_components()
    
    # Phase 1: Flush Observability buffer on shutdown (#115)
    try:
        from config.observability import DecisionLogger
        DecisionLogger.flush()
        logger.info("✅ Observability buffer flushed")
    except Exception as e:
        logger.warning(f"⚠️ Observability flush failed: {e}")
    
    if _store:
        _store.close()
        logger.info("✅ Retrieval Service shutdown")


def _get_db_pool():
    """Helper to get database connection pool from UnifiedStore"""
    try:
        if _store and hasattr(_store, 'pg_pool'):
            return _store.pg_pool
    except Exception as e:
        logger.warning(f"Could not get DB pool from store: {e}")
    return None


app = FastAPI(
    title="Retrieval Service",
    description="独立检索微服务 - 向量/关键词/图谱混合检索、精排、评估、查询分解",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Prometheus /metrics endpoint
if PROMETHEUS_AVAILABLE:
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)
    logger.info("✅ Prometheus /metrics endpoint mounted")


# Lightweight in-memory request metrics for /api/v1/ops/metrics
@app.middleware("http")
async def _metrics_middleware(request, call_next):
    import time as _t
    from app.api import ops_record_request

    t0 = _t.monotonic()
    response = await call_next(request)
    dur_ms = (_t.monotonic() - t0) * 1000.0
    try:
        ops_record_request(dur_ms, response.status_code, request.url.path)
    except Exception:
        pass
    return response


app.include_router(router)
app.include_router(tools_router)

# Phase 1 Infrastructure APIs (#113, #114, #115)
try:
    from app.feature_flag_api import router as feature_flag_router
    app.include_router(feature_flag_router)
    logger.info("✅ Feature Flag API registered")
except Exception as e:
    logger.warning(f"⚠️ Feature Flag API registration failed: {e}")

try:
    from app.param_api import router as param_router
    app.include_router(param_router)
    logger.info("✅ Parameter Registry API registered")
except Exception as e:
    logger.warning(f"⚠️ Parameter Registry API registration failed: {e}")

try:
    from app.observability_api import router as observability_router
    app.include_router(observability_router)
    logger.info("✅ Observability API registered")
except Exception as e:
    logger.warning(f"⚠️ Observability API registration failed: {e}")

# Phase 1+ Task 3: Adaptive Retest Scheduler API (#117, Sprint 1)
try:
    from app.adaptive_retest_api import router as adaptive_retest_router
    app.include_router(adaptive_retest_router)
    logger.info("✅ Adaptive Retest Scheduler API registered")
except Exception as e:
    logger.warning(f"⚠️ Adaptive Retest Scheduler API registration failed: {e}")

# OpenTelemetry — opt-in via OTEL_EXPORTER_OTLP_ENDPOINT (#87 P4)
try:
    from app.telemetry import init_telemetry
    init_telemetry(app)
except Exception as _otel_exc:  # never block startup on tracing
    logger.warning(f"telemetry init failed: {_otel_exc}")

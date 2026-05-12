"""
Prometheus Metrics for RAG Dashboard

Purpose: 暴露关键业务指标供 Prometheus 采集
Author: AI Agent
Date: 2026-05-08
"""

from prometheus_client import Counter, Gauge, Histogram, Info
import logging

logger = logging.getLogger(__name__)

# =====================================================
# AdaptiveRetestScheduler Metrics
# =====================================================

# 队列指标
retest_queue_size = Gauge(
    'retest_queue_size',
    'Current number of items in retest queue',
    ['status']  # pending, running, success, failed
)

retest_queue_age_seconds = Histogram(
    'retest_queue_age_seconds',
    'Age of oldest pending item in queue (seconds)',
    buckets=[60, 300, 900, 3600, 14400, 86400]  # 1m, 5m, 15m, 1h, 4h, 24h
)

# 请求指标
retest_requests_total = Counter(
    'retest_requests_total',
    'Total number of retest requests',
    ['source', 'priority']  # source: manual, timer, feedback, etc. | priority: 5-10
)

retest_requests_deduplicated_total = Counter(
    'retest_requests_deduplicated_total',
    'Total number of deduplicated retest requests',
    ['source']
)

# 执行指标
retest_execution_total = Counter(
    'retest_execution_total',
    'Total number of retest executions',
    ['status']  # success, failed
)

retest_execution_duration_seconds = Histogram(
    'retest_execution_duration_seconds',
    'Duration of retest execution (seconds)',
    buckets=[10, 30, 60, 120, 300, 600, 1200]  # 10s, 30s, 1m, 2m, 5m, 10m, 20m
)

retest_retry_count = Histogram(
    'retest_retry_count',
    'Number of retries before success or final failure',
    buckets=[0, 1, 2, 3, 4, 5]  # 对应退避策略
)

# 去重指标
retest_deduplication_rate = Gauge(
    'retest_deduplication_rate',
    'Deduplication rate (0-1)',
    ['window']  # 1h, 24h, 7d
)

# =====================================================
# Learning System Metrics
# =====================================================

learning_loop_total = Counter(
    'learning_loop_total',
    'Total number of learning loop executions',
    ['trigger_source', 'status']  # trigger_source: manual, timer, feedback, etc. | status: success, failed
)

learning_loop_duration_seconds = Histogram(
    'learning_loop_duration_seconds',
    'Duration of learning loop execution (seconds)',
    buckets=[60, 300, 600, 1200, 1800, 3600]  # 1m, 5m, 10m, 20m, 30m, 60m
)

learning_improvements_detected = Counter(
    'learning_improvements_detected',
    'Number of improvements detected by learning system',
    ['improvement_type']  # parameter_tuning, retrieval_strategy, etc.
)

# F4 (#135): 缺口闭环健康度指标
gap_retest_listener_last_run_ts = Gauge(
    'gap_retest_listener_last_run_ts',
    'Unix timestamp of the last successful learning_gap_listener cycle. '
    'Alert if (time() - this_value) > 600 — listener has stalled.'
)

gap_retest_listener_runs_total = Counter(
    'gap_retest_listener_runs_total',
    'Total cycles of learning_gap_listener executed',
    ['status']  # success | failed
)

gap_retest_listener_retests_total = Counter(
    'gap_retest_listener_retests_total',
    'Total live retests issued by listener',
    ['action']  # observe_fixed | keep_open | block_policy | reopen | resolve_after_observation
)

gap_realtime_resolutions_total = Counter(
    'gap_realtime_resolutions_total',
    'Total agent-realtime gap state transitions (F3)',
    ['action']  # observe_fixed | reopen | etc.
)

# =====================================================
# Decision Logger Metrics
# =====================================================

decision_logs_total = Counter(
    'decision_logs_total',
    'Total number of decision logs recorded',
    ['decision_type']  # followup_filtering, tool_selection, retrieval_strategy, etc.
)

# =====================================================
# Retrieval Metrics
# =====================================================

retrieval_requests_total = Counter(
    'retrieval_requests_total',
    'Total number of retrieval requests',
    ['database', 'strategy']  # database: qdrant, elasticsearch, etc. | strategy: vector, bm25, hybrid
)

retrieval_duration_seconds = Histogram(
    'retrieval_duration_seconds',
    'Duration of retrieval operation (seconds)',
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
)

retrieval_chunks_returned = Histogram(
    'retrieval_chunks_returned',
    'Number of chunks returned from retrieval',
    buckets=[5, 10, 15, 20, 30, 50, 100]
)

# =====================================================
# RAG Agent Metrics
# =====================================================

rag_agent_requests_total = Counter(
    'rag_agent_requests_total',
    'Total number of RAG agent requests',
    ['outcome']  # success, failed, timeout
)

rag_agent_duration_seconds = Histogram(
    'rag_agent_duration_seconds',
    'Duration of RAG agent request (seconds)',
    buckets=[1, 5, 10, 20, 30, 60, 120]
)

rag_agent_iterations = Histogram(
    'rag_agent_iterations',
    'Number of iterations in RAG agent execution',
    buckets=[1, 2, 3, 4, 5, 10]
)

rag_agent_tool_calls_total = Counter(
    'rag_agent_tool_calls_total',
    'Total number of tool calls in RAG agent',
    ['tool_name']  # search_database, search_graph, consult_expert, etc.
)

# =====================================================
# Feedback Metrics
# =====================================================

feedback_submissions_total = Counter(
    'feedback_submissions_total',
    'Total number of feedback submissions',
    ['rating', 'has_tags']  # rating: positive, negative | has_tags: true, false
)

feedback_analysis_triggers_total = Counter(
    'feedback_analysis_triggers_total',
    'Total number of learning triggers from feedback analysis',
    ['trending_tag']  # 触发学习的主要 tag
)

# =====================================================
# Failure Monitor Metrics
# =====================================================

failure_monitor_window_size = Gauge(
    'failure_monitor_window_size',
    'Current size of failure monitor sliding window'
)

failure_monitor_rate = Gauge(
    'failure_monitor_rate',
    'Current failure rate (0-1)'
)

failure_monitor_triggers_total = Counter(
    'failure_monitor_triggers_total',
    'Total number of learning triggers from failure monitor'
)

# =====================================================
# System Info
# =====================================================

system_info = Info(
    'rag_system',
    'RAG Dashboard system information'
)

# 初始化系统信息
system_info.info({
    'version': '1.0.0',
    'component': 'retrieval-service',
    'feature_flags': 'enabled',
    'adaptive_scheduler': 'enabled'
})

# =====================================================
# Helper Functions
# =====================================================

def record_retest_request(source: str, priority: int, deduplicated: bool = False):
    """记录重测请求"""
    retest_requests_total.labels(source=source, priority=str(priority)).inc()
    if deduplicated:
        retest_requests_deduplicated_total.labels(source=source).inc()

def record_retest_execution(status: str, duration_seconds: float, retry_count: int):
    """记录重测执行"""
    retest_execution_total.labels(status=status).inc()
    retest_execution_duration_seconds.observe(duration_seconds)
    retest_retry_count.observe(retry_count)

def record_learning_loop(trigger_source: str, status: str, duration_seconds: float):
    """记录 learning loop 执行"""
    learning_loop_total.labels(trigger_source=trigger_source, status=status).inc()
    learning_loop_duration_seconds.observe(duration_seconds)

def record_decision_log(decision_type: str):
    """记录决策日志"""
    decision_logs_total.labels(decision_type=decision_type).inc()

def record_retrieval(database: str, strategy: str, duration_seconds: float, chunk_count: int):
    """记录检索操作"""
    retrieval_requests_total.labels(database=database, strategy=strategy).inc()
    retrieval_duration_seconds.observe(duration_seconds)
    retrieval_chunks_returned.observe(chunk_count)

def record_rag_agent_request(outcome: str, duration_seconds: float, iterations: int):
    """记录 RAG agent 请求"""
    rag_agent_requests_total.labels(outcome=outcome).inc()
    rag_agent_duration_seconds.observe(duration_seconds)
    rag_agent_iterations.observe(iterations)

def record_tool_call(tool_name: str):
    """记录工具调用"""
    rag_agent_tool_calls_total.labels(tool_name=tool_name).inc()

def record_feedback(rating: str, has_tags: bool):
    """记录用户反馈"""
    feedback_submissions_total.labels(
        rating=rating,
        has_tags='true' if has_tags else 'false'
    ).inc()

def record_feedback_trigger(trending_tag: str):
    """记录反馈触发学习"""
    feedback_analysis_triggers_total.labels(trending_tag=trending_tag).inc()

def update_failure_monitor(window_size: int, failure_rate: float):
    """更新失败监控指标"""
    failure_monitor_window_size.set(window_size)
    failure_monitor_rate.set(failure_rate)

def record_failure_trigger():
    """记录失败监控触发学习"""
    failure_monitor_triggers_total.inc()

async def update_queue_metrics(scheduler):
    """
    更新队列指标（需要定期调用）
    
    Args:
        scheduler: AdaptiveRetestScheduler 实例
    """
    try:
        # 获取队列状态统计
        stats = await scheduler.get_queue_stats()
        
        for status, count in stats.get('by_status', {}).items():
            retest_queue_size.labels(status=status).set(count)
        
        # 获取最老待处理任务的年龄
        oldest_pending = await scheduler.get_oldest_pending_age()
        if oldest_pending is not None:
            retest_queue_age_seconds.observe(oldest_pending)
        
        # 计算去重率
        total_requests = stats.get('total_requests', 0)
        unique_requests = stats.get('unique_requests', 0)
        if total_requests > 0:
            dedup_rate = 1.0 - (unique_requests / total_requests)
            retest_deduplication_rate.labels(window='24h').set(dedup_rate)
    
    except Exception as e:
        logger.error(f"Failed to update queue metrics: {e}")

logger.info("✅ Prometheus metrics initialized")

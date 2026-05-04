"""
Layer 2 Signal Collector Framework - Issue #96
采集 5 种信号源的统一框架：
1. rag_feedback - 用户反馈
2. failure signals - 失败日志
3. repeat_questions - 重复问题
4. contract_violations - 合约违规
5. topology_anomalies - 拓扑异常
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from enum import Enum

import psycopg2
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)


class AnomalyType(str, Enum):
    """拓扑异常类型"""
    STALE = "stale"  # 超过7天未更新的死边
    SPIKE = "spike"  # 流量突增的陷阱边


# ─── 信号数据类 ─────────────────────────────────────────────────────
@dataclass
class FeedbackSignal:
    """用户反馈信号"""
    session_id: str
    message_id: str
    rating: int  # 1-5
    tags: List[str] = field(default_factory=list)
    feedback_text: str = ""
    ts: float = 0.0  # Unix timestamp (seconds)
    overall_score: float = 0.0  # For compatibility with problem_detector
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FailureSignal:
    """失败日志信号"""
    session_id: str
    turn_index: int
    status: str  # 'error'
    latency_ms: int
    context: Dict[str, Any] = field(default_factory=dict)
    ts: float = 0.0


@dataclass
class RepeatQuestionSignal:
    """重复问题信号"""
    session_id: str
    repeat_count: int
    original_turn: int
    latest_turn: int
    similarity: float
    ts: float = 0.0


@dataclass
class ViolationSignal:
    """合约违规信号"""
    run_id: str
    contract_name: str
    violation_code: str
    payload: Dict[str, Any] = field(default_factory=dict)
    ts: float = 0.0


@dataclass
class TopoAnomalySignal:
    """拓扑异常信号"""
    edge_id: str
    from_node: str
    to_node: str
    anomaly_type: str  # 'stale' | 'spike'
    last_traversed_at: str
    traversal_count: int
    ts: float = 0.0


@dataclass
class AggregatedSignals:
    """聚合后的信号对象"""
    timestamp: float  # 本次采集时间
    feedback_signals: List[FeedbackSignal] = field(default_factory=list)
    failure_signals: List[FailureSignal] = field(default_factory=list)
    repeat_signals: List[RepeatQuestionSignal] = field(default_factory=list)
    violation_signals: List[ViolationSignal] = field(default_factory=list)
    topo_signals: List[TopoAnomalySignal] = field(default_factory=list)
    
    # 耗时统计
    collect_times: Dict[str, float] = field(default_factory=dict)  # {type: ms}
    total_collect_time_ms: float = 0.0
    
    @property
    def total_count(self) -> int:
        """信号总数"""
        return (len(self.feedback_signals) + len(self.failure_signals) + 
                len(self.repeat_signals) + len(self.violation_signals) + 
                len(self.topo_signals))
    
    @property
    def severity_score(self) -> float:
        """计算整体严重度分值（0-100）"""
        # 权重：失败最严重，合约违规次之，反馈/重复/拓扑异常相对较轻
        score = 0.0
        score += len(self.failure_signals) * 20  # 失败最严重
        score += len(self.violation_signals) * 15  # 合约违规
        score += len(self.repeat_signals) * 5  # 重复问题
        score += len(self.topo_signals) * 8  # 拓扑异常
        
        # 负反馈（rating <= 2）加分
        negative_feedback = sum(1 for s in self.feedback_signals if s.rating <= 2)
        score += negative_feedback * 3
        
        return min(100.0, score)  # Cap at 100


# ─── SignalCollector 类 ──────────────────────────────────────────────
class SignalCollector:
    """统一信号采集器"""
    
    def __init__(self, pool: Optional[ThreadedConnectionPool] = None):
        """
        初始化信号采集器
        
        Args:
            pool: PostgreSQL 连接池。如果不提供，使用内部创建的池
        """
        self.pool = pool
        self._owns_pool = False
        if not self.pool:
            self._init_pool()
            self._owns_pool = True
    
    def _init_pool(self):
        """初始化 PostgreSQL 连接池"""
        try:
            import os
            dsn = (
                f"host={os.getenv('POSTGRES_HOST', 'localhost')} "
                f"port={os.getenv('POSTGRES_PORT', '5432')} "
                f"dbname={os.getenv('POSTGRES_DB', 'rag_db')} "
                f"user={os.getenv('POSTGRES_USER', 'rag_user')} "
                f"password={os.getenv('POSTGRES_PASSWORD', '')}"
            )
            self.pool = ThreadedConnectionPool(minconn=1, maxconn=5, dsn=dsn)
            conn = self.pool.getconn()
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            self.pool.putconn(conn)
            logger.info("✅ SignalCollector: PostgreSQL pool initialized")
        except Exception as e:
            logger.error(f"❌ SignalCollector: Failed to init pool: {e}")
            self.pool = None
    
    def close(self):
        """关闭连接池"""
        if self.pool and self._owns_pool:
            try:
                self.pool.closeall()
                logger.info("✅ SignalCollector pool closed")
            except Exception as e:
                logger.warning(f"Error closing pool: {e}")
    
    async def collect_feedback_signals(self, limit: int = 100) -> List[FeedbackSignal]:
        """
        从 rag_feedback 表采集反馈信号
        
        Args:
            limit: 最大返回条数
            
        Returns:
            FeedbackSignal 列表
        """
        if not self.pool:
            logger.warning("SignalCollector: pool not available, returning empty")
            return []
        
        signals = []
        try:
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cur:
                    # 采集最近的反馈，并去重（同一 message_id 保留最新的）
                    cur.execute("""
                        SELECT DISTINCT ON (message_id)
                            session_id, message_id, rating, tags,
                            COALESCE(praise || ' ' || criticism || ' ' || suggestion, '') as feedback_text,
                            ts
                        FROM rag_feedback
                        ORDER BY message_id, ts DESC
                        LIMIT %s
                    """, (limit,))
                    
                    rows = cur.fetchall()
                    for row in rows:
                        try:
                            session_id, message_id, rating, tags, feedback_text, ts = row
                            tags_list = tags if isinstance(tags, list) else (tags.split(',') if tags else [])
                            signals.append(FeedbackSignal(
                                session_id=session_id or "",
                                message_id=message_id or "",
                                rating=rating or 0,
                                tags=tags_list,
                                feedback_text=(feedback_text or "").strip(),
                                ts=float(ts) if ts else 0.0
                            ))
                        except Exception as e:
                            logger.warning(f"Error processing feedback row: {e}")
                            continue
                    
                    logger.info(f"✅ Collected {len(signals)} feedback signals")
            finally:
                self.pool.putconn(conn)
        except Exception as e:
            logger.error(f"❌ Error collecting feedback signals: {e}")
        
        return signals
    
    async def collect_failure_signals(self, window_hours: int = 24, 
                                     latency_threshold_ms: int = 5000) -> List[FailureSignal]:
        """
        从 conversation_turns 表采集失败信号
        
        Args:
            window_hours: 时间窗口（小时）
            latency_threshold_ms: 延迟阈值（毫秒）
            
        Returns:
            FailureSignal 列表
        """
        if not self.pool:
            logger.warning("SignalCollector: pool not available, returning empty")
            return []
        
        signals = []
        try:
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cur:
                    # 采集失败的 turn（status='error'）或高延迟的 turn
                    # ts 是 double precision (Unix timestamp), 所以不能直接用 NOW()
                    cur.execute("""
                        SELECT 
                            session_id, turn_index, status, latency_ms,
                            jsonb_build_object(
                                'user_query', user_content,
                                'response_excerpt', SUBSTRING(assistant_content, 1, 200),
                                'source', source
                            ) as context,
                            ts
                        FROM conversation_turns
                        WHERE (status = 'error' OR latency_ms > %s)
                          AND ts > (EXTRACT(EPOCH FROM NOW()) - %s * 3600)
                        ORDER BY ts DESC
                        LIMIT 100
                    """, (latency_threshold_ms, window_hours))
                    
                    rows = cur.fetchall()
                    for row in rows:
                        try:
                            session_id, turn_index, status, latency_ms, context, ts = row
                            signals.append(FailureSignal(
                                session_id=session_id or "",
                                turn_index=turn_index or 0,
                                status=status or "unknown",
                                latency_ms=latency_ms or 0,
                                context=context or {},
                                ts=float(ts) if ts else 0.0
                            ))
                        except Exception as e:
                            logger.warning(f"Error processing failure row: {e}")
                            continue
                    
                    logger.info(f"✅ Collected {len(signals)} failure signals")
            finally:
                self.pool.putconn(conn)
        except Exception as e:
            logger.error(f"❌ Error collecting failure signals: {e}")
        
        return signals
    
    async def collect_repeat_questions(self, threshold: float = 0.8) -> List[RepeatQuestionSignal]:
        """
        从 signal_repeat_question 表采集重复问题信号
        
        Args:
            threshold: 相似度阈值
            
        Returns:
            RepeatQuestionSignal 列表
        """
        if not self.pool:
            logger.warning("SignalCollector: pool not available, returning empty")
            return []
        
        signals = []
        try:
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cur:
                    # 检查表是否存在
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables 
                            WHERE table_name = 'signal_repeat_question'
                        )
                    """)
                    table_exists = cur.fetchone()[0]
                    
                    if not table_exists:
                        logger.info("⚠️ signal_repeat_question table not found, skipping")
                        return signals
                    
                    # 采集重复问题（注意：repeat_turn 不是 latest_turn）
                    cur.execute("""
                        SELECT 
                            session_id, 1 as repeat_count, original_turn, repeat_turn,
                            similarity, EXTRACT(EPOCH FROM ts) as ts
                        FROM signal_repeat_question
                        WHERE similarity > %s
                        ORDER BY ts DESC
                        LIMIT 100
                    """, (threshold,))
                    
                    rows = cur.fetchall()
                    for row in rows:
                        try:
                            session_id, repeat_count, original_turn, repeat_turn, similarity, ts = row
                            signals.append(RepeatQuestionSignal(
                                session_id=session_id or "",
                                repeat_count=repeat_count or 1,
                                original_turn=original_turn or 0,
                                latest_turn=repeat_turn or 0,
                                similarity=float(similarity) if similarity else 0.0,
                                ts=float(ts) if ts else 0.0
                            ))
                        except Exception as e:
                            logger.warning(f"Error processing repeat question row: {e}")
                            continue
                    
                    logger.info(f"✅ Collected {len(signals)} repeat question signals")
            finally:
                self.pool.putconn(conn)
        except Exception as e:
            logger.error(f"❌ Error collecting repeat questions: {e}")
        
        return signals
    
    async def collect_contract_violations(self) -> List[ViolationSignal]:
        """
        从 signal_contract_violation 表采集合约违规信号
        
        Returns:
            ViolationSignal 列表
        """
        if not self.pool:
            logger.warning("SignalCollector: pool not available, returning empty")
            return []
        
        signals = []
        try:
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cur:
                    # 检查表是否存在
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables 
                            WHERE table_name = 'signal_contract_violation'
                        )
                    """)
                    table_exists = cur.fetchone()[0]
                    
                    if not table_exists:
                        logger.info("⚠️ signal_contract_violation table not found, skipping")
                        return signals
                    
                    # 采集所有未处理的违规
                    cur.execute("""
                        SELECT 
                            run_id, contract_name, violation_code,
                            payload, EXTRACT(EPOCH FROM ts) as ts
                        FROM signal_contract_violation
                        ORDER BY ts DESC
                        LIMIT 100
                    """)
                    
                    rows = cur.fetchall()
                    for row in rows:
                        try:
                            run_id, contract_name, violation_code, payload, ts = row
                            signals.append(ViolationSignal(
                                run_id=run_id or "",
                                contract_name=contract_name or "",
                                violation_code=violation_code or "",
                                payload=payload or {},
                                ts=float(ts) if ts else 0.0
                            ))
                        except Exception as e:
                            logger.warning(f"Error processing violation row: {e}")
                            continue
                    
                    logger.info(f"✅ Collected {len(signals)} violation signals")
            finally:
                self.pool.putconn(conn)
        except Exception as e:
            logger.error(f"❌ Error collecting contract violations: {e}")
        
        return signals
    
    async def collect_topology_anomalies(self, stale_days: int = 7,
                                        spike_threshold: int = 1000) -> List[TopoAnomalySignal]:
        """
        检测拓扑异常（死边、流量突增）
        
        Args:
            stale_days: 超过 N 天未更新的边为死边
            spike_threshold: 单日遍历超过 N 次为流量突增
            
        Returns:
            TopoAnomalySignal 列表
        """
        if not self.pool:
            logger.warning("SignalCollector: pool not available, returning empty")
            return []
        
        signals = []
        try:
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cur:
                    # 检查表是否存在
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables 
                            WHERE table_name = 'topology_edge_log'
                        )
                    """)
                    table_exists = cur.fetchone()[0]
                    
                    if not table_exists:
                        logger.info("⚠️ topology_edge_log table not found, skipping")
                        return signals
                    
                    # 规则1：超过 stale_days 天未更新的边
                    cur.execute("""
                        SELECT 
                            edge_id, from_node, to_node,
                            last_traversed_at, traversal_count
                        FROM topology_edge_log
                        WHERE last_traversed_at < NOW() - INTERVAL '%s days'
                        LIMIT 100
                    """, (stale_days,))
                    
                    rows = cur.fetchall()
                    for row in rows:
                        try:
                            edge_id, from_node, to_node, last_traversed_at, traversal_count = row
                            signals.append(TopoAnomalySignal(
                                edge_id=edge_id or "",
                                from_node=from_node or "",
                                to_node=to_node or "",
                                anomaly_type=AnomalyType.STALE.value,
                                last_traversed_at=str(last_traversed_at) if last_traversed_at else "",
                                traversal_count=traversal_count or 0,
                                ts=time.time()
                            ))
                        except Exception as e:
                            logger.warning(f"Error processing stale edge: {e}")
                            continue
                    
                    # 规则2：单日遍历数突增的边（假设超过阈值）
                    cur.execute("""
                        SELECT 
                            edge_id, from_node, to_node,
                            last_traversed_at, traversal_count
                        FROM topology_edge_log
                        WHERE traversal_count > %s
                        ORDER BY traversal_count DESC
                        LIMIT 50
                    """, (spike_threshold,))
                    
                    rows = cur.fetchall()
                    for row in rows:
                        try:
                            edge_id, from_node, to_node, last_traversed_at, traversal_count = row
                            signals.append(TopoAnomalySignal(
                                edge_id=edge_id or "",
                                from_node=from_node or "",
                                to_node=to_node or "",
                                anomaly_type=AnomalyType.SPIKE.value,
                                last_traversed_at=str(last_traversed_at) if last_traversed_at else "",
                                traversal_count=traversal_count or 0,
                                ts=time.time()
                            ))
                        except Exception as e:
                            logger.warning(f"Error processing spike edge: {e}")
                            continue
                    
                    logger.info(f"✅ Collected {len(signals)} topology anomaly signals")
            finally:
                self.pool.putconn(conn)
        except Exception as e:
            logger.error(f"❌ Error collecting topology anomalies: {e}")
        
        return signals
    
    async def aggregate_all(self) -> AggregatedSignals:
        """
        一次性采集所有信号，返回汇总对象
        并发执行所有采集任务以优化性能
        
        Returns:
            AggregatedSignals 对象
        """
        start_time = time.time()
        aggregated = AggregatedSignals(timestamp=start_time)
        
        try:
            # 并发执行所有采集任务
            tasks = [
                self._timed_collect("feedback", self.collect_feedback_signals()),
                self._timed_collect("failure", self.collect_failure_signals()),
                self._timed_collect("repeat_questions", self.collect_repeat_questions()),
                self._timed_collect("contract_violations", self.collect_contract_violations()),
                self._timed_collect("topology_anomalies", self.collect_topology_anomalies()),
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            for i, (signal_type, result) in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Error in {signal_type}: {result}")
                    continue
                
                signals, duration_ms = result
                aggregated.collect_times[signal_type] = duration_ms
                
                if signal_type == "feedback":
                    aggregated.feedback_signals = signals
                elif signal_type == "failure":
                    aggregated.failure_signals = signals
                elif signal_type == "repeat_questions":
                    aggregated.repeat_signals = signals
                elif signal_type == "contract_violations":
                    aggregated.violation_signals = signals
                elif signal_type == "topology_anomalies":
                    aggregated.topo_signals = signals
        
        except Exception as e:
            logger.error(f"❌ Error in aggregate_all: {e}")
        
        finally:
            aggregated.total_collect_time_ms = (time.time() - start_time) * 1000
            logger.info(
                f"📊 Signal collection complete: "
                f"total={aggregated.total_count}, "
                f"severity={aggregated.severity_score:.1f}, "
                f"duration={aggregated.total_collect_time_ms:.1f}ms"
            )
        
        return aggregated
    
    async def _timed_collect(self, signal_type: str, coro) -> tuple:
        """
        为采集任务计时的辅助方法
        
        Args:
            signal_type: 信号类型标识
            coro: 协程
            
        Returns:
            (signals, duration_ms) 元组
        """
        start = time.time()
        signals = await coro
        duration_ms = (time.time() - start) * 1000
        return signal_type, (signals, duration_ms)


# ─── 导出辅助函数 ────────────────────────────────────────────────────
async def get_latest_signals(pool: Optional[ThreadedConnectionPool] = None) -> AggregatedSignals:
    """
    对外 API：获取最新的聚合信号
    
    Args:
        pool: PostgreSQL 连接池（可选）
        
    Returns:
        AggregatedSignals 对象
    """
    collector = SignalCollector(pool)
    try:
        signals = await collector.aggregate_all()
        return signals
    finally:
        if not pool:  # 如果没有提供池，则关闭内部创建的池
            collector.close()


# ─── 快速测试 ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    
    async def main():
        collector = SignalCollector()
        try:
            signals = await collector.aggregate_all()
            print(f"\n{'='*60}")
            print(f"🔍 Signal Collection Report")
            print(f"{'='*60}")
            print(f"Timestamp: {datetime.fromtimestamp(signals.timestamp).isoformat()}")
            print(f"Total Signals: {signals.total_count}")
            print(f"Severity Score: {signals.severity_score:.1f}/100")
            print(f"Total Collection Time: {signals.total_collect_time_ms:.1f}ms")
            print(f"\n📈 Signal Breakdown:")
            print(f"  - Feedback: {len(signals.feedback_signals)}")
            print(f"  - Failures: {len(signals.failure_signals)}")
            print(f"  - Repeat Questions: {len(signals.repeat_signals)}")
            print(f"  - Contract Violations: {len(signals.violation_signals)}")
            print(f"  - Topology Anomalies: {len(signals.topo_signals)}")
            print(f"\n⏱️  Collection Times by Type:")
            for signal_type, duration_ms in signals.collect_times.items():
                print(f"  - {signal_type}: {duration_ms:.1f}ms")
            print(f"{'='*60}\n")
        finally:
            collector.close()
    
    asyncio.run(main())

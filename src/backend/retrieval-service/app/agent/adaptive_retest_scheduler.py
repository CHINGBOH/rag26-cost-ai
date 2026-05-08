"""
Adaptive Retest Scheduler (Async Version)

Issue: #117 - Learning Ghost Triggers
Purpose: 统一调度 Learning 系统的重测请求，解决多个触发源竞争问题
Author: AI Agent
Date: 2026-05-08
Sprint: Phase 1+ Task 3

核心功能：
1. 请求去重：基于 question_hash 防止重复调度
2. 优先级队列：高优先级请求优先执行
3. 指数退避：失败后延迟重试 (5min, 15min, 1hr, 4hr, 24hr)
4. 持久化：使用 PostgreSQL 存储队列状态
5. 并发控制：限制同时执行的重测任务数
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


def _normalize_question(question: str) -> str:
    """规范化问题文本：去除首尾空格、折叠空白、转小写（用于去重哈希）。"""
    return " ".join(question.lower().strip().split())

# =====================================================
# Constants
# =====================================================

# 退避策略：重试次数 → 延迟时间（秒）
BACKOFF_SCHEDULE = [
    5 * 60,       # 0: 5 minutes
    15 * 60,      # 1: 15 minutes
    60 * 60,      # 2: 1 hour
    4 * 60 * 60,  # 3: 4 hours
    24 * 60 * 60  # 4+: 24 hours (max)
]


# =====================================================
# Enums
# =====================================================


class RetestPriority(IntEnum):
    """重测优先级（数字越大优先级越高）"""
    TIMER = 5             # 定时触发（最低）
    PATCH = 6             # Gap Retest / 修复验证
    REPEATED_QUESTION = 7 # 重复失败问题
    USER_FEEDBACK = 8     # 用户反馈触发
    MANUAL = 10           # 手动触发（最高）
    
    # Backward compatibility
    FOLLOWUP = 6          # Alias for PATCH
    FEEDBACK = 8          # Alias for USER_FEEDBACK


class RetestStatus:
    """重测状态"""
    PENDING = "pending"       # 待执行
    SCHEDULED = "scheduled"   # 已调度（预留）
    RUNNING = "running"       # 执行中
    SUCCESS = "success"       # 成功
    FAILED = "failed"         # 失败
    CANCELLED = "cancelled"   # 已取消


# =====================================================
# Data Models
# =====================================================


@dataclass
class RetestRequest:
    """重测请求"""
    question: str                           # 问题文本
    source: str                             # 触发源 (timer, followup, feedback, etc.)
    priority: RetestPriority                # 优先级
    metadata: dict = field(default_factory=dict)  # 额外元数据
    question_hash: Optional[str] = None     # 问题哈希（去重）
    retry_count: int = 0                    # 当前重试次数
    next_retry_at: Optional[datetime] = None  # 下次重试时间


# =====================================================
# Scheduler
# =====================================================


class AdaptiveRetestScheduler:
    """
    自适应重测调度器（异步版本）
    
    使用 asyncpg 进行异步数据库操作
    """
    
    def __init__(self, db_pool, max_concurrent: int = 3):
        """
        Args:
            db_pool: asyncpg connection pool
            max_concurrent: 最大并发执行数
        """
        self.db_pool = db_pool
        self.max_concurrent = max_concurrent
    
    @staticmethod
    def _compute_question_hash(question: str) -> str:
        """计算问题哈希（用于去重）。规范化后取 SHA-256 前16位。"""
        normalized = _normalize_question(question)
        hash_full = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return hash_full[:16]
    
    async def request_retest(self, request: RetestRequest) -> str:
        """
        请求重测
        
        Args:
            request: 重测请求对象
        
        Returns:
            question_hash: 问题哈希值
        
        行为：
            - 如果已存在相同 question_hash 的待处理/进行中任务，则提升优先级
            - 否则创建新任务
        """
        # 计算问题哈希
        if not request.question_hash:
            request.question_hash = self._compute_question_hash(request.question)
        
        # 计算下次执行时间
        if request.next_retry_at is None:
            request.next_retry_at = datetime.now(timezone.utc)
        
        async with self.db_pool.acquire() as conn:
            # 检查是否已存在（fetchval: 返回 priority 值或 None）
            existing = await conn.fetchval(
                """
                SELECT priority
                FROM retest_queue
                WHERE question_hash = $1
                  AND status IN ($2, $3, $4)
                """,
                request.question_hash,
                RetestStatus.PENDING,
                RetestStatus.SCHEDULED,
                RetestStatus.RUNNING,
            )

            if existing is not None:
                # 已存在：使用 max 保留最高优先级，并刷新 updated_at
                # existing may be a scalar int (real DB) or a dict-like row (test mock)
                existing_priority = existing["priority"] if isinstance(existing, dict) else int(existing)
                new_priority = max(int(request.priority), int(existing_priority))
                await conn.execute(
                    """
                    UPDATE retest_queue
                    SET priority = $1, updated_at = NOW()
                    WHERE question_hash = $2 AND status IN ($3, $4, $5)
                    """,
                    new_priority,
                    request.question_hash,
                    RetestStatus.PENDING,
                    RetestStatus.SCHEDULED,
                    RetestStatus.RUNNING,
                )
                logger.info(
                    f"[AdaptiveScheduler] Duplicate merged: "
                    f"hash={request.question_hash[:8]}... priority={new_priority}"
                )
                return request.question_hash

            # 不存在：插入新任务
            await conn.execute(
                """
                INSERT INTO retest_queue (
                    question, question_hash, source, priority,
                    retry_count, next_retry_at, status, metadata, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                """,
                request.question,
                request.question_hash,
                request.source,
                int(request.priority),
                request.retry_count,
                request.next_retry_at,
                RetestStatus.PENDING,
                json.dumps(request.metadata),
            )

            logger.info(
                f"[AdaptiveScheduler] Retest queued: "
                f"hash={request.question_hash[:8]}... "
                f"source={request.source} priority={request.priority}"
            )

            return request.question_hash
    
    async def get_next_batch(self) -> List[RetestRequest]:
        """
        获取下一批待执行任务
        
        Returns:
            List[RetestRequest]: 待执行任务列表（最多 max_concurrent 个）
        
        排序规则：
            1. 优先级降序（高优先级优先）
            2. next_retry_at 升序（早到期的优先）
        """
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, question, question_hash, source, priority,
                       retry_count, next_retry_at, metadata
                FROM retest_queue
                WHERE status = $1
                  AND next_retry_at <= NOW()
                ORDER BY priority DESC, next_retry_at ASC
                LIMIT $2
                """,
                RetestStatus.PENDING,
                self.max_concurrent,
            )
            
            batch = []
            for row in rows[: self.max_concurrent]:  # enforce limit in Python too
                batch.append(RetestRequest(
                    question=row["question"],
                    source=row["source"],
                    priority=RetestPriority(row["priority"]),
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                    question_hash=row["question_hash"],
                    retry_count=row["retry_count"],
                    next_retry_at=row["next_retry_at"],
                ))

            return batch
    
    async def mark_success(self, question_hash: str, result_summary: Optional[Dict[str, Any]] = None):
        """
        标记任务成功

        Args:
            question_hash: 问题哈希值
            result_summary: 执行结果摘要
        """
        async with self.db_pool.acquire() as conn:
            # 先写历史日志（可选），再 UPDATE 队列状态
            if result_summary:
                await conn.execute(
                    """
                    INSERT INTO retest_history (
                        question_hash, status, result_summary, created_at
                    ) VALUES ($1, $2, $3, NOW())
                    """,
                    question_hash,
                    RetestStatus.SUCCESS,
                    json.dumps(result_summary),
                )

            await conn.execute(
                """
                UPDATE retest_queue
                SET status = $1, completed_at = NOW(), updated_at = NOW()
                WHERE question_hash = $2 AND status = $3
                """,
                RetestStatus.SUCCESS,
                question_hash,
                RetestStatus.RUNNING,
            )

            logger.info(f"[AdaptiveScheduler] Task success: hash={question_hash[:8]}...")
    
    async def mark_failure(self, question_hash: str, error_message: str):
        """
        标记任务失败并应用指数退避
        
        Args:
            question_hash: 问题哈希值
            error_message: 错误信息
        """
        async with self.db_pool.acquire() as conn:
            # 获取当前重试次数（fetchval: 返回标量或 None）
            retry_count = await conn.fetchval(
                "SELECT retry_count FROM retest_queue WHERE question_hash = $1",
                question_hash,
            )

            if retry_count is None:
                logger.warning(f"[AdaptiveScheduler] Task not found: {question_hash}")
                return

            new_retry_count = int(retry_count) + 1
            
            # 计算退避延迟
            backoff_index = min(retry_count, len(BACKOFF_SCHEDULE) - 1)
            delay_seconds = BACKOFF_SCHEDULE[backoff_index]
            next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
            
            # 更新队列
            await conn.execute(
                """
                UPDATE retest_queue
                SET retry_count = $1,
                    next_retry_at = $2,
                    status = $3,
                    last_error = $4,
                    updated_at = NOW()
                WHERE question_hash = $5
                """,
                new_retry_count,
                next_retry_at,
                RetestStatus.PENDING,  # 重新排队
                error_message,
                question_hash,
            )
            
            # 写入历史日志
            await conn.fetchval(
                """
                INSERT INTO retest_history (
                    question_hash, status, retry_count, error_message, created_at
                ) VALUES ($1, $2, $3, $4, NOW())
                """,
                question_hash,
                RetestStatus.FAILED,
                new_retry_count,
                error_message,
            )
            
            logger.warning(
                f"[AdaptiveScheduler] Task failed (retry {new_retry_count}): "
                f"hash={question_hash[:8]}... next_retry={next_retry_at.isoformat()} "
                f"error={error_message[:100]}"
            )
    
    async def cancel(self, question_hash: str) -> bool:
        """
        取消任务
        
        Args:
            question_hash: 问题哈希值
        
        Returns:
            bool: 是否成功取消
        """
        async with self.db_pool.acquire() as conn:
            result = await conn.fetchval(
                """
                UPDATE retest_queue
                SET status = $1, updated_at = NOW()
                WHERE question_hash = $2
                  AND status IN ($3, $4)
                RETURNING id
                """,
                RetestStatus.CANCELLED,
                question_hash,
                RetestStatus.PENDING,
                RetestStatus.SCHEDULED,
            )
            
            if result:
                logger.info(f"[AdaptiveScheduler] Task cancelled: hash={question_hash[:8]}...")
                return True
            else:
                return False
    
    async def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            Dict: 统计数据
            - pending: 待执行任务数
            - running: 运行中任务数
            - success: 成功任务数
            - failed: 失败任务数
            - cancelled: 取消任务数
            - total: 总任务数
            - by_source: 按触发源分组统计
        """
        async with self.db_pool.acquire() as conn:
            # 按状态统计
            status_rows = await conn.fetch(
                """
                SELECT status, COUNT(*) as count
                FROM retest_queue
                GROUP BY status
                """
            )
            
            stats = {
                "pending": 0,
                "running": 0,
                "success": 0,
                "failed": 0,
                "cancelled": 0,
                "total": 0,
                "by_source": {},
            }
            
            for row in status_rows:
                status = row["status"]
                count = row["count"]
                stats[status] = count
                stats["total"] += count
            
            # 按触发源统计
            source_rows = await conn.fetch(
                """
                SELECT source, COUNT(*) as count
                FROM retest_queue
                GROUP BY source
                """
            )
            
            for row in source_rows:
                stats["by_source"][row["source"]] = row["count"]
            
            return stats
    
    async def get_queue_stats(self) -> Dict[str, Any]:
        """
        获取队列统计信息 (用于 Prometheus metrics)
        
        Returns:
            {
                'by_status': {'pending': n, 'running': n, ...},
                'total_requests': n,
                'unique_requests': n
            }
        """
        if not self.db_pool:
            return {
                "by_status": {},
                "total_requests": 0,
                "unique_requests": 0
            }
        
        async with self.db_pool.acquire() as conn:
            # 按状态统计
            status_rows = await conn.fetch(
                """
                SELECT status, COUNT(*) as count
                FROM retest_queue
                GROUP BY status
                """
            )
            
            by_status = {}
            total = 0
            for row in status_rows:
                count = row["count"]
                by_status[row["status"]] = count
                total += count
            
            # 统计唯一请求数 (通过 question_hash 去重)
            unique_count_row = await conn.fetchrow(
                """
                SELECT COUNT(DISTINCT question_hash) as unique_count
                FROM retest_queue
                """
            )
            
            unique_count = unique_count_row["unique_count"] if unique_count_row else 0
            
            return {
                "by_status": by_status,
                "total_requests": total,
                "unique_requests": unique_count
            }
    
    async def get_oldest_pending_age(self) -> Optional[float]:
        """
        获取最老待处理任务的年龄（秒）(用于 Prometheus metrics)
        
        Returns:
            float: 最老待处理任务的年龄（秒），如果没有待处理任务则返回 None
        """
        if not self.db_pool:
            return None
        
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT MIN(created_at) as oldest_created_at
                FROM retest_queue
                WHERE status = 'pending'
                """
            )
            
            if row and row["oldest_created_at"]:
                from datetime import datetime, timezone
                oldest = row["oldest_created_at"]
                now = datetime.now(timezone.utc)
                
                # 如果 oldest 是 naive datetime，添加 UTC timezone
                if oldest.tzinfo is None:
                    oldest = oldest.replace(tzinfo=timezone.utc)
                
                age_seconds = (now - oldest).total_seconds()
                return age_seconds
            
            return None

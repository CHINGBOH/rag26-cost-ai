"""
Adaptive Retest Scheduler - REST API

Issue: #117
Purpose: 提供 HTTP 接口查询和管理 AdaptiveRetestScheduler
Author: AI Agent
Date: 2026-05-08
"""

import sys
from pathlib import Path

# Bootstrap: 确保能导入项目模块
project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

from app.agent.adaptive_retest_scheduler import (
    AdaptiveRetestScheduler,
    RetestRequest,
    RetestPriority,
    RetestStatus,
)

logger = logging.getLogger(__name__)

# =====================================================
# API Router
# =====================================================

router = APIRouter(prefix="/api/v1/adaptive-retest", tags=["Adaptive Retest Scheduler"])

# Global scheduler instance (will be injected by main.py)
_scheduler: Optional[AdaptiveRetestScheduler] = None


def set_scheduler(scheduler: AdaptiveRetestScheduler):
    """由 main.py 注入调度器实例"""
    global _scheduler
    _scheduler = scheduler


def get_scheduler() -> AdaptiveRetestScheduler:
    """获取调度器实例"""
    if _scheduler is None:
        raise HTTPException(
            status_code=503, detail="Adaptive Retest Scheduler not initialized"
        )
    return _scheduler


# =====================================================
# Request/Response Models
# =====================================================


class RetestRequestInput(BaseModel):
    """重测请求输入"""

    question: str = Field(..., description="问题文本")
    source: str = Field(
        ..., description="触发源: timer, followup, feedback, repeated, contract, manual, patch"
    )
    priority: Optional[int] = Field(
        None, description="优先级 (1-10)，不填则根据 source 自动推断"
    )
    metadata: Optional[Dict[str, Any]] = Field(None, description="元数据")


class RetestRequestResponse(BaseModel):
    """重测请求响应"""

    question_hash: str
    status: str
    message: str


class QueueItemResponse(BaseModel):
    """队列项响应"""

    id: int
    question: str
    question_hash: str
    source: str
    priority: int
    retry_count: int
    next_retry_at: datetime
    status: str
    last_error: Optional[str]
    created_at: datetime
    updated_at: datetime


class StatsResponse(BaseModel):
    """统计信息响应"""

    pending: int
    running: int
    success: int
    failed: int
    cancelled: int
    total: int
    by_source: Dict[str, int]


# =====================================================
# API Endpoints
# =====================================================


@router.post("/request", response_model=RetestRequestResponse)
async def request_retest(req: RetestRequestInput):
    """
    请求重测

    **Parameters**:
    - question: 问题文本
    - source: 触发源 (timer, followup, feedback, repeated, contract, manual, patch)
    - priority: 优先级 (可选，不填则自动推断)
    - metadata: 元数据 (可选)

    **Returns**:
    - question_hash: 问题哈希值
    - status: new / deduplicated
    - message: 描述信息
    """
    scheduler = get_scheduler()

    # 推断优先级
    if req.priority is None:
        priority_map = {
            "manual": RetestPriority.MANUAL,
            "feedback": RetestPriority.FEEDBACK,
            "repeated": RetestPriority.REPEATED_QUESTION,
            "followup": RetestPriority.FOLLOWUP,
            "timer": RetestPriority.TIMER,
            "contract": RetestPriority.REPEATED_QUESTION,
            "patch": RetestPriority.REPEATED_QUESTION,
        }
        priority = priority_map.get(req.source, RetestPriority.TIMER)
    else:
        priority = req.priority

    try:
        # 创建请求
        retest_req = RetestRequest(
            question=req.question,
            source=req.source,
            priority=priority,
            metadata=req.metadata or {},
        )

        # 提交到调度器
        question_hash = await scheduler.request_retest(retest_req)

        return RetestRequestResponse(
            question_hash=question_hash,
            status="new",
            message=f"Retest request queued with priority {priority}",
        )

    except Exception as e:
        logger.error(f"Failed to request retest: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", response_model=StatsResponse)
async def get_stats():
    """
    获取统计信息

    **Returns**:
    - pending: 待执行任务数
    - running: 运行中任务数
    - success: 成功任务数
    - failed: 失败任务数
    - cancelled: 取消任务数
    - total: 总任务数
    - by_source: 按触发源分组统计
    """
    scheduler = get_scheduler()

    try:
        stats = await scheduler.get_stats()
        return StatsResponse(**stats)
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue", response_model=List[QueueItemResponse])
async def get_queue(
    status: Optional[str] = Query(None, description="过滤状态: pending, running, failed"),
    source: Optional[str] = Query(None, description="过滤触发源"),
    limit: int = Query(50, ge=1, le=500, description="返回数量"),
):
    """
    获取队列列表

    **Parameters**:
    - status: 过滤状态 (可选)
    - source: 过滤触发源 (可选)
    - limit: 返回数量 (默认50)

    **Returns**: 队列项列表
    """
    scheduler = get_scheduler()

    try:
        # 构造查询
        where_clauses = []
        if status:
            where_clauses.append(f"status = '{status}'")
        if source:
            where_clauses.append(f"source = '{source}'")

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        query = f"""
            SELECT id, question, question_hash, source, priority, retry_count,
                   next_retry_at, status, last_error, created_at, updated_at
            FROM retest_queue
            WHERE {where_sql}
            ORDER BY priority DESC, next_retry_at ASC
            LIMIT {limit}
        """

        async with scheduler.db_pool.acquire() as conn:
            rows = await conn.fetch(query)

        results = [
            QueueItemResponse(
                id=row["id"],
                question=row["question"],
                question_hash=row["question_hash"],
                source=row["source"],
                priority=row["priority"],
                retry_count=row["retry_count"],
                next_retry_at=row["next_retry_at"],
                status=row["status"],
                last_error=row["last_error"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

        return results

    except Exception as e:
        logger.error(f"Failed to get queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{question_hash}")
async def cancel_retest(question_hash: str):
    """
    取消重测任务

    **Parameters**:
    - question_hash: 问题哈希值

    **Returns**: 操作结果
    """
    scheduler = get_scheduler()

    try:
        cancelled = await scheduler.cancel(question_hash)

        if cancelled:
            return {"message": f"Retest for {question_hash} cancelled"}
        else:
            raise HTTPException(
                status_code=404, detail=f"Retest task {question_hash} not found"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel retest: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{question_hash}/retry")
async def retry_retest(question_hash: str):
    """
    立即重试任务（重置退避计数器）

    **Parameters**:
    - question_hash: 问题哈希值

    **Returns**: 操作结果
    """
    scheduler = get_scheduler()

    try:
        async with scheduler.db_pool.acquire() as conn:
            # 检查任务是否存在
            row = await conn.fetchrow(
                "SELECT id, status FROM retest_queue WHERE question_hash = $1",
                question_hash,
            )

            if not row:
                raise HTTPException(
                    status_code=404, detail=f"Retest task {question_hash} not found"
                )

            # 重置为 pending 并立即调度
            await conn.execute(
                """
                UPDATE retest_queue
                SET status = $1, retry_count = 0, next_retry_at = NOW(), updated_at = NOW()
                WHERE question_hash = $2
                """,
                RetestStatus.PENDING,
                question_hash,
            )

        return {"message": f"Retest for {question_hash} scheduled for immediate retry"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retry retest: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# Health Check
# =====================================================


@router.get("/health")
async def health_check():
    """健康检查"""
    scheduler = get_scheduler()

    try:
        # 测试数据库连接
        async with scheduler.db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")

        return {
            "status": "healthy",
            "scheduler": "initialized",
            "database": "connected",
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "scheduler": "initialized" if _scheduler else "not_initialized",
            "database": "disconnected",
            "error": str(e),
        }

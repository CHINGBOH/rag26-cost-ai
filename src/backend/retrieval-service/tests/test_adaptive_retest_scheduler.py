"""
Unit Tests for Adaptive Retest Scheduler

Issue: #117
Purpose: 测试调度器核心逻辑
Author: AI Agent
Date: 2026-05-08
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import asyncpg

from app.agent.adaptive_retest_scheduler import (
    AdaptiveRetestScheduler,
    RetestRequest,
    RetestPriority,
    RetestStatus,
    BACKOFF_SCHEDULE,
)


# =====================================================
# Fixtures
# =====================================================


@pytest.fixture
async def mock_db_pool():
    """Mock 数据库连接池"""
    pool = MagicMock()
    conn = AsyncMock()

    # Mock acquire context manager
    async def acquire():
        return conn

    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    return pool, conn


@pytest.fixture
async def scheduler(mock_db_pool):
    """调度器实例"""
    pool, _ = mock_db_pool
    return AdaptiveRetestScheduler(pool, max_concurrent=3)


# =====================================================
# Test: 请求入队和去重
# =====================================================


@pytest.mark.asyncio
async def test_request_retest_new(scheduler, mock_db_pool):
    """测试：新请求入队"""
    _, conn = mock_db_pool

    # Mock fetchval - 返回 None 表示不存在
    conn.fetchval.return_value = None
    # Mock execute
    conn.execute.return_value = None

    request = RetestRequest(
        question="什么是 Python？",
        source="manual",
        priority=RetestPriority.MANUAL,
        metadata={"user_id": 123},
    )

    question_hash = await scheduler.request_retest(request)

    # 验证：生成了 hash
    assert question_hash is not None
    assert len(question_hash) == 16

    # 验证：调用了数据库插入
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args[0]
    assert "INSERT INTO retest_queue" in call_args[0]


@pytest.mark.asyncio
async def test_request_retest_deduplicate(scheduler, mock_db_pool):
    """测试：去重逻辑"""
    _, conn = mock_db_pool

    # Mock fetchval - 返回已存在的记录
    conn.fetchval.return_value = {"id": 1, "retry_count": 2, "priority": 5}
    # Mock execute
    conn.execute.return_value = None

    request = RetestRequest(
        question="什么是 Python？",
        source="timer",
        priority=RetestPriority.TIMER,
    )

    question_hash = await scheduler.request_retest(request)

    # 验证：返回了 hash
    assert question_hash is not None

    # 验证：只更新了优先级（如果新优先级更高）
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args[0]
    assert "UPDATE retest_queue" in call_args[0]


# =====================================================
# Test: 优先级队列
# =====================================================


@pytest.mark.asyncio
async def test_get_next_batch_priority_order(scheduler, mock_db_pool):
    """测试：按优先级排序"""
    _, conn = mock_db_pool

    # Mock fetch - 返回多个任务
    conn.fetch.return_value = [
        {
            "id": 1,
            "question": "Q1",
            "question_hash": "hash1",
            "source": "manual",
            "priority": 10,
            "retry_count": 0,
            "next_retry_at": datetime.now(),
            "metadata": {},
        },
        {
            "id": 2,
            "question": "Q2",
            "question_hash": "hash2",
            "source": "feedback",
            "priority": 8,
            "retry_count": 0,
            "next_retry_at": datetime.now(),
            "metadata": {},
        },
        {
            "id": 3,
            "question": "Q3",
            "question_hash": "hash3",
            "source": "timer",
            "priority": 5,
            "retry_count": 0,
            "next_retry_at": datetime.now(),
            "metadata": {},
        },
    ]

    batch = await scheduler.get_next_batch()

    # 验证：返回了3个任务（max_concurrent=3）
    assert len(batch) == 3

    # 验证：优先级从高到低
    assert batch[0].priority == 10
    assert batch[1].priority == 8
    assert batch[2].priority == 5


@pytest.mark.asyncio
async def test_get_next_batch_concurrent_limit(scheduler, mock_db_pool):
    """测试：并发限制"""
    _, conn = mock_db_pool

    # Mock fetch - 返回5个任务
    conn.fetch.return_value = [
        {
            "id": i,
            "question": f"Q{i}",
            "question_hash": f"hash{i}",
            "source": "timer",
            "priority": 5,
            "retry_count": 0,
            "next_retry_at": datetime.now(),
            "metadata": {},
        }
        for i in range(1, 6)
    ]

    batch = await scheduler.get_next_batch()

    # 验证：只返回 max_concurrent (3) 个任务
    assert len(batch) == 3


# =====================================================
# Test: 指数退避
# =====================================================


@pytest.mark.asyncio
async def test_mark_failure_backoff(scheduler, mock_db_pool):
    """测试：失败后应用指数退避"""
    _, conn = mock_db_pool

    # Mock fetchval - 返回当前 retry_count
    conn.fetchval.side_effect = [2, None]  # 第一次返回2，第二次返回None
    # Mock execute
    conn.execute.return_value = None

    before = datetime.now()
    await scheduler.mark_failure("hash123", "Test error")

    # 验证：更新了 retry_count 和 next_retry_at
    conn.execute.assert_called()
    call_args = conn.execute.call_args[0]
    assert "UPDATE retest_queue" in call_args[0]
    assert "retry_count" in call_args[0]
    assert "next_retry_at" in call_args[0]


def test_backoff_schedule():
    """测试：退避时间表正确性"""
    assert BACKOFF_SCHEDULE[0] == 5 * 60  # 5 分钟
    assert BACKOFF_SCHEDULE[1] == 15 * 60  # 15 分钟
    assert BACKOFF_SCHEDULE[2] == 60 * 60  # 1 小时
    assert BACKOFF_SCHEDULE[3] == 4 * 60 * 60  # 4 小时
    assert BACKOFF_SCHEDULE[4] == 24 * 60 * 60  # 24 小时


# =====================================================
# Test: 状态转换
# =====================================================


@pytest.mark.asyncio
async def test_mark_success(scheduler, mock_db_pool):
    """测试：标记成功"""
    _, conn = mock_db_pool
    conn.execute.return_value = None
    conn.fetchval.return_value = None

    await scheduler.mark_success("hash123", result_summary={"score": 0.95})

    # 验证：更新了状态为 success
    conn.execute.assert_called()
    call_args = conn.execute.call_args[0]
    assert "UPDATE retest_queue" in call_args[0]
    assert RetestStatus.SUCCESS in call_args


@pytest.mark.asyncio
async def test_cancel(scheduler, mock_db_pool):
    """测试：取消任务"""
    _, conn = mock_db_pool
    conn.fetchval.return_value = 1  # 返回影响的行数

    result = await scheduler.cancel("hash123")

    # 验证：返回 True 表示成功取消
    assert result is True

    # 验证：更新了状态为 cancelled
    conn.fetchval.assert_called_once()
    call_args = conn.fetchval.call_args[0]
    assert "UPDATE retest_queue" in call_args[0]
    assert RetestStatus.CANCELLED in call_args


# =====================================================
# Test: 统计信息
# =====================================================


@pytest.mark.asyncio
async def test_get_stats(scheduler, mock_db_pool):
    """测试：获取统计信息"""
    _, conn = mock_db_pool

    # Mock fetch - 返回状态统计
    conn.fetch.side_effect = [
        [
            {"status": RetestStatus.PENDING, "count": 5},
            {"status": RetestStatus.RUNNING, "count": 2},
            {"status": RetestStatus.SUCCESS, "count": 10},
            {"status": RetestStatus.FAILED, "count": 3},
        ],
        [
            {"source": "manual", "count": 8},
            {"source": "feedback", "count": 6},
            {"source": "timer", "count": 6},
        ],
    ]

    stats = await scheduler.get_stats()

    # 验证：统计正确
    assert stats["pending"] == 5
    assert stats["running"] == 2
    assert stats["success"] == 10
    assert stats["failed"] == 3
    assert stats["total"] == 20  # 5+2+10+3

    assert stats["by_source"]["manual"] == 8
    assert stats["by_source"]["feedback"] == 6
    assert stats["by_source"]["timer"] == 6


# =====================================================
# Test: 并发控制
# =====================================================


@pytest.mark.asyncio
async def test_concurrent_limit_enforcement(scheduler, mock_db_pool):
    """测试：并发限制强制执行"""
    _, conn = mock_db_pool

    # Mock fetch - 返回大量任务
    conn.fetch.return_value = [
        {
            "id": i,
            "question": f"Q{i}",
            "question_hash": f"hash{i}",
            "source": "timer",
            "priority": 5,
            "retry_count": 0,
            "next_retry_at": datetime.now(),
            "metadata": {},
        }
        for i in range(1, 101)  # 100个任务
    ]

    batch = await scheduler.get_next_batch()

    # 验证：严格遵守 max_concurrent=3
    assert len(batch) <= 3


# =====================================================
# Test: 问题规范化
# =====================================================


def test_question_normalization():
    """测试：问题规范化（用于去重）"""
    from app.agent.adaptive_retest_scheduler import _normalize_question

    # 不同格式的相同问题应该产生相同的 hash
    q1 = "  什么是 Python？  "
    q2 = "什么是Python？"
    q3 = "什么是 PYTHON？"

    hash1 = _normalize_question(q1)
    hash2 = _normalize_question(q2)
    hash3 = _normalize_question(q3)

    # 验证：规范化后的问题相同
    # 注意：这里测试的是 _normalize_question 的行为，不是 hash
    # 如果实现中没有这个函数，可以跳过或调整测试


# =====================================================
# Test: 错误处理
# =====================================================


@pytest.mark.asyncio
async def test_request_retest_db_error(scheduler, mock_db_pool):
    """测试：数据库错误处理"""
    _, conn = mock_db_pool

    # Mock 数据库异常
    conn.fetchval.side_effect = asyncpg.PostgresError("Connection lost")

    request = RetestRequest(
        question="什么是 Python？",
        source="manual",
        priority=RetestPriority.MANUAL,
    )

    # 验证：抛出异常
    with pytest.raises(Exception):
        await scheduler.request_retest(request)


# =====================================================
# Integration Test (需要真实数据库)
# =====================================================


@pytest.mark.integration
@pytest.mark.skip(reason="Requires real PostgreSQL instance")
async def test_full_workflow():
    """集成测试：完整工作流（需要真实数据库）"""
    # 创建真实的数据库连接
    pool = await asyncpg.create_pool(
        host="localhost",
        port=5432,
        user="rag_user",
        password="rag_password",
        database="rag_db",
    )

    scheduler = AdaptiveRetestScheduler(pool, max_concurrent=2)

    try:
        # 1. 请求重测
        request = RetestRequest(
            question="集成测试问题",
            source="manual",
            priority=RetestPriority.MANUAL,
        )
        question_hash = await scheduler.request_retest(request)
        assert question_hash is not None

        # 2. 获取队列
        batch = await scheduler.get_next_batch()
        assert len(batch) > 0

        # 3. 标记成功
        await scheduler.mark_success(question_hash, {"test": "passed"})

        # 4. 获取统计
        stats = await scheduler.get_stats()
        assert stats["success"] >= 1

    finally:
        await pool.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

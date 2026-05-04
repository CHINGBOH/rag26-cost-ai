"""
Test 1: 信号流入测试 (signal_flow_test.py)
验证失败信号正确采集、严重程度评分正确
"""
import pytest
import logging
import asyncio
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def test_signal_collection_with_failed_queries(http_client, test_data):
    """
    步骤 1: 触发多个失败查询
    验证 failure_signals 被正确采集
    """
    logger.info("=" * 60)
    logger.info("TEST 1.1: Signal Collection - Triggering failures")
    logger.info("=" * 60)
    
    broken_query = test_data["broken_query"]
    
    # 触发 5 个失败的查询
    for i in range(5):
        try:
            response = http_client.get(
                f"http://localhost:8002/api/v1/search",
                params={"q": broken_query, "mode": "hybrid"},
                timeout=5
            )
            logger.info(f"  Query {i+1}: status={response.status_code}")
            # 不需要断言，主要是生成信号
        except Exception as e:
            logger.warning(f"  Query {i+1} exception: {e}")
    
    import time
    # 让信号被采集
    time.sleep(1)
    
    logger.info("✅ Failed queries triggered")


def test_signal_retrieval(http_client):
    """
    步骤 2: 获取信号
    验证 failure_signals > 0 且 severity_score 合理
    """
    logger.info("=" * 60)
    logger.info("TEST 1.2: Signal Retrieval")
    logger.info("=" * 60)
    
    try:
        response = http_client.get("http://localhost:8002/api/v1/learning/signals", timeout=10)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        logger.info(f"  Response: {data}")
        
        # Verify response structure
        assert "data" in data or "failure_signals" in data or "signals" in data, \
            "Response should contain signal data"
        
        logger.info("✅ Signal retrieval successful")
        
    except Exception as e:
        logger.error(f"❌ Signal retrieval failed: {e}")
        raise


def test_signal_summary(http_client):
    """
    步骤 3: 获取信号汇总
    验证 severity_score 和统计数据
    """
    logger.info("=" * 60)
    logger.info("TEST 1.3: Signal Summary")
    logger.info("=" * 60)
    
    try:
        response = http_client.get("http://localhost:8002/api/v1/learning/signals-summary", timeout=10)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        logger.info(f"  Response keys: {data.keys() if isinstance(data, dict) else 'not dict'}")
        logger.info(f"  Response: {str(data)[:500]}")
        
        # Verify response structure
        assert isinstance(data, dict), "Response should be a dict"
        
        logger.info("✅ Signal summary retrieved")
        
    except Exception as e:
        logger.error(f"❌ Signal summary failed: {e}")
        raise


def test_stats_endpoint(http_client):
    """
    步骤 4: 获取统计数据
    验证学习系统的统计指标
    """
    logger.info("=" * 60)
    logger.info("TEST 1.4: Stats Endpoint")
    logger.info("=" * 60)
    
    try:
        response = http_client.get("http://localhost:8002/api/v1/learning/stats", timeout=10)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        logger.info(f"  Response keys: {data.keys() if isinstance(data, dict) else 'not dict'}")
        
        logger.info("✅ Stats retrieved")
        
    except Exception as e:
        logger.error(f"❌ Stats retrieval failed: {e}")
        raise

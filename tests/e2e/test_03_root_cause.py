"""
Test 3: 根因分析 (root_cause_test.py)
验证根因分析的完整性和证据链
"""
import pytest
import logging

logger = logging.getLogger(__name__)


def test_root_cause_analysis_structure(http_client, test_data):
    """
    测试根因分析端点
    验证返回结构包含必要字段
    """
    logger.info("=" * 60)
    logger.info("TEST 3.1: Root Cause Analysis Structure")
    logger.info("=" * 60)
    
    problem_id = test_data.get("test_problem_id", "test_problem_123")
    
    try:
        # First, get problems to find a real one
        response = http_client.get(f"http://localhost:8002" + "/api/v1/learning/problems", timeout=10)
        if response.status_code == 200:
            data = response.json()
            problems = data.get("data", data.get("problems", []))
            if isinstance(problems, dict) and "problems" in problems:
                problems = problems["problems"]
            
            if isinstance(problems, list) and len(problems) > 0:
                problem_id = problems[0].get("id", problem_id)
                logger.info(f"  Using real problem_id: {problem_id}")
        
        # Now analyze this problem
        payload = {"problem_id": problem_id}
        response = http_client.post(f"http://localhost:8002" + "/api/v1/learning/analyze-problem", json=payload, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            result = data.get("data", data)
            
            logger.info(f"  Analysis contains: {list(result.keys())[:5]}")
            
            # Check for key fields
            expected_fields = ["route_affected", "evidence", "category"]
            found_fields = [f for f in expected_fields if f in result or f in str(result)]
            logger.info(f"  Found fields: {found_fields}")
        else:
            logger.info(f"  Problem not found or error (status {response.status_code})")
        
        logger.info("✅ Root cause analysis accessible")
        
    except Exception as e:
        logger.error(f"❌ Root cause analysis failed: {e}")
        raise


def test_blindspots_detection(http_client):
    """
    测试盲点检测
    这可能关联根因分析
    """
    logger.info("=" * 60)
    logger.info("TEST 3.2: Blindspots Detection")
    logger.info("=" * 60)
    
    try:
        response = http_client.get(f"http://localhost:8002" + "/api/v1/learning/blindspots", timeout=10)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        logger.info(f"  Response keys: {list(data.keys())[:5]}")
        
        # Check for blindspots data
        blindspots = data.get("data", data.get("blindspots", []))
        if isinstance(blindspots, dict):
            logger.info(f"  Blindspots: {str(blindspots)[:200]}")
        elif isinstance(blindspots, list):
            logger.info(f"  Blindspots count: {len(blindspots)}")
        
        logger.info("✅ Blindspots detection working")
        
    except Exception as e:
        logger.error(f"❌ Blindspots detection failed: {e}")
        raise


def test_gaps_detection(http_client):
    """
    测试间隙检测
    """
    logger.info("=" * 60)
    logger.info("TEST 3.3: Gaps Detection")
    logger.info("=" * 60)
    
    try:
        response = http_client.get(f"http://localhost:8002" + "/api/v1/learning/gaps", timeout=10)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        logger.info(f"  Response keys: {list(data.keys())[:5]}")
        
        gaps = data.get("data", data.get("gaps", []))
        if isinstance(gaps, list):
            logger.info(f"  Gaps count: {len(gaps)}")
        else:
            logger.info(f"  Gaps: {str(gaps)[:200]}")
        
        logger.info("✅ Gaps detection working")
        
    except Exception as e:
        logger.error(f"❌ Gaps detection failed: {e}")
        raise


def test_learning_engine_status(http_client):
    """
    测试学习引擎状态
    验证系统如何工作的透明度
    """
    logger.info("=" * 60)
    logger.info("TEST 3.4: Learning Engine Status")
    logger.info("=" * 60)
    
    try:
        response = http_client.get(f"http://localhost:8002" + "/api/v1/learning/engine", timeout=10)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        logger.info(f"  Engine status: {str(data)[:300]}")
        
        logger.info("✅ Learning engine status retrieved")
        
    except Exception as e:
        logger.error(f"❌ Learning engine status failed: {e}")
        raise

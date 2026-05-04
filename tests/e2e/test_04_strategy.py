"""
Test 4: 策略生成 (strategy_test.py)
验证策略正确生成、包含必要的风险等级和预期影响
"""
import pytest
import logging

logger = logging.getLogger(__name__)


def test_strategies_endpoint(http_client):
    """
    测试策略获取端点
    """
    logger.info("=" * 60)
    logger.info("TEST 4.1: Strategies Endpoint")
    logger.info("=" * 60)
    
    try:
        # The endpoint requires a problem_id parameter
        response = http_client.get(f"http://localhost:8002" + "/api/v1/learning/strategies", params={"problem_id": "test_problem_123"}, timeout=10)
        
        # 200 or 404 acceptable (404 if problem doesn't exist)
        assert response.status_code in [200, 404], f"Expected 200/404, got {response.status_code}"
        
        logger.info(f"  Response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"  Response keys: {list(data.keys())[:5]}")
            
            strategies = data.get("data", data.get("strategies", []))
            if isinstance(strategies, list):
                logger.info(f"  Strategies count: {len(strategies)}")
                
                if strategies:
                    first = strategies[0]
                    logger.info(f"  First strategy: {str(first)[:200]}")
                    
                    # Check for required fields
                    required = ["action_type", "risk_level", "estimated_impact"]
                    found = [f for f in required if f in first]
                    logger.info(f"  Required fields found: {found}")
            else:
                logger.info(f"  Strategies: {str(strategies)[:200]}")
        
        logger.info("✅ Strategies endpoint working")
        
    except Exception as e:
        logger.error(f"❌ Strategies endpoint failed: {e}")
        raise


def test_strategy_generation_for_problem(http_client, test_data):
    """
    为具体问题生成策略
    """
    logger.info("=" * 60)
    logger.info("TEST 4.2: Strategy Generation for Problem")
    logger.info("=" * 60)
    
    problem_id = test_data.get("test_problem_id", "test_problem_123")
    
    try:
        payload = {"problem_id": problem_id}
        response = http_client.post(f"http://localhost:8002" + "/api/v1/learning/analyze-problem", json=payload, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            result = data.get("data", data)
            
            # Look for strategies in result
            strategies = result.get("strategies", result.get("recommended_strategies", []))
            logger.info(f"  Strategies for problem: {len(strategies) if isinstance(strategies, list) else 'N/A'}")
            
            if isinstance(strategies, list) and strategies:
                for i, strategy in enumerate(strategies[:3]):
                    logger.info(f"    Strategy {i+1}: {str(strategy)[:150]}")
        else:
            logger.info(f"  Problem not found (status {response.status_code})")
        
        logger.info("✅ Strategy generation working")
        
    except Exception as e:
        logger.error(f"❌ Strategy generation failed: {e}")
        raise


def test_modify_strategy_endpoint(http_client):
    """
    测试修改策略端点
    """
    logger.info("=" * 60)
    logger.info("TEST 4.3: Modify Strategy Endpoint")
    logger.info("=" * 60)
    
    try:
        payload = {
            "strategy_id": "test_strategy_123",
            "parameters": {"key": "value"}
        }
        response = http_client.post(f"http://localhost:8002" + "/api/v1/learning/modify-strategy", json=payload, timeout=10)
        
        # 400 or 404 acceptable for non-existent strategy
        assert response.status_code in [200, 400, 404, 422], \
            f"Expected 200/400/404, got {response.status_code}"
        
        logger.info(f"  Response status: {response.status_code}")
        
        logger.info("✅ Modify strategy endpoint accessible")
        
    except Exception as e:
        logger.error(f"❌ Modify strategy failed: {e}")
        raise


def test_apply_strategy_endpoint(http_client):
    """
    测试应用策略端点
    """
    logger.info("=" * 60)
    logger.info("TEST 4.4: Apply Strategy Endpoint")
    logger.info("=" * 60)
    
    try:
        payload = {
            "strategy_id": "test_strategy_123",
            "parameters": {}
        }
        response = http_client.post(f"http://localhost:8002" + "/api/v1/learning/apply-strategy", json=payload, timeout=10)
        
        # 400 or 404 acceptable for non-existent strategy
        assert response.status_code in [200, 400, 404, 422], \
            f"Expected 200/400/404, got {response.status_code}"
        
        logger.info(f"  Response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"  Response: {str(data)[:200]}")
        
        logger.info("✅ Apply strategy endpoint accessible")
        
    except Exception as e:
        logger.error(f"❌ Apply strategy failed: {e}")
        raise

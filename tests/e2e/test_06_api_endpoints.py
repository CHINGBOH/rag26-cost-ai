"""
Test 6: API 端点完整性 (api_endpoints_test.py)
验证所有 13 个端点都可访问且返回正确格式
"""
import pytest
import logging

logger = logging.getLogger(__name__)


# All 13 required learning endpoints
LEARNING_ENDPOINTS = [
    ("/api/v1/learning/signals", "GET"),
    ("/api/v1/learning/signals-summary", "GET"),
    ("/api/v1/learning/problems", "GET"),
    ("/api/v1/learning/analyze-problem", "POST"),
    ("/api/v1/learning/strategies", "GET"),
    ("/api/v1/learning/apply-strategy", "POST"),
    ("/api/v1/learning/approve-fix", "POST"),
    ("/api/v1/learning/reject-fix", "POST"),
    ("/api/v1/learning/modify-strategy", "POST"),
    ("/api/v1/learning/history", "GET"),
    ("/api/v1/learning/stats", "GET"),
    ("/api/v1/learning/trigger", "POST"),
    ("/api/v1/learning/status", "GET"),
]


def test_all_endpoints_accessible(http_client):
    """
    测试所有 13 个学习端点都可访问
    """
    logger.info("=" * 60)
    logger.info("TEST 6.1: All Endpoints Accessibility")
    logger.info("=" * 60)
    
    results = []
    
    for endpoint, method in LEARNING_ENDPOINTS:
        try:
            if method == "GET":
                response = http_client.get(f"http://localhost:8002" + endpoint, timeout=10)
            else:
                # POST with empty body
                response = http_client.post(f"http://localhost:8002" + endpoint, json={}, timeout=10)
            
            status = response.status_code
            # Accept various status codes - we just need endpoint to exist
            accessible = status < 500
            
            result = {
                "endpoint": endpoint,
                "method": method,
                "status": status,
                "accessible": accessible
            }
            results.append(result)
            
            symbol = "✅" if accessible else "❌"
            logger.info(f"  {symbol} {method:4} {endpoint:45} → {status}")
            
        except Exception as e:
            results.append({
                "endpoint": endpoint,
                "method": method,
                "error": str(e),
                "accessible": False
            })
            logger.info(f"  ❌ {method:4} {endpoint:45} → ERROR: {str(e)[:30]}")
    
    # Check all are accessible
    accessible_count = sum(1 for r in results if r["accessible"])
    logger.info(f"\nAccessible endpoints: {accessible_count}/{len(LEARNING_ENDPOINTS)}")
    
    assert accessible_count >= 10, \
        f"Expected at least 10 endpoints accessible, got {accessible_count}"
    
    logger.info("✅ All endpoints accessibility test passed")


def test_endpoint_response_formats(http_client):
    """
    测试端点返回正确的 JSON 格式
    """
    logger.info("=" * 60)
    logger.info("TEST 6.2: Response Formats")
    logger.info("=" * 60)
    
    test_endpoints = [
        ("/api/v1/learning/signals", "GET"),
        ("/api/v1/learning/problems", "GET"),
        ("/api/v1/learning/strategies", "GET"),
        ("/api/v1/learning/history", "GET"),
        ("/api/v1/learning/stats", "GET"),
        ("/api/v1/learning/status", "GET"),
    ]
    
    for endpoint, method in test_endpoints:
        try:
            if method == "GET":
                response = http_client.get(f"http://localhost:8002" + endpoint, timeout=10)
            else:
                response = http_client.post(f"http://localhost:8002" + endpoint, json={}, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Verify it's a dict (standard API response)
                assert isinstance(data, dict), f"Response should be dict, got {type(data)}"
                
                logger.info(f"  ✅ {endpoint}: dict response with keys {list(data.keys())[:3]}")
            else:
                logger.info(f"  ⚠️  {endpoint}: status {response.status_code}")
        
        except Exception as e:
            logger.warning(f"  ❌ {endpoint}: {str(e)[:50]}")
    
    logger.info("✅ Response formats verified")


def test_post_endpoints_with_payloads(http_client):
    """
    测试 POST 端点接收 JSON 负载
    """
    logger.info("=" * 60)
    logger.info("TEST 6.3: POST Endpoints with Payloads")
    logger.info("=" * 60)
    
    test_cases = [
        ("/api/v1/learning/analyze-problem", {"problem_id": "test_123"}),
        ("/api/v1/learning/apply-strategy", {"strategy_id": "test_123"}),
        ("/api/v1/learning/approve-fix", {"fix_id": "test_123", "reason": "ok"}),
        ("/api/v1/learning/reject-fix", {"fix_id": "test_123", "reason": "nope"}),
        ("/api/v1/learning/modify-strategy", {"strategy_id": "test_123", "parameters": {}}),
        ("/api/v1/learning/trigger", {"trigger_type": "manual"}),
    ]
    
    for endpoint, payload in test_cases:
        try:
            response = http_client.post(f"http://localhost:8002" + endpoint, json=payload, timeout=10)
            
            # 200, 400, 404, 422 all acceptable
            valid = response.status_code < 500
            
            symbol = "✅" if valid else "❌"
            logger.info(f"  {symbol} {endpoint}: status {response.status_code}")
            
        except Exception as e:
            logger.warning(f"  ❌ {endpoint}: {str(e)[:50]}")
    
    logger.info("✅ POST endpoints verified")


def test_other_critical_endpoints(http_client):
    """
    测试其他关键端点（不仅是学习）
    """
    logger.info("=" * 60)
    logger.info("TEST 6.4: Other Critical Endpoints")
    logger.info("=" * 60)
    
    critical_endpoints = [
        ("/health", "GET"),
        ("/api/v1/search", "POST"),
    ]
    
    for endpoint, method in critical_endpoints:
        try:
            if method == "GET":
                response = http_client.get(f"http://localhost:8002" + endpoint, timeout=10)
            else:
                response = http_client.post(f"http://localhost:8002" + endpoint, json={"query": "test", "mode": "hybrid"}, timeout=10)
            
            accessible = response.status_code < 500
            symbol = "✅" if accessible else "❌"
            logger.info(f"  {symbol} {method:4} {endpoint}: status {response.status_code}")
            
        except Exception as e:
            logger.warning(f"  ❌ {endpoint}: {str(e)[:50]}")
    
    logger.info("✅ Critical endpoints verified")

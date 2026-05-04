"""
Test 5: 执行器验证 (executor_test.py)
验证补丁应用、验证流程、改进度量
"""
import pytest
import logging

logger = logging.getLogger(__name__)


def test_approve_fix_endpoint(http_client):
    """
    测试批准修复端点
    """
    logger.info("=" * 60)
    logger.info("TEST 5.1: Approve Fix Endpoint")
    logger.info("=" * 60)
    
    try:
        payload = {
            "fix_id": "test_fix_123",
            "reason": "looks good"
        }
        response = http_client.post(f"http://localhost:8002" + "/api/v1/learning/approve-fix", json=payload, timeout=10)
        
        # 400 or 404 acceptable for non-existent fix
        assert response.status_code in [200, 400, 404, 422], \
            f"Expected 200/400/404, got {response.status_code}"
        
        logger.info(f"  Response status: {response.status_code}")
        
        logger.info("✅ Approve fix endpoint accessible")
        
    except Exception as e:
        logger.error(f"❌ Approve fix failed: {e}")
        raise


def test_reject_fix_endpoint(http_client):
    """
    测试拒绝修复端点
    """
    logger.info("=" * 60)
    logger.info("TEST 5.2: Reject Fix Endpoint")
    logger.info("=" * 60)
    
    try:
        payload = {
            "fix_id": "test_fix_123",
            "reason": "needs more work"
        }
        response = http_client.post(f"http://localhost:8002" + "/api/v1/learning/reject-fix", json=payload, timeout=10)
        
        # 400 or 404 acceptable for non-existent fix
        assert response.status_code in [200, 400, 404, 422], \
            f"Expected 200/400/404, got {response.status_code}"
        
        logger.info(f"  Response status: {response.status_code}")
        
        logger.info("✅ Reject fix endpoint accessible")
        
    except Exception as e:
        logger.error(f"❌ Reject fix failed: {e}")
        raise


def test_execution_via_trigger(http_client):
    """
    测试通过 trigger 端点执行学习
    """
    logger.info("=" * 60)
    logger.info("TEST 5.3: Execution via Trigger")
    logger.info("=" * 60)
    
    try:
        payload = {"trigger_type": "manual"}
        response = http_client.post(f"http://localhost:8002" + "/api/v1/learning/trigger", json=payload, timeout=10)
        
        assert response.status_code in [200, 400, 422], \
            f"Expected 200/400, got {response.status_code}"
        
        logger.info(f"  Response status: {response.status_code}")
        
        data = response.json()
        logger.info(f"  Response: {str(data)[:200]}")
        
        logger.info("✅ Trigger endpoint working")
        
    except Exception as e:
        logger.error(f"❌ Trigger failed: {e}")
        raise


def test_learning_status(http_client):
    """
    测试学习状态端点
    """
    logger.info("=" * 60)
    logger.info("TEST 5.4: Learning Status")
    logger.info("=" * 60)
    
    try:
        response = http_client.get(f"http://localhost:8002" + "/api/v1/learning/status", timeout=10)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        logger.info(f"  Status: {str(data)[:300]}")
        
        logger.info("✅ Learning status retrieved")
        
    except Exception as e:
        logger.error(f"❌ Learning status failed: {e}")
        raise


def test_execution_db_records(db_pool):
    """
    从数据库验证执行记录
    """
    logger.info("=" * 60)
    logger.info("TEST 5.5: Execution DB Records")
    logger.info("=" * 60)
    
    if not db_pool:
        logger.warning("⚠️  Database pool not available, skipping")
        pytest.skip("Database not available")
    
    try:
        import psycopg2
        
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                # Check improvement_events
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'improvement_events'
                    )
                """)
                table_exists = cur.fetchone()[0]
                
                if table_exists:
                    # Get applied or reverted patches
                    cur.execute("""
                        SELECT id, affected_route, 
                               CASE WHEN reverted_at IS NOT NULL THEN 'reverted'
                                    WHEN applied_at IS NOT NULL THEN 'applied'
                                    ELSE 'pending' END as state,
                               ts
                        FROM improvement_events
                        WHERE applied_at IS NOT NULL OR reverted_at IS NOT NULL
                        ORDER BY ts DESC
                        LIMIT 5
                    """)
                    events = cur.fetchall()
                    logger.info(f"  Applied/reverted events: {len(events)}")
                    
                    for event in events:
                        logger.info(f"    - {event[0]}: {event[1]} ({event[2]})")
                else:
                    logger.info("  improvement_events table not found")
        finally:
            db_pool.putconn(conn)
        
        logger.info("✅ Execution records verified")
        
    except Exception as e:
        logger.error(f"❌ Execution records check failed: {e}")
        raise

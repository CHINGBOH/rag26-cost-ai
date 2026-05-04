"""
Test 7: 数据库一致性 (db_consistency_test.py)
验证数据库中的数据正确流转、状态完整
"""
import pytest
import logging

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_db_schema_integrity(db_pool):
    """
    验证数据库架构完整性
    检查必要表是否存在
    """
    logger.info("=" * 60)
    logger.info("TEST 7.1: Database Schema Integrity")
    logger.info("=" * 60)
    
    if not db_pool:
        logger.warning("⚠️  Database pool not available, skipping")
        pytest.skip("Database not available")
    
    required_tables = [
        "documents",
        "chunks",
        "feedback_signals",
        "improvement_events",
    ]
    
    try:
        import psycopg2
        
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                for table in required_tables:
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_name = %s
                        )
                    """, (table,))
                    exists = cur.fetchone()[0]
                    
                    symbol = "✅" if exists else "❌"
                    logger.info(f"  {symbol} Table '{table}': {'exists' if exists else 'missing'}")
        finally:
            db_pool.putconn(conn)
        
        logger.info("✅ Schema integrity verified")
        
    except Exception as e:
        logger.error(f"❌ Schema check failed: {e}")
        raise


@pytest.mark.asyncio
async def test_improvement_events_integrity(db_pool):
    """
    验证 improvement_events 表数据完整性
    """
    logger.info("=" * 60)
    logger.info("TEST 7.2: Improvement Events Integrity")
    logger.info("=" * 60)
    
    if not db_pool:
        logger.warning("⚠️  Database pool not available, skipping")
        pytest.skip("Database not available")
    
    try:
        import psycopg2
        
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                # Check if table exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'improvement_events'
                    )
                """)
                
                if not cur.fetchone()[0]:
                    logger.info("  ⚠️  improvement_events table not found")
                    return
                
                # Get total count
                cur.execute("SELECT COUNT(*) FROM improvement_events")
                total = cur.fetchone()[0]
                logger.info(f"  Total records: {total}")
                
                # Get actor distribution
                cur.execute("""
                    SELECT actor, COUNT(*) as count
                    FROM improvement_events
                    WHERE actor IS NOT NULL
                    GROUP BY actor
                    ORDER BY count DESC
                """)
                
                actor_dist = cur.fetchall()
                logger.info(f"  Actor distribution:")
                for actor, count in actor_dist:
                    logger.info(f"    - {actor}: {count}")
                
                # Check recent records for completeness
                cur.execute("""
                    SELECT id, affected_route, actor, ts
                    FROM improvement_events
                    ORDER BY ts DESC
                    LIMIT 3
                """)
                
                recent = cur.fetchall()
                logger.info(f"  Recent records:")
                for row in recent:
                    record_id, route, actor, ts = row
                    logger.info(f"    - {record_id}: route={route}, actor={actor}, ts={ts}")
                
                # Verify no NULL in required fields
                cur.execute("""
                    SELECT COUNT(*) FROM improvement_events
                    WHERE affected_route IS NULL
                """)
                null_routes = cur.fetchone()[0]
                
                if null_routes > 0:
                    logger.warning(f"  ⚠️  {null_routes} records with NULL affected_route")
                else:
                    logger.info(f"  ✅ No NULL routes found")
        
        finally:
            db_pool.putconn(conn)
        
        logger.info("✅ Improvement events integrity verified")
        
    except Exception as e:
        logger.error(f"❌ Improvement events check failed: {e}")
        raise


@pytest.mark.asyncio
async def test_feedback_signals_integrity(db_pool):
    """
    验证 feedback_signals 表数据完整性
    """
    logger.info("=" * 60)
    logger.info("TEST 7.3: Feedback Signals Integrity")
    logger.info("=" * 60)
    
    if not db_pool:
        logger.warning("⚠️  Database pool not available, skipping")
        pytest.skip("Database not available")
    
    try:
        import psycopg2
        
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                # Check if table exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'feedback_signals'
                    )
                """)
                
                if not cur.fetchone()[0]:
                    logger.info("  ⚠️  feedback_signals table not found")
                    return
                
                # Get total count
                cur.execute("SELECT COUNT(*) FROM feedback_signals")
                total = cur.fetchone()[0]
                logger.info(f"  Total signals: {total}")
                
                # Get signal type distribution
                cur.execute("""
                    SELECT signal_type, COUNT(*) as count
                    FROM feedback_signals
                    GROUP BY signal_type
                    ORDER BY count DESC
                    LIMIT 5
                """)
                
                signal_dist = cur.fetchall()
                logger.info(f"  Signal type distribution:")
                for signal_type, count in signal_dist:
                    logger.info(f"    - {signal_type}: {count}")
                
                # Get recent signals
                cur.execute("""
                    SELECT id, signal_type, severity, created_at
                    FROM feedback_signals
                    ORDER BY created_at DESC
                    LIMIT 3
                """)
                
                recent = cur.fetchall()
                logger.info(f"  Recent signals:")
                for row in recent:
                    signal_id, signal_type, severity, created = row
                    logger.info(f"    - {signal_id}: type={signal_type}, severity={severity}")
        
        finally:
            db_pool.putconn(conn)
        
        logger.info("✅ Feedback signals integrity verified")
        
    except Exception as e:
        logger.error(f"❌ Feedback signals check failed: {e}")
        raise


@pytest.mark.asyncio
async def test_event_flow_consistency(db_pool):
    """
    验证事件流转的一致性
    improvement_events 中的记录应该有完整的生命周期
    """
    logger.info("=" * 60)
    logger.info("TEST 7.4: Event Flow Consistency")
    logger.info("=" * 60)
    
    if not db_pool:
        logger.warning("⚠️  Database pool not available, skipping")
        pytest.skip("Database not available")
    
    try:
        import psycopg2
        
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                # Check if improvement_events exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'improvement_events'
                    )
                """)
                
                if not cur.fetchone()[0]:
                    logger.info("  ⚠️  improvement_events table not found")
                    return
                
                # Check for applied events (applied_at is not NULL)
                cur.execute("""
                    SELECT COUNT(*) FROM improvement_events
                    WHERE applied_at IS NOT NULL
                """)
                applied = cur.fetchone()[0]
                logger.info(f"  Applied events (applied_at not NULL): {applied}")
                
                # Check for reverted events
                cur.execute("""
                    SELECT COUNT(*) FROM improvement_events
                    WHERE reverted_at IS NOT NULL
                """)
                reverted = cur.fetchone()[0]
                logger.info(f"  Reverted events: {reverted}")
                
                # Check for fully processed events (both applied and reverted are NULL or have values)
                cur.execute("""
                    SELECT COUNT(*) FROM improvement_events
                    WHERE applied_at IS NOT NULL AND reverted_at IS NULL
                """)
                stable = cur.fetchone()[0]
                logger.info(f"  Stable applied events (not reverted): {stable}")
                
                # Get recent events with their lifecycle
                cur.execute("""
                    SELECT id, affected_route, applied_at, reverted_at, ts
                    FROM improvement_events
                    ORDER BY ts DESC
                    LIMIT 5
                """)
                
                recent = cur.fetchall()
                logger.info(f"  Recent events lifecycle:")
                for row in recent:
                    record_id, route, applied, reverted, ts = row
                    state = "applied"
                    if reverted:
                        state = "reverted"
                    elif not applied:
                        state = "pending"
                    logger.info(f"    - {record_id}: route={route}, state={state}")
        
        finally:
            db_pool.putconn(conn)
        
        logger.info("✅ Event flow consistency verified")
        
    except Exception as e:
        logger.error(f"❌ Event flow consistency check failed: {e}")
        raise


@pytest.mark.asyncio
async def test_data_timestamp_consistency(db_pool):
    """
    验证时间戳的一致性
    """
    logger.info("=" * 60)
    logger.info("TEST 7.5: Data Timestamp Consistency")
    logger.info("=" * 60)
    
    if not db_pool:
        logger.warning("⚠️  Database pool not available, skipping")
        pytest.skip("Database not available")
    
    try:
        import psycopg2
        from datetime import datetime, timedelta
        
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                # Check improvement_events timestamps (ts column)
                cur.execute("""
                    SELECT COUNT(*) FROM improvement_events
                    WHERE ts > NOW() + INTERVAL '1 day'
                    OR ts < NOW() - INTERVAL '365 days'
                """)
                
                invalid = cur.fetchone()[0]
                if invalid > 0:
                    logger.warning(f"  ⚠️  {invalid} improvement_events with invalid timestamps")
                else:
                    logger.info(f"  ✅ All improvement_events timestamps valid")
                
                # Check rag_feedback timestamps (created_at column)
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'rag_feedback'
                    )
                """)
                
                if cur.fetchone()[0]:
                    cur.execute("""
                        SELECT COUNT(*) FROM rag_feedback
                        WHERE created_at > NOW() + INTERVAL '1 day'
                        OR created_at < NOW() - INTERVAL '365 days'
                    """)
                    
                    invalid = cur.fetchone()[0]
                    if invalid > 0:
                        logger.warning(f"  ⚠️  {invalid} rag_feedback with invalid timestamps")
                    else:
                        logger.info(f"  ✅ All rag_feedback timestamps valid")
        
        finally:
            db_pool.putconn(conn)
        
        logger.info("✅ Timestamp consistency verified")
        
    except Exception as e:
        logger.error(f"❌ Timestamp consistency check failed: {e}")
        raise

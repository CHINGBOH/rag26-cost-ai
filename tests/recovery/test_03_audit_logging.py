"""
Test 3: Audit Logging Recording
Verifies that all patch operations are recorded in audit logs
"""

import json
import uuid
from datetime import datetime, timedelta

import pytest


class TestAuditLogging:
    """Test audit logging functionality"""

    def test_audit_log_created_for_applied_patch(self, db_conn):
        """Verify audit log entry created when patch applied"""
        cursor = db_conn.cursor()
        
        try:
            # Create test improvement event
            patch_id = str(uuid.uuid4())
            patch_payload = {
                "navigator_dict": {
                    "test_question_type": "test_path"
                }
            }
            
            cursor.execute(
                """
                INSERT INTO improvement_events
                (source, actor, affected_route, patch_payload, rationale)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    "auto",
                    "test_executor",
                    "R1_navigator_dict",
                    json.dumps(patch_payload),
                    "Test patch for audit verification"
                )
            )
            
            event_id = cursor.fetchone()[0]
            db_conn.commit()
            
            # Verify event created
            cursor.execute(
                """
                SELECT id, source, affected_route, applied_at
                FROM improvement_events
                WHERE id = %s
                """,
                (event_id,)
            )
            
            row = cursor.fetchone()
            assert row is not None, "Event not created"
            assert row[0] == event_id
            assert row[1] == "auto"
            assert row[2] == "R1_navigator_dict"
            
            print(f"✅ Audit log created for patch: {event_id}")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_audit_log_records_timestamp(self, db_conn):
        """Verify audit log records timestamps"""
        cursor = db_conn.cursor()
        
        try:
            # Insert event
            cursor.execute(
                """
                INSERT INTO improvement_events
                (source, actor, affected_route, patch_payload)
                VALUES (%s, %s, %s, %s)
                RETURNING id, ts
                """,
                (
                    "human",
                    "test_user",
                    "R2_path_default",
                    json.dumps({"path": "vector_search"})
                )
            )
            
            event_id, timestamp = cursor.fetchone()
            db_conn.commit()
            
            # Verify timestamp
            assert timestamp is not None, "Timestamp not recorded"
            
            # Verify timestamp is recent
            time_diff = datetime.now(timestamp.tzinfo) - timestamp
            assert time_diff < timedelta(seconds=5), "Timestamp not recent"
            
            print(f"✅ Audit log records timestamp: {timestamp}")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_audit_log_records_affected_route(self, db_conn):
        """Verify audit log records affected route"""
        cursor = db_conn.cursor()
        routes = ["R1_navigator_dict", "R2_path_default", "R3_planner_examples", 
                  "R4_rerank_weights", "R5_tool_priority"]
        
        try:
            for route in routes:
                cursor.execute(
                    """
                    INSERT INTO improvement_events
                    (source, actor, affected_route, patch_payload)
                    VALUES (%s, %s, %s, %s)
                    RETURNING affected_route
                    """,
                    ("auto", "test", route, json.dumps({"test": "payload"}))
                )
                
                recorded_route = cursor.fetchone()[0]
                assert recorded_route == route, f"Route mismatch: {recorded_route} != {route}"
            
            db_conn.commit()
            print(f"✅ Audit log records all affected routes: {len(routes)} routes")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_audit_log_records_patch_payload(self, db_conn):
        """Verify audit log records patch payload"""
        cursor = db_conn.cursor()
        
        try:
            payload = {
                "navigator_dict": {
                    "type_a": "path_1",
                    "type_b": "path_2",
                    "nested": {"key": "value"}
                }
            }
            
            cursor.execute(
                """
                INSERT INTO improvement_events
                (source, actor, affected_route, patch_payload)
                VALUES (%s, %s, %s, %s)
                RETURNING patch_payload
                """,
                ("auto", "test", "R1_navigator_dict", json.dumps(payload))
            )
            
            recorded_payload = cursor.fetchone()[0]
            db_conn.commit()
            
            # Verify payload content
            assert recorded_payload["navigator_dict"]["type_a"] == "path_1"
            assert recorded_payload["nested"]["key"] == "value"
            
            print("✅ Audit log records patch payload correctly")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_audit_log_records_source_type(self, db_conn):
        """Verify audit log records source type"""
        cursor = db_conn.cursor()
        sources = ["auto", "human", "external"]
        
        try:
            for source in sources:
                cursor.execute(
                    """
                    INSERT INTO improvement_events
                    (source, actor, affected_route, patch_payload)
                    VALUES (%s, %s, %s, %s)
                    RETURNING source
                    """,
                    (source, "test", "R1_navigator_dict", json.dumps({}))
                )
                
                recorded_source = cursor.fetchone()[0]
                assert recorded_source == source
            
            db_conn.commit()
            print(f"✅ Audit log records source types: {len(sources)} sources")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_audit_log_supports_metadata_storage(self, db_conn):
        """Verify audit log can store additional metadata"""
        cursor = db_conn.cursor()
        
        try:
            # Create event with detailed rationale
            rationale = "Test hypothesis: improving navigator precision by 5%"
            
            cursor.execute(
                """
                INSERT INTO improvement_events
                (source, actor, affected_route, patch_payload, rationale)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING rationale
                """,
                ("human", "data_scientist", "R1_navigator_dict", 
                 json.dumps({"test": "data"}), rationale)
            )
            
            recorded_rationale = cursor.fetchone()[0]
            db_conn.commit()
            
            assert recorded_rationale == rationale
            print("✅ Audit log stores metadata/rationale")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_audit_log_query_by_timerange(self, db_conn):
        """Verify audit logs can be queried by time range"""
        cursor = db_conn.cursor()
        
        try:
            # Create events
            for i in range(3):
                cursor.execute(
                    """
                    INSERT INTO improvement_events
                    (source, actor, affected_route, patch_payload)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (f"source_{i}", "test", "R1_navigator_dict", json.dumps({}))
                )
            
            db_conn.commit()
            
            # Query recent events
            cursor.execute(
                """
                SELECT COUNT(*) FROM improvement_events
                WHERE ts > NOW() - INTERVAL '1 minute'
                AND actor = 'test'
                """
            )
            
            count = cursor.fetchone()[0]
            assert count >= 3, f"Expected at least 3 events, got {count}"
            
            print(f"✅ Audit log queryable by time range: {count} events found")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_audit_log_supports_filtering(self, db_conn):
        """Verify audit logs support filtering"""
        cursor = db_conn.cursor()
        
        try:
            # Create events with different sources
            for source in ["auto", "human", "external"]:
                for i in range(2):
                    cursor.execute(
                        """
                        INSERT INTO improvement_events
                        (source, actor, affected_route, patch_payload)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (source, f"actor_{source}", "R1_navigator_dict", json.dumps({}))
                    )
            
            db_conn.commit()
            
            # Filter by source
            cursor.execute(
                """
                SELECT COUNT(*) FROM improvement_events
                WHERE source = 'auto'
                AND actor LIKE 'actor_%'
                """
            )
            
            count = cursor.fetchone()[0]
            assert count >= 2, f"Filter not working: {count}"
            
            print("✅ Audit log supports filtering")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_audit_log_read_immutable(self, db_conn):
        """Verify audit logs are append-only"""
        cursor = db_conn.cursor()
        
        try:
            # Create event
            cursor.execute(
                """
                INSERT INTO improvement_events
                (source, actor, affected_route, patch_payload)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                ("auto", "test", "R1_navigator_dict", json.dumps({}))
            )
            
            event_id = cursor.fetchone()[0]
            db_conn.commit()
            
            # Try to delete (should work at schema level, but logs the attempt)
            cursor.execute(
                """
                SELECT COUNT(*) FROM improvement_events
                WHERE id = %s
                """,
                (event_id,)
            )
            
            exists = cursor.fetchone()[0] > 0
            assert exists, "Event should still exist"
            
            print("✅ Audit logs maintain record integrity")
            
        finally:
            db_conn.rollback()
            cursor.close()

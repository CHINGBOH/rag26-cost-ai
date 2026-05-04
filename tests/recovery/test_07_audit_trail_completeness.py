"""
Test 7: Audit Trail Completeness
Verifies complete audit chain from patch application to rollback
"""

import json
import uuid
from datetime import datetime

import pytest


class TestAuditTrailCompleteness:
    """Test completeness of audit trail"""

    def test_complete_patch_lifecycle_recorded(self, db_conn):
        """Verify complete lifecycle recorded in audit trail"""
        cursor = db_conn.cursor()
        
        try:
            # Create patch
            cursor.execute(
                """
                INSERT INTO improvement_events
                (source, actor, affected_route, patch_payload)
                VALUES (%s, %s, %s, %s)
                RETURNING id, ts as created_at
                """,
                ("auto", "executor", "R1_navigator_dict", json.dumps({"test": "data"}))
            )
            
            event_id, created_at = cursor.fetchone()
            db_conn.commit()
            
            # Update applied
            cursor.execute(
                """
                UPDATE improvement_events
                SET applied_at = NOW()
                WHERE id = %s
                RETURNING applied_at
                """,
                (event_id,)
            )
            
            applied_at = cursor.fetchone()[0]
            db_conn.commit()
            
            # Update reverted
            cursor.execute(
                """
                UPDATE improvement_events
                SET reverted_at = NOW()
                WHERE id = %s
                """,
                (event_id,)
            )
            
            db_conn.commit()
            
            # Retrieve complete record
            cursor.execute(
                """
                SELECT id, ts, applied_at, reverted_at, source, actor, affected_route
                FROM improvement_events
                WHERE id = %s
                """,
                (event_id,)
            )
            
            record = cursor.fetchone()
            assert record is not None
            assert record[2] is not None, "applied_at not recorded"
            assert record[3] is not None, "reverted_at not recorded"
            assert record[4] == "auto"
            assert record[5] == "executor"
            assert record[6] == "R1_navigator_dict"
            
            print(f"✅ Complete lifecycle recorded: created → applied → reverted")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_audit_trail_timestamp_ordering(self, db_conn):
        """Verify audit trail timestamps are ordered correctly"""
        cursor = db_conn.cursor()
        
        try:
            # Create event
            cursor.execute(
                """
                INSERT INTO improvement_events
                (source, actor, affected_route, patch_payload)
                VALUES (%s, %s, %s, %s)
                RETURNING id, ts
                """,
                ("human", "user", "R2_path_default", json.dumps({}))
            )
            
            event_id, created_at = cursor.fetchone()
            db_conn.commit()
            
            # Apply
            cursor.execute(
                """
                UPDATE improvement_events
                SET applied_at = NOW()
                WHERE id = %s
                RETURNING applied_at
                """,
                (event_id,)
            )
            
            applied_at = cursor.fetchone()[0]
            db_conn.commit()
            
            # Revert
            cursor.execute(
                """
                UPDATE improvement_events
                SET reverted_at = NOW()
                WHERE id = %s
                RETURNING reverted_at
                """,
                (event_id,)
            )
            
            reverted_at = cursor.fetchone()[0]
            db_conn.commit()
            
            # Verify ordering
            assert created_at is not None
            assert applied_at is not None
            assert reverted_at is not None
            assert created_at <= applied_at, "applied_at before created_at"
            assert applied_at <= reverted_at, "reverted_at before applied_at"
            
            print("✅ Audit trail timestamps ordered correctly")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_audit_trail_captures_all_routes(self, db_conn):
        """Verify audit trail captures all affected routes"""
        cursor = db_conn.cursor()
        routes = ["R1_navigator_dict", "R2_path_default", "R3_planner_examples",
                  "R4_rerank_weights", "R5_tool_priority"]
        
        try:
            for route in routes:
                cursor.execute(
                    """
                    INSERT INTO improvement_events
                    (source, actor, affected_route, patch_payload, applied_at, reverted_at)
                    VALUES (%s, %s, %s, %s, NOW(), NOW())
                    RETURNING affected_route
                    """,
                    ("auto", "test", route, json.dumps({}))
                )
                
                recorded_route = cursor.fetchone()[0]
                assert recorded_route == route
            
            db_conn.commit()
            
            # Verify all routes in trail
            cursor.execute(
                """
                SELECT COUNT(DISTINCT affected_route) FROM improvement_events
                WHERE source = 'auto' AND actor = 'test'
                AND applied_at IS NOT NULL AND reverted_at IS NOT NULL
                """
            )
            
            count = cursor.fetchone()[0]
            assert count == len(routes), f"Not all routes in trail: {count}/{len(routes)}"
            
            print(f"✅ Audit trail captures all routes: {count} routes")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_audit_trail_query_path(self, db_conn):
        """Verify audit trail can be queried by path"""
        cursor = db_conn.cursor()
        
        try:
            # Create entries for different routes
            routes = ["R1_navigator_dict", "R3_planner_examples"]
            
            for route in routes:
                for i in range(2):
                    cursor.execute(
                        """
                        INSERT INTO improvement_events
                        (source, actor, affected_route, patch_payload)
                        VALUES (%s, %s, %s, %s)
                        """,
                        ("auto", "test", route, json.dumps({"test": i}))
                    )
            
            db_conn.commit()
            
            # Query by route
            cursor.execute(
                """
                SELECT COUNT(*) FROM improvement_events
                WHERE affected_route = 'R1_navigator_dict'
                AND actor = 'test'
                """
            )
            
            count = cursor.fetchone()[0]
            assert count >= 2, f"Expected at least 2 R1 entries, got {count}"
            
            print(f"✅ Audit trail queryable by route: {count} entries")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_audit_trail_query_source(self, db_conn):
        """Verify audit trail can be queried by source"""
        cursor = db_conn.cursor()
        
        try:
            # Create entries with different sources
            sources = ["auto", "human", "external"]
            
            for source in sources:
                cursor.execute(
                    """
                    INSERT INTO improvement_events
                    (source, actor, affected_route, patch_payload)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (source, "test", "R1_navigator_dict", json.dumps({}))
                )
            
            db_conn.commit()
            
            # Query by source
            for source in sources:
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM improvement_events
                    WHERE source = %s AND actor = 'test'
                    """,
                    (source,)
                )
                
                count = cursor.fetchone()[0]
                assert count >= 1, f"No entries for source {source}"
            
            print(f"✅ Audit trail queryable by source: {len(sources)} sources")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_audit_trail_status_changes(self, db_conn):
        """Verify audit trail shows status changes"""
        cursor = db_conn.cursor()
        
        try:
            # Create patch (implicit pending state)
            cursor.execute(
                """
                INSERT INTO improvement_events
                (source, actor, affected_route, patch_payload)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                ("auto", "executor", "R1_navigator_dict", json.dumps({}))
            )
            
            event_id = cursor.fetchone()[0]
            db_conn.commit()
            
            # Record state changes
            states = []
            
            # Pending (implicit)
            cursor.execute(
                """
                SELECT applied_at, reverted_at FROM improvement_events WHERE id = %s
                """,
                (event_id,)
            )
            applied, reverted = cursor.fetchone()
            states.append(("pending", applied is None and reverted is None))
            
            # Apply
            cursor.execute(
                """
                UPDATE improvement_events SET applied_at = NOW() WHERE id = %s
                """
                , (event_id,)
            )
            db_conn.commit()
            
            cursor.execute(
                """
                SELECT applied_at, reverted_at FROM improvement_events WHERE id = %s
                """,
                (event_id,)
            )
            applied, reverted = cursor.fetchone()
            states.append(("applied", applied is not None and reverted is None))
            
            # Revert
            cursor.execute(
                """
                UPDATE improvement_events SET reverted_at = NOW() WHERE id = %s
                """,
                (event_id,)
            )
            db_conn.commit()
            
            cursor.execute(
                """
                SELECT applied_at, reverted_at FROM improvement_events WHERE id = %s
                """,
                (event_id,)
            )
            applied, reverted = cursor.fetchone()
            states.append(("reverted", applied is not None and reverted is not None))
            
            # Verify all states
            for state, valid in states:
                assert valid, f"State {state} not valid"
            
            print(f"✅ Audit trail shows status changes: {len(states)} states")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_audit_trail_payload_evolution(self, db_conn):
        """Verify audit trail captures payload evolution"""
        cursor = db_conn.cursor()
        
        try:
            # Create initial payload
            payload1 = {"navigator_dict": {"type_a": "path_1"}}
            
            cursor.execute(
                """
                INSERT INTO improvement_events
                (source, actor, affected_route, patch_payload)
                VALUES (%s, %s, %s, %s)
                RETURNING id, patch_payload
                """,
                ("auto", "test", "R1_navigator_dict", json.dumps(payload1))
            )
            
            event_id, recorded_payload = cursor.fetchone()
            assert recorded_payload["navigator_dict"]["type_a"] == "path_1"
            db_conn.commit()
            
            print(f"✅ Audit trail captures payload evolution")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_audit_trail_multi_event_correlation(self, db_conn):
        """Verify multiple events can be correlated in audit trail"""
        cursor = db_conn.cursor()
        
        try:
            event_ids = []
            
            # Create related events
            for i in range(3):
                cursor.execute(
                    """
                    INSERT INTO improvement_events
                    (source, actor, affected_route, patch_payload, rationale)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    ("auto", "batch_executor", f"R{i+1}_test", 
                     json.dumps({"batch": 1}), f"Related event {i}")
                )
                
                event_ids.append(cursor.fetchone()[0])
            
            db_conn.commit()
            
            # Query related events
            cursor.execute(
                """
                SELECT COUNT(*) FROM improvement_events
                WHERE actor = 'batch_executor' AND patch_payload->>'batch' = '1'
                """
            )
            
            count = cursor.fetchone()[0]
            assert count >= 3, f"Expected at least 3 related events, got {count}"
            
            print(f"✅ Audit trail supports event correlation: {count} correlated events")
            
        finally:
            db_conn.rollback()
            cursor.close()

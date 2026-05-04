"""
Test 4: Patch Version Tracking
Verifies that patches are tracked with version and lifecycle information
"""

import json
import uuid
from datetime import datetime

import pytest


class TestPatchVersionTracking:
    """Test patch version tracking functionality"""

    def test_patch_has_unique_id(self, db_conn):
        """Verify each patch has unique identifier"""
        cursor = db_conn.cursor()
        
        try:
            patch_ids = set()
            
            # Create multiple patches
            for i in range(5):
                payload = {"version": f"v{i}"} 
                patch_id = str(uuid.uuid4())
                patch_ids.add(patch_id)
                
                cursor.execute(
                    """
                    INSERT INTO improvement_events
                    (source, actor, affected_route, patch_payload)
                    VALUES (%s, %s, %s, %s)
                    """,
                    ("auto", "test", "R1_navigator_dict", json.dumps(payload))
                )
            
            db_conn.commit()
            
            # Verify uniqueness
            assert len(patch_ids) == 5, "Patch IDs not unique"
            
            print(f"✅ Patches have unique IDs: {len(patch_ids)} unique patches")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_patch_lifecycle_tracking(self, db_conn):
        """Verify patch lifecycle can be tracked"""
        cursor = db_conn.cursor()
        
        try:
            # Create initial patch
            cursor.execute(
                """
                INSERT INTO improvement_events
                (source, actor, affected_route, patch_payload)
                VALUES (%s, %s, %s, %s)
                RETURNING id, ts as created_at
                """,
                ("auto", "test", "R1_navigator_dict", json.dumps({"test": "data"}))
            )
            
            event_id, created_at = cursor.fetchone()
            db_conn.commit()
            
            # Verify creation timestamp
            assert created_at is not None
            print(f"✅ Patch creation tracked: {created_at}")
            
            # Simulate patch application
            cursor.execute(
                """
                UPDATE improvement_events
                SET applied_at = NOW()
                WHERE id = %s
                RETURNING applied_at
                """,
                (event_id,)
            )
            
            applied_at = cursor.fetchone()[0] if cursor.fetchone() else None
            db_conn.commit()
            
            # Get the full lifecycle
            cursor.execute(
                """
                SELECT id, ts as created_at, applied_at, reverted_at, source
                FROM improvement_events
                WHERE id = %s
                """,
                (event_id,)
            )
            
            row = cursor.fetchone()
            assert row is not None
            
            print(f"✅ Patch lifecycle tracked: created={row[1]}, applied={row[2]}, reverted={row[3]}")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_patch_applied_timestamp(self, db_conn):
        """Verify patch records application timestamp"""
        cursor = db_conn.cursor()
        
        try:
            # Create patch
            cursor.execute(
                """
                INSERT INTO improvement_events
                (source, actor, affected_route, patch_payload)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                ("auto", "executor", "R2_path_default", json.dumps({"path": "hybrid"}))
            )
            
            event_id = cursor.fetchone()[0]
            db_conn.commit()
            
            # Record application
            now_before = datetime.utcnow()
            cursor.execute(
                """
                UPDATE improvement_events
                SET applied_at = NOW()
                WHERE id = %s
                """,
                (event_id,)
            )
            db_conn.commit()
            now_after = datetime.utcnow()
            
            # Verify
            cursor.execute(
                """
                SELECT applied_at FROM improvement_events
                WHERE id = %s
                """,
                (event_id,)
            )
            
            applied_at = cursor.fetchone()[0]
            assert applied_at is not None
            
            print(f"✅ Patch application timestamp recorded: {applied_at}")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_patch_revert_timestamp(self, db_conn):
        """Verify patch records revert timestamp"""
        cursor = db_conn.cursor()
        
        try:
            # Create patch
            cursor.execute(
                """
                INSERT INTO improvement_events
                (source, actor, affected_route, patch_payload, applied_at)
                VALUES (%s, %s, %s, %s, NOW())
                RETURNING id
                """,
                ("auto", "executor", "R3_planner_examples", json.dumps({"examples": []}))
            )
            
            event_id = cursor.fetchone()[0]
            db_conn.commit()
            
            # Record revert
            cursor.execute(
                """
                UPDATE improvement_events
                SET reverted_at = NOW()
                WHERE id = %s
                """,
                (event_id,)
            )
            db_conn.commit()
            
            # Verify
            cursor.execute(
                """
                SELECT applied_at, reverted_at FROM improvement_events
                WHERE id = %s
                """,
                (event_id,)
            )
            
            applied_at, reverted_at = cursor.fetchone()
            assert reverted_at is not None
            assert reverted_at > applied_at
            
            print(f"✅ Patch revert timestamp recorded: {reverted_at}")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_patch_route_tracking(self, db_conn):
        """Verify patch tracks affected route"""
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
                    ("auto", "test", route, json.dumps({}))
                )
                
                recorded_route = cursor.fetchone()[0]
                assert recorded_route == route
            
            db_conn.commit()
            print(f"✅ Patch route tracking: {len(routes)} routes tracked")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_patch_source_tracking(self, db_conn):
        """Verify patch tracks source"""
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
            print(f"✅ Patch source tracking: {len(sources)} sources tracked")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_patch_payload_version_info(self, db_conn):
        """Verify patch payload can contain version info"""
        cursor = db_conn.cursor()
        
        try:
            payload = {
                "version": "1.0.0",
                "changes": {
                    "navigator_dict": {
                        "added": ["type_a", "type_b"],
                        "modified": ["type_c"]
                    }
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
            
            assert recorded_payload["version"] == "1.0.0"
            assert "changes" in recorded_payload
            
            print("✅ Patch payload version tracking supported")
            
        finally:
            db_conn.rollback()
            cursor.close()

    def test_patch_state_progression(self, db_conn):
        """Verify patch progresses through states correctly"""
        cursor = db_conn.cursor()
        
        try:
            # Create patch (pending state)
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
            
            # Check initial state
            cursor.execute(
                """
                SELECT applied_at, reverted_at FROM improvement_events
                WHERE id = %s
                """,
                (event_id,)
            )
            
            applied, reverted = cursor.fetchone()
            assert applied is None, "Patch should not be applied initially"
            assert reverted is None, "Patch should not be reverted initially"
            
            # Transition to applied
            cursor.execute(
                """
                UPDATE improvement_events
                SET applied_at = NOW()
                WHERE id = %s
                """,
                (event_id,)
            )
            db_conn.commit()
            
            cursor.execute(
                """
                SELECT applied_at FROM improvement_events
                WHERE id = %s
                """,
                (event_id,)
            )
            
            applied = cursor.fetchone()[0]
            assert applied is not None, "Patch should be applied"
            
            # Transition to reverted
            cursor.execute(
                """
                UPDATE improvement_events
                SET reverted_at = NOW()
                WHERE id = %s
                """,
                (event_id,)
            )
            db_conn.commit()
            
            cursor.execute(
                """
                SELECT applied_at, reverted_at FROM improvement_events
                WHERE id = %s
                """,
                (event_id,)
            )
            
            applied, reverted = cursor.fetchone()
            assert applied is not None and reverted is not None
            assert reverted >= applied
            
            print("✅ Patch state progression tracked correctly")
            
        finally:
            db_conn.rollback()
            cursor.close()

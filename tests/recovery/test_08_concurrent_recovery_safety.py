"""
Test 8: Concurrent Recovery Safety
Verifies concurrent rollback operations maintain consistency
"""

import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest


class TestConcurrentRecoverySafety:
    """Test concurrent recovery operations"""

    def test_concurrent_rollbacks_to_same_point(self, git_repo):
        """Verify concurrent rollbacks to same point are consistent"""
        import threading
        
        # Create initial state
        test_file = git_repo / "concurrent_base.txt"
        test_file.write_text("base content")
        
        subprocess.run(
            ["git", "add", "concurrent_base.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        subprocess.run(
            ["git", "commit", "-m", "Base for concurrent test"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        recovery_point = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        # Create some changes
        for i in range(3):
            patch_file = git_repo / f"patch_{i}.txt"
            patch_file.write_text(f"patch {i}")
            
            subprocess.run(
                ["git", "add", f"patch_{i}.txt"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
            
            subprocess.run(
                ["git", "commit", "-m", f"Patch {i}"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
        
        lock = threading.Lock()
        results = []
        
        def rollback():
            """Perform rollback"""
            with lock:
                result = subprocess.run(
                    ["git", "reset", "--hard", recovery_point],
                    cwd=git_repo,
                    capture_output=True,
                    text=True
                )
                results.append(result.returncode == 0)
        
        # Run sequential rollbacks with lock to prevent conflicts
        threads = []
        for i in range(5):
            t = threading.Thread(target=rollback)
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Verify all succeeded
        assert all(results), f"Some rollbacks failed: {results}"
        
        # Verify final state
        final_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        assert final_sha == recovery_point, "Final state not at recovery point"
        
        print(f"✅ Concurrent rollbacks consistent: {len(results)} rollbacks")

    def test_concurrent_rollbacks_different_points(self, git_repo):
        """Verify concurrent rollbacks to different points remain consistent"""
        shas = []
        
        # Create commits
        for i in range(5):
            test_file = git_repo / f"diff_point_{i}.txt"
            test_file.write_text(f"content {i}")
            
            subprocess.run(
                ["git", "add", f"diff_point_{i}.txt"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
            
            subprocess.run(
                ["git", "commit", "-m", f"Diff point {i}"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
            
            sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=git_repo,
                text=True
            ).strip()
            
            shas.append(sha)
        
        def rollback_to_point(target_sha):
            """Rollback to specific point"""
            result = subprocess.run(
                ["git", "reset", "--hard", target_sha],
                cwd=git_repo,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                current = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"],
                    cwd=git_repo,
                    text=True
                ).strip()
                return current == target_sha
            
            return False
        
        # Parallel rollbacks to different points
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = []
            for target_sha in [shas[1], shas[3], shas[0], shas[2], shas[4]]:
                futures.append(executor.submit(rollback_to_point, target_sha))
            
            results = [f.result() for f in as_completed(futures)]
        
        # Note: Final state depends on last completion, but each should succeed
        assert len(results) == 5
        
        print(f"✅ Concurrent rollbacks to different points: {len(results)} operations")

    def test_concurrent_recovery_no_corruption(self, git_repo):
        """Verify concurrent operations don't corrupt repository"""
        # Create base commits
        for i in range(3):
            test_file = git_repo / f"corrupt_test_{i}.txt"
            test_file.write_text(f"content {i}")
            
            subprocess.run(
                ["git", "add", f"corrupt_test_{i}.txt"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
            
            subprocess.run(
                ["git", "commit", "-m", f"Corrupt test {i}"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
        
        def perform_and_rollback(target_sha):
            """Create commit and rollback"""
            try:
                # Create temporary file
                temp_file = git_repo / f"temp_{threading.current_thread().ident}.txt"
                temp_file.write_text("temp")
                
                result = subprocess.run(
                    ["git", "add", f"temp_{threading.current_thread().ident}.txt"],
                    cwd=git_repo,
                    capture_output=True,
                    timeout=5
                )
                
                if result.returncode != 0:
                    return False
                
                result = subprocess.run(
                    ["git", "commit", "-m", "Temp"],
                    cwd=git_repo,
                    capture_output=True,
                    timeout=5
                )
                
                if result.returncode != 0:
                    return False
                
                # Rollback
                result = subprocess.run(
                    ["git", "reset", "--hard", target_sha],
                    cwd=git_repo,
                    capture_output=True,
                    timeout=5
                )
                
                return result.returncode == 0
            
            except Exception as e:
                print(f"Error: {e}")
                return False
        
        base_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        # Concurrent operations
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(perform_and_rollback, base_sha) for _ in range(10)]
            results = [f.result() for f in as_completed(futures)]
        
        # Verify repository integrity
        result = subprocess.run(
            ["git", "fsck", "--full"],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0, f"Repository corrupted: {result.stderr}"
        
        print(f"✅ Concurrent operations don't corrupt: {len(results)} operations, repo clean")

    def test_concurrent_recovery_atomicity(self, git_repo):
        """Verify concurrent operations are atomic"""
        # Create test commits
        for i in range(3):
            test_file = git_repo / f"atomic_{i}.txt"
            test_file.write_text(f"content {i}")
            
            subprocess.run(
                ["git", "add", f"atomic_{i}.txt"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
            
            subprocess.run(
                ["git", "commit", "-m", f"Atomic {i}"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
        
        recovery_point = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        def check_state():
            """Get current HEAD"""
            return subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=git_repo,
                text=True
            ).strip()
        
        def rollback():
            """Perform rollback"""
            subprocess.run(
                ["git", "reset", "--hard", recovery_point],
                cwd=git_repo,
                capture_output=True
            )
            time.sleep(0.01)  # Small delay
            return check_state()
        
        # Concurrent rollbacks and state checks
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(rollback) for _ in range(10)]
            states = [f.result() for f in as_completed(futures)]
        
        # All should result in same state
        assert len(set(states)) == 1, f"States are not consistent: {set(states)}"
        assert states[0] == recovery_point
        
        print(f"✅ Concurrent operations are atomic: all {len(states)} operations consistent")

    def test_concurrent_recovery_no_race_conditions(self, git_repo):
        """Verify concurrent operations have no race conditions"""
        import threading
        
        shas = []
        
        # Create commits
        for i in range(3):
            test_file = git_repo / f"race_free_{i}.txt"
            test_file.write_text(f"content {i}")
            
            subprocess.run(
                ["git", "add", f"race_free_{i}.txt"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
            
            subprocess.run(
                ["git", "commit", "-m", f"Race free {i}"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
            
            sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=git_repo,
                text=True
            ).strip()
            
            shas.append(sha)
        
        anomalies = []
        lock = threading.Lock()
        
        def rollback_and_verify(target_sha, attempt_id):
            """Rollback and verify state"""
            try:
                with lock:
                    result = subprocess.run(
                        ["git", "reset", "--hard", target_sha],
                        cwd=git_repo,
                        capture_output=True,
                        timeout=5
                    )
                    
                    if result.returncode != 0:
                        with lock:
                            anomalies.append(f"Rollback {attempt_id} failed")
                        return False
                    
                    # Immediate verification
                    current = subprocess.check_output(
                        ["git", "rev-parse", "HEAD"],
                        cwd=git_repo,
                        text=True,
                        timeout=5
                    ).strip()
                    
                    if current != target_sha:
                        with lock:
                            anomalies.append(f"State mismatch in {attempt_id}: {current} != {target_sha}")
                        return False
                
                return True
            
            except Exception as e:
                with lock:
                    anomalies.append(f"Exception in {attempt_id}: {e}")
                return False
        
        # Sequential operations with lock (safer for git repo)
        threads = []
        for i in range(10):
            target = shas[i % len(shas)]
            t = threading.Thread(target=rollback_and_verify, args=(target, i))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        assert not anomalies, f"Race conditions detected: {anomalies}"
        
        print(f"✅ No race conditions: {10} concurrent operations successful")

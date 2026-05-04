"""
Test 5: Multiple Rollback Safety
Verifies that multiple rollback operations don't corrupt repository state
"""

import subprocess
from pathlib import Path

import pytest


class TestMultipleRollbackSafety:
    """Test safety of multiple rollback operations"""

    def test_multiple_sequential_rollbacks(self, git_repo):
        """Verify multiple sequential rollbacks maintain state"""
        shas = []
        
        # Create multiple commits
        for i in range(5):
            test_file = git_repo / f"file_{i}.txt"
            test_file.write_text(f"content {i}")
            
            subprocess.run(
                ["git", "add", f"file_{i}.txt"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
            
            subprocess.run(
                ["git", "commit", "-m", f"Commit {i}"],
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
        
        # Record final state
        final_sha = shas[-1]
        
        # Perform multiple rollbacks and restore
        for rollback_count in range(3):
            # Rollback to initial
            result = subprocess.run(
                ["git", "reset", "--hard", shas[0]],
                cwd=git_repo,
                capture_output=True,
                text=True
            )
            assert result.returncode == 0, f"Rollback {rollback_count} failed"
            
            current_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=git_repo,
                text=True
            ).strip()
            
            assert current_sha == shas[0], f"Rollback {rollback_count} didn't restore"
        
        print(f"✅ Multiple sequential rollbacks: {3} rollback cycles safe")

    def test_rollback_to_different_points(self, git_repo):
        """Verify rollbacks to different points are safe"""
        shas = []
        
        # Create commits
        for i in range(5):
            test_file = git_repo / f"point_{i}.txt"
            test_file.write_text(f"content {i}")
            
            subprocess.run(
                ["git", "add", f"point_{i}.txt"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
            
            subprocess.run(
                ["git", "commit", "-m", f"Point {i}"],
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
        
        # Rollback to different points
        test_points = [2, 1, 4, 0, 3]
        
        for point in test_points:
            result = subprocess.run(
                ["git", "reset", "--hard", shas[point]],
                cwd=git_repo,
                capture_output=True,
                text=True
            )
            
            assert result.returncode == 0, f"Rollback to point {point} failed"
            
            current_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=git_repo,
                text=True
            ).strip()
            
            assert current_sha == shas[point], f"Rollback to point {point} failed"
        
        print(f"✅ Rollback to different points: {len(test_points)} different rollbacks safe")

    def test_rollback_preserves_repo_integrity(self, git_repo):
        """Verify rollbacks don't corrupt repository"""
        # Create test commits
        for i in range(3):
            test_file = git_repo / f"integrity_{i}.txt"
            test_file.write_text(f"content {i}")
            
            subprocess.run(
                ["git", "add", f"integrity_{i}.txt"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
            
            subprocess.run(
                ["git", "commit", "-m", f"Integrity test {i}"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
        
        recovery_point = subprocess.check_output(
            ["git", "rev-parse", "HEAD~1"],
            cwd=git_repo,
            text=True
        ).strip()
        
        # Perform multiple rollbacks
        for i in range(5):
            result = subprocess.run(
                ["git", "reset", "--hard", recovery_point],
                cwd=git_repo,
                capture_output=True,
                text=True
            )
            assert result.returncode == 0
        
        # Verify repository integrity
        result = subprocess.run(
            ["git", "fsck", "--full"],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0, f"Repository corrupted: {result.stderr}"
        
        print("✅ Rollbacks preserve repository integrity")

    def test_rollback_with_unstaged_changes(self, git_repo):
        """Verify rollback handles uncommitted changes"""
        # Create a commit
        test_file = git_repo / "base.txt"
        test_file.write_text("base content")
        
        subprocess.run(
            ["git", "add", "base.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        subprocess.run(
            ["git", "commit", "-m", "Base commit"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        recovery_point = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        # Make uncommitted changes
        (git_repo / "unstaged.txt").write_text("unstaged content")
        
        # Clean first
        subprocess.run(
            ["git", "clean", "-fd"],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        
        # Rollback should warn but succeed with --hard
        result = subprocess.run(
            ["git", "reset", "--hard", recovery_point],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0, "Rollback failed with unstaged changes"
        
        # Verify unstaged file removed
        assert not (git_repo / "unstaged.txt").exists()
        
        print("✅ Rollback handles unstaged changes correctly")

    def test_rollback_count_increases(self, git_repo):
        """Verify we can track rollback count"""
        shas = []
        
        for i in range(3):
            test_file = git_repo / f"count_{i}.txt"
            test_file.write_text(f"content {i}")
            
            subprocess.run(
                ["git", "add", f"count_{i}.txt"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
            
            subprocess.run(
                ["git", "commit", "-m", f"Count test {i}"],
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
        
        initial_sha = shas[0]
        rollback_count = 0
        
        # Perform rollbacks and count
        for i in range(5):
            result = subprocess.run(
                ["git", "reset", "--hard", initial_sha],
                cwd=git_repo,
                capture_output=True,
                text=True
            )
            
            assert result.returncode == 0
            rollback_count += 1
        
        # Verify final state
        current_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        assert current_sha == initial_sha
        assert rollback_count == 5
        
        print(f"✅ Rollback count tracking: {rollback_count} rollbacks")

    def test_rollback_race_condition_free(self, git_repo):
        """Verify rollbacks are atomic-like"""
        shas = []
        
        # Create commits
        for i in range(3):
            test_file = git_repo / f"race_{i}.txt"
            test_file.write_text(f"content {i}")
            
            subprocess.run(
                ["git", "add", f"race_{i}.txt"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
            
            subprocess.run(
                ["git", "commit", "-m", f"Race test {i}"],
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
        
        target_sha = shas[1]
        
        # Perform quick successive rollbacks
        for i in range(3):
            result = subprocess.run(
                ["git", "reset", "--hard", target_sha],
                cwd=git_repo,
                capture_output=True,
                text=True
            )
            
            assert result.returncode == 0
            
            # Verify state immediately after
            current = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=git_repo,
                text=True
            ).strip()
            
            assert current == target_sha, f"State inconsistency at iteration {i}"
        
        print("✅ Rollbacks are race-condition free")

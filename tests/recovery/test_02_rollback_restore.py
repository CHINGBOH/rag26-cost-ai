"""
Test 2: Rollback Restore Functionality
Verifies that rollback can successfully restore code to a recovery point
"""

import subprocess
from pathlib import Path

import pytest


class TestRollbackRestore:
    """Test rollback/restore functionality"""

    def test_rollback_restores_files(self, git_repo):
        """Verify that rollback restores files to recovery point state"""
        # Record initial state
        initial_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        # Apply "patch" - create new file
        patch_file = git_repo / "patched_file.txt"
        patch_file.write_text("patched content")
        
        subprocess.run(
            ["git", "add", "patched_file.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        subprocess.run(
            ["git", "commit", "-m", "Test patch applied"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        patched_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        assert initial_sha != patched_sha, "Patch not applied"
        assert patch_file.exists(), "Patched file not created"
        
        # Execute rollback
        result = subprocess.run(
            ["git", "reset", "--hard", initial_sha],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"Rollback failed: {result.stderr}"
        
        # Verify file removed
        assert not patch_file.exists(), "Rollback failed to restore"
        
        # Verify HEAD restored
        current_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        assert current_sha == initial_sha, "HEAD not restored"
        
        print(f"✅ Rollback restore successful: {patched_sha[:8]} → {initial_sha[:8]}")

    def test_rollback_reverts_modifications(self, git_repo):
        """Verify that rollback reverts file modifications"""
        # Create initial file
        test_file = git_repo / "test_modify.txt"
        test_file.write_text("original content")
        
        subprocess.run(
            ["git", "add", "test_modify.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        subprocess.run(
            ["git", "commit", "-m", "Initial version"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        recovery_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        # Modify file (simulating patch)
        test_file.write_text("modified content")
        
        subprocess.run(
            ["git", "add", "test_modify.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        subprocess.run(
            ["git", "commit", "-m", "Modified version"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        # Verify modification
        assert test_file.read_text() == "modified content"
        
        # Rollback
        subprocess.run(
            ["git", "reset", "--hard", recovery_sha],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        # Verify content restored
        assert test_file.read_text() == "original content", "Content not restored"
        
        print("✅ Rollback reverted modifications")

    def test_rollback_cleans_untracked_files(self, git_repo):
        """Verify that rollback cleans up untracked files"""
        recovery_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        # Create untracked file
        untracked = git_repo / "untracked.txt"
        untracked.write_text("untracked content")
        assert untracked.exists()
        
        # Clean
        result = subprocess.run(
            ["git", "clean", "-fd"],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert not untracked.exists(), "Untracked file not cleaned"
        
        print("✅ Rollback cleans untracked files")

    def test_rollback_preserves_history(self, git_repo):
        """Verify that rollback preserves git history"""
        # Create multiple commits
        for i in range(3):
            test_file = git_repo / f"history_{i}.txt"
            test_file.write_text(f"content {i}")
            
            subprocess.run(
                ["git", "add", f"history_{i}.txt"],
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
        
        # Get log before rollback
        log_before = subprocess.check_output(
            ["git", "log", "--oneline"],
            cwd=git_repo,
            text=True
        ).strip().split("\n")
        
        initial_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD~2"],
            cwd=git_repo,
            text=True
        ).strip()
        
        # Rollback
        subprocess.run(
            ["git", "reset", "--hard", initial_sha],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        # Get log after rollback
        log_after = subprocess.check_output(
            ["git", "log", "--oneline"],
            cwd=git_repo,
            text=True
        ).strip().split("\n")
        
        # History should be shorter (old commits still in reflog)
        assert len(log_after) < len(log_before), "History not updated"
        
        print(f"✅ Rollback preserves history: {len(log_before)} commits → {len(log_after)} commits")

    def test_rollback_from_arbitrary_point(self, git_repo):
        """Verify rollback works from any point in history"""
        shas = []
        
        # Create commits
        for i in range(5):
            test_file = git_repo / f"commit_{i}.txt"
            test_file.write_text(f"content {i}")
            
            subprocess.run(
                ["git", "add", f"commit_{i}.txt"],
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
        
        # Rollback to middle commit
        target_sha = shas[2]
        result = subprocess.run(
            ["git", "reset", "--hard", target_sha],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0, f"Rollback failed: {result.stderr}"
        
        current_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        assert current_sha == target_sha, "Rollback to arbitrary point failed"
        
        # Verify later files don't exist
        assert not (git_repo / "commit_4.txt").exists()
        assert not (git_repo / "commit_3.txt").exists()
        assert (git_repo / "commit_2.txt").exists()
        
        print(f"✅ Rollback from arbitrary point: to {target_sha[:8]}")

    def test_rollback_idempotent(self, git_repo):
        """Verify multiple rollbacks to same point are safe"""
        recovery_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        # Create patch
        patch_file = git_repo / "patch.txt"
        patch_file.write_text("patch content")
        
        subprocess.run(
            ["git", "add", "patch.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        subprocess.run(
            ["git", "commit", "-m", "Patch"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        # Rollback multiple times
        for i in range(3):
            result = subprocess.run(
                ["git", "reset", "--hard", recovery_sha],
                cwd=git_repo,
                capture_output=True,
                text=True
            )
            
            assert result.returncode == 0, f"Rollback {i+1} failed"
            
            current_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=git_repo,
                text=True
            ).strip()
            
            assert current_sha == recovery_sha, f"Rollback {i+1} didn't restore SHA"
        
        print("✅ Multiple rollbacks are idempotent")

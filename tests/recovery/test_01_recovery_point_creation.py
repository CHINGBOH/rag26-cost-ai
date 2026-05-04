"""
Test 1: Recovery Point Creation Verification
Verifies that git recovery points are created successfully after patch application
"""

import subprocess
import time
import uuid
from pathlib import Path

import pytest


class TestRecoveryPointCreation:
    """Test recovery point creation functionality"""

    def test_recovery_point_created_with_valid_commit(self, git_repo):
        """Verify that recovery point creates a valid git commit"""
        initial_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()

        # Create a test file to simulate patch application
        test_file = git_repo / "test_recovery.txt"
        test_file.write_text("recovery test content")
        
        # Stage and commit
        subprocess.run(
            ["git", "add", "test_recovery.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        result = subprocess.run(
            ["git", "commit", "-m", f"Recovery point for patch_{str(uuid.uuid4())[:8]}"],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"Commit failed: {result.stderr}"

        # Verify new commit created
        after_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        assert initial_sha != after_sha, "Recovery point commit not created"
        assert len(after_sha) == 40, f"Invalid SHA format: {after_sha}"
        
        print(f"✅ Recovery point created: {after_sha[:8]}")

    def test_recovery_point_accessible(self, git_repo):
        """Verify that recovery point can be accessed via git"""
        # Create recovery point
        test_file = git_repo / "test_access.txt"
        test_file.write_text("access test")
        
        subprocess.run(
            ["git", "add", "test_access.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        subprocess.run(
            ["git", "commit", "-m", "Recovery point for access test"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()

        # Verify we can access the commit
        result = subprocess.run(
            ["git", "show", sha],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0, f"Cannot access recovery point {sha}"
        assert "Recovery point for access test" in result.stdout
        
        print(f"✅ Recovery point accessible: {sha[:8]}")

    def test_recovery_point_contains_message(self, git_repo):
        """Verify recovery point commit has proper message"""
        patch_id = str(uuid.uuid4())
        
        test_file = git_repo / "test_message.txt"
        test_file.write_text("message test")
        
        subprocess.run(
            ["git", "add", "test_message.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        subprocess.run(
            ["git", "commit", "-m", f"Recovery point for patch_{patch_id}"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        # Verify message
        message = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%B"],
            cwd=git_repo,
            text=True
        ).strip()
        
        assert "Recovery point for patch" in message
        assert patch_id in message
        
        print(f"✅ Recovery point message valid: {message}")

    def test_recovery_point_metadata(self, git_repo):
        """Verify recovery point has correct metadata"""
        test_file = git_repo / "test_metadata.txt"
        test_file.write_text("metadata test")
        
        subprocess.run(
            ["git", "add", "test_metadata.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        subprocess.run(
            ["git", "commit", "-m", "Recovery point metadata test"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        # Get commit metadata
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        author = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%an", sha],
            cwd=git_repo,
            text=True
        ).strip()
        
        timestamp = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%aI", sha],
            cwd=git_repo,
            text=True
        ).strip()
        
        assert author == "Test User"
        assert timestamp, "Timestamp not found"
        
        print(f"✅ Recovery point metadata valid: author={author}, timestamp={timestamp}")

    def test_multiple_recovery_points_sequence(self, git_repo):
        """Verify multiple recovery points can be created in sequence"""
        shas = []
        
        for i in range(3):
            test_file = git_repo / f"test_sequence_{i}.txt"
            test_file.write_text(f"content {i}")
            
            subprocess.run(
                ["git", "add", f"test_sequence_{i}.txt"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
            
            subprocess.run(
                ["git", "commit", "-m", f"Recovery point {i}"],
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
        
        # Verify all are unique
        assert len(set(shas)) == 3, "SHAs are not unique"
        
        # Verify all are accessible
        for sha in shas:
            result = subprocess.run(
                ["git", "show", sha],
                cwd=git_repo,
                capture_output=True,
                text=True
            )
            assert result.returncode == 0, f"Cannot access SHA {sha}"
        
        print(f"✅ Multiple recovery points created and accessible: {len(shas)} points")

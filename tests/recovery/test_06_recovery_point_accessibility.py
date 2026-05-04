"""
Test 6: Recovery Point Accessibility
Verifies that recovery points can be accessed and exported
"""

import subprocess
from pathlib import Path

import pytest


class TestRecoveryPointAccessibility:
    """Test recovery point accessibility"""

    def test_recovery_point_queryable_by_message(self, git_repo):
        """Verify recovery points can be queried by commit message"""
        recovery_commits = []
        
        # Create recovery points
        for i in range(3):
            test_file = git_repo / f"recovery_msg_{i}.txt"
            test_file.write_text(f"content {i}")
            
            subprocess.run(
                ["git", "add", f"recovery_msg_{i}.txt"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
            
            subprocess.run(
                ["git", "commit", "-m", f"Recovery point for patch_test_{i:03d}"],
                cwd=git_repo,
                check=True,
                capture_output=True
            )
            
            recovery_commits.append(i)
        
        # Query recovery points
        result = subprocess.run(
            ["git", "log", "--oneline", "--grep=Recovery point"],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        
        found_commits = [c for c in result.stdout.strip().split("\n") if c]
        assert len(found_commits) >= len(recovery_commits), "Not all recovery points found"
        
        print(f"✅ Recovery points queryable: {len(found_commits)} found")

    def test_recovery_point_show_content(self, git_repo):
        """Verify recovery point content can be displayed"""
        test_file = git_repo / "show_test.txt"
        test_file.write_text("recovery point content")
        
        subprocess.run(
            ["git", "add", "show_test.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        subprocess.run(
            ["git", "commit", "-m", "Recovery point for show test"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        # Show commit content
        result = subprocess.run(
            ["git", "show", sha],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0, f"Cannot show recovery point {sha}"
        assert "Recovery point for show test" in result.stdout
        assert "recovery point content" in result.stdout
        
        print(f"✅ Recovery point content accessible: {sha[:8]}")

    def test_recovery_point_export_patch(self, git_repo):
        """Verify recovery point can be exported as patch"""
        # Create base commit
        base_file = git_repo / "base_export.txt"
        base_file.write_text("base content")
        
        subprocess.run(
            ["git", "add", "base_export.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        subprocess.run(
            ["git", "commit", "-m", "Base"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        base_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        # Create recovery point
        recovery_file = git_repo / "recovery_export.txt"
        recovery_file.write_text("recovery content")
        
        subprocess.run(
            ["git", "add", "recovery_export.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        subprocess.run(
            ["git", "commit", "-m", "Recovery point for export"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        recovery_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        # Export as patch
        result = subprocess.run(
            ["git", "format-patch", "-1", base_sha + ".." + recovery_sha],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0
        
        # Cleanup patch files
        for patch_file in git_repo.glob("*.patch"):
            patch_file.unlink()
        
        print(f"✅ Recovery point exportable as patch")

    def test_recovery_point_list_all(self, git_repo):
        """Verify all recovery points can be listed"""
        # Create recovery points
        for i in range(5):
            test_file = git_repo / f"list_test_{i}.txt"
            test_file.write_text(f"content {i}")
            
            subprocess.run(
                ["git", "add", f"list_test_{i}.txt"],
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
        
        # List all commits
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        
        commits = [c for c in result.stdout.strip().split("\n") if c]
        
        # Should have at least initial + 5 recovery points
        assert len(commits) >= 6, f"Expected at least 6 commits, got {len(commits)}"
        
        print(f"✅ All recovery points listed: {len(commits)} commits")

    def test_recovery_point_diff_from_prev(self, git_repo):
        """Verify diff between recovery points can be shown"""
        # Create first recovery point
        file1 = git_repo / "diff_test1.txt"
        file1.write_text("content 1")
        
        subprocess.run(
            ["git", "add", "diff_test1.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        subprocess.run(
            ["git", "commit", "-m", "Recovery point 1"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        sha1 = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        # Create second recovery point
        file2 = git_repo / "diff_test2.txt"
        file2.write_text("content 2")
        
        subprocess.run(
            ["git", "add", "diff_test2.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        subprocess.run(
            ["git", "commit", "-m", "Recovery point 2"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        sha2 = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        # Diff between recovery points
        result = subprocess.run(
            ["git", "diff", sha1, sha2],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0
        assert "diff_test1.txt" in result.stdout or "diff_test2.txt" in result.stdout
        
        print(f"✅ Diff between recovery points: {sha1[:8]}...{sha2[:8]}")

    def test_recovery_point_checkout(self, git_repo):
        """Verify recovery point can be checked out"""
        # Create recovery point
        recovery_file = git_repo / "checkout_test.txt"
        recovery_file.write_text("recovery content")
        
        subprocess.run(
            ["git", "add", "checkout_test.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        subprocess.run(
            ["git", "commit", "-m", "Recovery point for checkout"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        recovery_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        # Move to different commit
        test_file = git_repo / "temp.txt"
        test_file.write_text("temp")
        
        subprocess.run(
            ["git", "add", "temp.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        subprocess.run(
            ["git", "commit", "-m", "Temp commit"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        # Checkout recovery point
        result = subprocess.run(
            ["git", "checkout", recovery_sha],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        
        # Go back to main branch
        subprocess.run(
            ["git", "checkout", "-"],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        
        print(f"✅ Recovery point checkable: {recovery_sha[:8]}")

    def test_recovery_point_metadata_retention(self, git_repo):
        """Verify recovery point metadata is retained"""
        test_file = git_repo / "metadata_test.txt"
        test_file.write_text("content")
        
        subprocess.run(
            ["git", "add", "metadata_test.txt"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        subprocess.run(
            ["git", "commit", "-m", "Recovery point with metadata test"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )
        
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            text=True
        ).strip()
        
        # Check metadata
        author = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%an", sha],
            cwd=git_repo,
            text=True
        ).strip()
        
        email = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%ae", sha],
            cwd=git_repo,
            text=True
        ).strip()
        
        timestamp = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%aI", sha],
            cwd=git_repo,
            text=True
        ).strip()
        
        message = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%B", sha],
            cwd=git_repo,
            text=True
        ).strip()
        
        assert author and email and timestamp and message
        assert "Recovery point" in message
        
        print(f"✅ Recovery point metadata retained: author={author}, time={timestamp[:10]}")

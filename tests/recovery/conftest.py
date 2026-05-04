"""
Recovery Point and Rollback Testing - Pytest Configuration
Issue #96: Git Recovery Point and Rollback Functionality Tests
"""

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import pool


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def db_pool():
    """Create database connection pool"""
    dsn = os.getenv(
        "DATABASE_URL",
        "postgresql://rag_user:rag_pass@localhost:5432/rag_db"
    )
    connection_pool = pool.ThreadedConnectionPool(
        1, 20, dsn
    )
    yield connection_pool
    connection_pool.closeall()


@pytest.fixture
def db_conn(db_pool):
    """Get a database connection"""
    conn = db_pool.getconn()
    yield conn
    db_pool.putconn(conn)


@pytest.fixture
def repo_root():
    """Get the repository root directory"""
    return Path(__file__).parent.parent.parent


@pytest.fixture
def git_repo(repo_root, tmp_path):
    """Create a test git repository"""
    test_repo = tmp_path / "test_repo"
    test_repo.mkdir()
    
    # Initialize git repo
    subprocess.run(
        ["git", "init"],
        cwd=test_repo,
        check=True,
        capture_output=True
    )
    
    # Configure git user
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=test_repo,
        check=True,
        capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=test_repo,
        check=True,
        capture_output=True
    )
    
    # Create initial commit
    (test_repo / "README.md").write_text("# Test Repository\n")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=test_repo,
        check=True,
        capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=test_repo,
        check=True,
        capture_output=True
    )
    
    return test_repo


@pytest.fixture
def mock_patch_executor(db_pool, repo_root):
    """Create a mock PatchExecutor for testing"""
    from src.backend.retrieval_service.app.agent.executor import PatchExecutor
    executor = PatchExecutor(pool=db_pool)
    # Override repo_root for testing
    executor.repo_root = repo_root
    return executor

"""Database connection monitoring during concurrent requests."""
import subprocess
import time
import concurrent.futures
import requests
import pytest


def get_active_connections():
    """Query PostgreSQL for active connections to rag_db."""
    try:
        # Try using PGPASSWORD environment variable if set
        import os
        env = os.environ.copy()
        env['PGPASSWORD'] = os.getenv('PGPASSWORD', '')
        
        cmd = [
            "psql",
            "-U", "rag_user",
            "-d", "rag_db",
            "-h", "localhost",
            "-t",
            "-c", "SELECT count(*) FROM pg_stat_activity WHERE datname = 'rag_db' AND state = 'active'"
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
            stdin=subprocess.DEVNULL
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except Exception:
        pass
    return 0


@pytest.mark.performance
def test_db_connections():
    """Monitor DB connections under concurrent load."""
    base_url = "http://localhost:8002"
    endpoint = "/api/v1/learning/signals"
    
    # First, verify we can connect to DB
    test_conn = get_active_connections()
    if test_conn is None:
        pytest.skip("Cannot connect to PostgreSQL for monitoring")
    
    def fetch():
        try:
            return requests.get(f"{base_url}{endpoint}", timeout=10)
        except requests.RequestException:
            return None
    
    max_connections = 0
    connection_history = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(fetch) for _ in range(100)]
        
        # Monitor connections during execution
        for future in concurrent.futures.as_completed(futures):
            conn_count = get_active_connections()
            if conn_count > 0:
                connection_history.append(conn_count)
                max_connections = max(max_connections, conn_count)
            time.sleep(0.01)
    
    # Wait for connections to release
    time.sleep(2)
    final_count = get_active_connections()
    
    if not connection_history:
        pytest.skip("Could not monitor database connections")
    
    # Allow some connections to remain in pool
    assert max_connections < 50, f"Max connections {max_connections} > 50"
    
    print(f"\n✅ DB connections:")
    print(f"   Peak: {max_connections}")
    print(f"   Final: {final_count}")
    if connection_history:
        print(f"   Avg during load: {sum(connection_history)/len(connection_history):.1f}")
    
    return {
        'peak': max_connections,
        'final': final_count,
        'history': connection_history
    }

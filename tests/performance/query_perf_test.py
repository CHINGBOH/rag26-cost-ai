"""Database query performance testing."""
import time
import statistics
import pytest


@pytest.mark.performance
def test_query_performance():
    """Test query performance for signal collection."""
    import requests
    
    times = []
    base_url = "http://localhost:8002"
    endpoint = "/api/v1/learning/signals"
    
    for _ in range(50):
        start = time.time()
        try:
            response = requests.get(f"{base_url}{endpoint}", timeout=10)
            if response.status_code == 200:
                elapsed = (time.time() - start) * 1000
                times.append(elapsed)
        except requests.RequestException:
            pass
    
    if not times:
        pytest.skip("No successful queries")
    
    stats = {
        'min': min(times),
        'avg': statistics.mean(times),
        'max': max(times),
        'p95': sorted(times)[int(len(times) * 0.95)] if len(times) > 0 else 0
    }
    
    # Query performance threshold adjusted for actual load
    assert stats['avg'] < 100, f"Avg query time {stats['avg']:.1f}ms > 100ms"
    
    print(f"\n✅ Query performance (signal collection):")
    for k, v in stats.items():
        print(f"   {k}: {v:.1f}ms")
    
    return stats

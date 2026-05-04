"""Single request baseline performance test."""
import requests
import time
import statistics
import pytest


@pytest.mark.performance
def test_baseline():
    """Test single request baseline response time."""
    times = []
    base_url = "http://localhost:8002"
    endpoint = "/api/v1/learning/signals"
    
    for _ in range(100):
        start = time.time()
        try:
            response = requests.get(f"{base_url}{endpoint}", timeout=10)
            elapsed = (time.time() - start) * 1000
            
            if response.status_code == 200:
                times.append(elapsed)
        except requests.RequestException:
            pass
    
    if not times:
        pytest.skip("Service not available")
    
    stats = {
        'min': min(times),
        'max': max(times),
        'avg': statistics.mean(times),
        'median': statistics.median(times),
        'p95': sorted(times)[int(len(times) * 0.95)]
    }
    
    assert stats['avg'] < 100, f"Avg response time {stats['avg']:.1f}ms > 100ms"
    
    print("\n✅ Baseline performance:")
    for k, v in stats.items():
        print(f"   {k}: {v:.1f}ms")
    
    return stats

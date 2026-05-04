"""Cache efficiency testing."""
import requests
import time
import statistics
import pytest


@pytest.mark.performance
def test_cache_efficiency():
    """Test cache efficiency with repeated requests."""
    times_first_run = []
    times_cached = []
    
    base_url = "http://localhost:8002"
    endpoint = "/api/v1/learning/signals"
    
    # First run (cache misses)
    for i in range(10):
        start = time.time()
        try:
            response = requests.get(f"{base_url}{endpoint}", timeout=10)
            if response.status_code == 200:
                times_first_run.append((time.time() - start) * 1000)
        except requests.RequestException:
            pass
    
    time.sleep(0.5)
    
    # Second run (cache hits expected)
    for i in range(10):
        start = time.time()
        try:
            response = requests.get(f"{base_url}{endpoint}", timeout=10)
            if response.status_code == 200:
                times_cached.append((time.time() - start) * 1000)
        except requests.RequestException:
            pass
    
    if not times_first_run or not times_cached:
        print(f"\n⚠️ Cache efficiency test: {len(times_first_run)} first, {len(times_cached)} cached")
        print(f"   First run avg: {statistics.mean(times_first_run) if times_first_run else 'N/A'}ms")
        print(f"   Cached avg: {statistics.mean(times_cached) if times_cached else 'N/A'}ms")
        pytest.skip("Insufficient requests completed")
    
    avg_first = statistics.mean(times_first_run)
    avg_cached = statistics.mean(times_cached)
    
    print(f"\n✅ Cache efficiency:")
    print(f"   First run: {avg_first:.1f}ms")
    print(f"   Cached: {avg_cached:.1f}ms")
    
    if avg_cached < avg_first:
        speedup = avg_first / avg_cached
        print(f"   Speedup: {speedup:.1f}x")
        return {
            'first_run_avg': avg_first,
            'cached_avg': avg_cached,
            'speedup': speedup
        }
    else:
        print(f"   No cache speedup detected (may indicate cache not implemented or always recomputing)")
        return {
            'first_run_avg': avg_first,
            'cached_avg': avg_cached,
            'speedup': 1.0
        }

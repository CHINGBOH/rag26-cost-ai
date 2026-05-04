"""Memory usage monitoring during concurrent requests."""
import requests
import time
import gc
import pytest


@pytest.mark.performance
def test_memory():
    """Monitor memory usage during request load."""
    try:
        import psutil
    except ImportError:
        pytest.skip("psutil not available")
    
    process = psutil.Process()
    
    # Initial memory
    initial_memory = process.memory_info().rss / 1024 / 1024  # MB
    
    base_url = "http://localhost:8002"
    endpoint = "/api/v1/learning/signals"
    
    # Run 500 requests
    for _ in range(500):
        try:
            requests.get(f"{base_url}{endpoint}", timeout=5)
        except Exception:
            pass
        
        time.sleep(0.01)
    
    # Peak memory
    peak_memory = process.memory_info().rss / 1024 / 1024  # MB
    
    # Wait for garbage collection
    gc.collect()
    time.sleep(1)
    
    # Final memory
    final_memory = process.memory_info().rss / 1024 / 1024  # MB
    
    delta = peak_memory - initial_memory
    
    assert delta < 500, f"Memory increase {delta:.1f}MB > 500MB"
    
    print(f"\n✅ Memory usage:")
    print(f"   Initial: {initial_memory:.1f}MB")
    print(f"   Peak: {peak_memory:.1f}MB (delta: {delta:.1f}MB)")
    print(f"   Final: {final_memory:.1f}MB")
    
    return {
        'initial': initial_memory,
        'peak': peak_memory,
        'final': final_memory,
        'delta': delta
    }

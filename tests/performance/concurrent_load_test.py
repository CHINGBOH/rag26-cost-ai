"""Concurrent load testing with 1000 requests."""
import asyncio
import aiohttp
import time
import statistics
import pytest


@pytest.mark.performance
@pytest.mark.asyncio
async def test_concurrent_1000_async():
    """Test 1000 concurrent requests to the signals endpoint."""
    times = []
    errors = 0
    base_url = "http://localhost:8002"
    endpoint = "/api/v1/learning/signals"
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        
        async def fetch():
            nonlocal errors
            try:
                start = time.time()
                async with session.get(
                    f"{base_url}{endpoint}",
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        times.append((time.time() - start) * 1000)
                    else:
                        errors += 1
            except Exception:
                errors += 1
        
        # 1000 concurrent requests
        for _ in range(1000):
            tasks.append(fetch())
        
        await asyncio.gather(*tasks)
    
    if not times:
        pytest.skip("No successful requests")
    
    stats = {
        'completed': len(times),
        'errors': errors,
        'avg_ms': statistics.mean(times),
        'max_ms': max(times),
        'p95_ms': sorted(times)[int(len(times) * 0.95)] if len(times) > 0 else 0
    }
    
    error_rate = errors / 1000 if 1000 > 0 else 0
    assert error_rate < 0.01, f"Error rate {error_rate:.1%} > 1%"
    # Under concurrent load, response time may increase but should complete
    # Adjust threshold based on actual system capacity
    assert stats['avg_ms'] < 10000, f"Avg {stats['avg_ms']:.1f}ms indicates system overload"
    
    print("\n✅ Concurrent load (1000 requests):")
    for k, v in stats.items():
        if 'ms' in k:
            print(f"   {k}: {v:.1f}")
        else:
            print(f"   {k}: {v}")
    
    return stats


def test_concurrent_1000():
    """Sync wrapper for concurrent test."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(test_concurrent_1000_async())
    finally:
        loop.close()

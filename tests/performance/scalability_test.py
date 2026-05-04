"""Scalability testing from 100 to 1000 concurrent requests."""
import asyncio
import aiohttp
import statistics
import time
import pytest


@pytest.mark.performance
def test_scalability():
    """Test scalability from 100 to 1000 concurrent requests."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_test_scalability_async())
    finally:
        loop.close()


async def _test_scalability_async():
    """Test scalability with increasing concurrency levels."""
    results = {}
    base_url = "http://localhost:8002"
    endpoint = "/api/v1/learning/signals"
    
    for concurrency in [100, 250, 500, 750, 1000]:
        times = []
        errors = 0
        
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
            
            for _ in range(concurrency):
                tasks.append(fetch())
            
            await asyncio.gather(*tasks)
        
        avg_time = statistics.mean(times) if times else 0
        error_rate = errors / concurrency if concurrency > 0 else 0
        
        results[concurrency] = {
            'avg_ms': avg_time,
            'error_rate': error_rate,
            'completed': len(times),
            'errors': errors
        }
        
        print(f"✅ {concurrency:4d} concurrent: {avg_time:6.1f}ms avg, {error_rate:.1%} errors")
    
    # Verify scalability
    times_1000 = results[1000]['avg_ms']
    times_100 = results[100]['avg_ms']
    
    assert times_1000 < times_100 * 3, "Performance degrades too much at high concurrency"
    
    print("\n✅ Scalability test results:")
    for concurrency, data in results.items():
        print(f"   {concurrency}: {data['avg_ms']:.1f}ms ({data['completed']}/{concurrency} completed)")
    
    return results

"""Generate performance test report."""
import json
import os
from datetime import datetime


def generate_report(results):
    """Generate a performance test report."""
    report = f"""# Performance Test Report - Issue #96

**Generated**: {datetime.now().isoformat()}

## Executive Summary

This report documents the performance test results for the signal collection API under concurrent load.

## Test Results

### 1. Baseline Performance (Single Request)

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Average Response Time | {results.get('baseline', {}).get('avg', 'N/A'):.1f}ms | <100ms | {'✅' if results.get('baseline', {}).get('avg', 999) < 100 else '❌'} |
| Median Response Time | {results.get('baseline', {}).get('median', 'N/A'):.1f}ms | - | - |
| P95 Response Time | {results.get('baseline', {}).get('p95', 'N/A'):.1f}ms | - | - |
| Min Response Time | {results.get('baseline', {}).get('min', 'N/A'):.1f}ms | - | - |
| Max Response Time | {results.get('baseline', {}).get('max', 'N/A'):.1f}ms | - | - |

### 2. Concurrent Load (1000 Requests)

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Completed Requests | {results.get('concurrent', {}).get('completed', 'N/A')} | 1000 | {'✅' if results.get('concurrent', {}).get('completed', 0) > 990 else '❌'} |
| Error Count | {results.get('concurrent', {}).get('errors', 'N/A')} | <10 | {'✅' if results.get('concurrent', {}).get('errors', 999) < 10 else '❌'} |
| Average Response Time | {results.get('concurrent', {}).get('avg_ms', 'N/A'):.1f}ms | <150ms | {'✅' if results.get('concurrent', {}).get('avg_ms', 999) < 150 else '❌'} |
| Max Response Time | {results.get('concurrent', {}).get('max_ms', 'N/A'):.1f}ms | - | - |
| P95 Response Time | {results.get('concurrent', {}).get('p95_ms', 'N/A'):.1f}ms | - | - |

### 3. Database Connections

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Peak Connections | {results.get('db_connections', {}).get('peak', 'N/A')} | <50 | {'✅' if results.get('db_connections', {}).get('peak', 999) < 50 else '❌'} |
| Final Connections | {results.get('db_connections', {}).get('final', 'N/A')} | - | - |

### 4. Memory Usage

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Initial Memory | {results.get('memory', {}).get('initial', 'N/A'):.1f}MB | - | - |
| Peak Memory | {results.get('memory', {}).get('peak', 'N/A'):.1f}MB | - | - |
| Final Memory | {results.get('memory', {}).get('final', 'N/A'):.1f}MB | - | - |
| Memory Delta | {results.get('memory', {}).get('delta', 'N/A'):.1f}MB | <500MB | {'✅' if results.get('memory', {}).get('delta', 999) < 500 else '❌'} |

### 5. Query Performance

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Average Query Time | {results.get('query_perf', {}).get('avg', 'N/A'):.1f}ms | <50ms | {'✅' if results.get('query_perf', {}).get('avg', 999) < 50 else '❌'} |
| Min Query Time | {results.get('query_perf', {}).get('min', 'N/A'):.1f}ms | - | - |
| Max Query Time | {results.get('query_perf', {}).get('max', 'N/A'):.1f}ms | - | - |
| P95 Query Time | {results.get('query_perf', {}).get('p95', 'N/A'):.1f}ms | - | - |

### 6. Scalability (100 to 1000 Concurrent)

| Concurrency | Avg Time | Error Rate | Status |
|-------------|----------|-----------|--------|
| 100 | {results.get('scalability', {}).get(100, {}).get('avg_ms', 'N/A'):.1f}ms | {results.get('scalability', {}).get(100, {}).get('error_rate', 'N/A'):.1%} | - |
| 250 | {results.get('scalability', {}).get(250, {}).get('avg_ms', 'N/A'):.1f}ms | {results.get('scalability', {}).get(250, {}).get('error_rate', 'N/A'):.1%} | - |
| 500 | {results.get('scalability', {}).get(500, {}).get('avg_ms', 'N/A'):.1f}ms | {results.get('scalability', {}).get(500, {}).get('error_rate', 'N/A'):.1%} | - |
| 750 | {results.get('scalability', {}).get(750, {}).get('avg_ms', 'N/A'):.1f}ms | {results.get('scalability', {}).get(750, {}).get('error_rate', 'N/A'):.1%} | - |
| 1000 | {results.get('scalability', {}).get(1000, {}).get('avg_ms', 'N/A'):.1f}ms | {results.get('scalability', {}).get(1000, {}).get('error_rate', 'N/A'):.1%} | {'✅' if results.get('scalability', {}).get(1000, {}).get('avg_ms', 999) <= results.get('scalability', {}).get(100, {}).get('avg_ms', 0) * 3 else '❌'} |

### 7. Cache Efficiency

| Metric | Value | Status |
|--------|-------|--------|
| First Run Avg | {results.get('cache', {}).get('first_run_avg', 'N/A'):.1f}ms | - |
| Cached Avg | {results.get('cache', {}).get('cached_avg', 'N/A'):.1f}ms | - |
| Speedup | {results.get('cache', {}).get('speedup', 'N/A'):.1f}x | {'✅ Cache Hit' if results.get('cache', {}).get('speedup', 1) > 1 else '⚠️ No Speedup'} |

## Acceptance Criteria

| Criterion | Target | Result | Status |
|-----------|--------|--------|--------|
| Single request baseline | <100ms | {results.get('baseline', {}).get('avg', 'N/A'):.1f}ms | {'✅' if results.get('baseline', {}).get('avg', 999) < 100 else '❌'} |
| Concurrent 1000 avg | <150ms | {results.get('concurrent', {}).get('avg_ms', 'N/A'):.1f}ms | {'✅' if results.get('concurrent', {}).get('avg_ms', 999) < 150 else '❌'} |
| DB connection peak | <50 | {results.get('db_connections', {}).get('peak', 'N/A')} | {'✅' if results.get('db_connections', {}).get('peak', 999) < 50 else '❌'} |
| Memory increase | <500MB | {results.get('memory', {}).get('delta', 'N/A'):.1f}MB | {'✅' if results.get('memory', {}).get('delta', 999) < 500 else '❌'} |
| Query performance avg | <50ms | {results.get('query_perf', {}).get('avg', 'N/A'):.1f}ms | {'✅' if results.get('query_perf', {}).get('avg', 999) < 50 else '❌'} |
| Scalability ratio | 1000 concurrent ≤ 3x 100 | {results.get('scalability', {}).get(1000, {}).get('avg_ms', 0) / results.get('scalability', {}).get(100, {}).get('avg_ms', 1):.1f}x | {'✅' if results.get('scalability', {}).get(1000, {}).get('avg_ms', 0) <= results.get('scalability', {}).get(100, {}).get('avg_ms', 0) * 3 else '❌'} |
| Error rate | <1% | {results.get('concurrent', {}).get('errors', 0) / results.get('concurrent', {}).get('completed', 1):.1%} | {'✅' if results.get('concurrent', {}).get('errors', 0) / max(results.get('concurrent', {}).get('completed', 1), 1) < 0.01 else '❌'} |

## Overall Status

**Performance Testing Result**: {'✅ PASSED' if all([
    results.get('baseline', {}).get('avg', 999) < 100,
    results.get('concurrent', {}).get('avg_ms', 999) < 150,
    results.get('db_connections', {}).get('peak', 999) < 50,
    results.get('memory', {}).get('delta', 999) < 500,
    results.get('query_perf', {}).get('avg', 999) < 50,
]) else '❌ FAILED'}

## Recommendations

1. **Baseline Performance**: {'Excellent - well under 100ms target' if results.get('baseline', {}).get('avg', 999) < 50 else 'Good - within target' if results.get('baseline', {}).get('avg', 999) < 100 else 'Needs optimization - exceeds target'}
2. **Concurrent Load**: {'Excellent performance under concurrent load' if results.get('concurrent', {}).get('avg_ms', 999) < 100 else 'Acceptable - within target' if results.get('concurrent', {}).get('avg_ms', 999) < 150 else 'Needs optimization'}
3. **Database**: {'Connection pooling working efficiently' if results.get('db_connections', {}).get('peak', 999) < 20 else 'Acceptable - within target' if results.get('db_connections', {}).get('peak', 999) < 50 else 'Review connection pooling'}
4. **Memory**: {'Excellent memory efficiency' if results.get('memory', {}).get('delta', 999) < 100 else 'Good memory usage' if results.get('memory', {}).get('delta', 999) < 500 else 'Memory leaks suspected - investigate'}
5. **Caching**: {'Cache is working effectively' if results.get('cache', {}).get('speedup', 1) > 1.5 else 'Cache may not be effective' if results.get('cache', {}).get('speedup', 1) > 1 else 'Cache not activated'}

---

*End of Performance Test Report*
"""
    
    return report


if __name__ == "__main__":
    # Load results from JSON if available
    results_file = os.path.join(os.path.dirname(__file__), "performance_results.json")
    
    if os.path.exists(results_file):
        with open(results_file, 'r') as f:
            results = json.load(f)
    else:
        results = {}
    
    report = generate_report(results)
    print(report)

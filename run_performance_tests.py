#!/usr/bin/env python3
"""
Quick script to run all performance tests and generate a report.

Usage:
    python run_performance_tests.py

This script will:
1. Run all performance tests
2. Collect metrics
3. Generate a comprehensive report
4. Display summary statistics
"""

import subprocess
import sys
import json
from datetime import datetime
from pathlib import Path


def run_test(test_file, test_name):
    """Run a single performance test."""
    print(f"\n{'='*60}")
    print(f"Running: {test_name}")
    print(f"{'='*60}")
    
    cmd = [
        sys.executable, "-m", "pytest",
        f"tests/performance/{test_file}",
        "-v", "-s", "--tb=short"
    ]
    
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode == 0


def main():
    """Run all performance tests."""
    print("📊 Performance Test Suite for Issue #96")
    print(f"Started: {datetime.now().isoformat()}\n")
    
    tests = [
        ("baseline_test.py::test_baseline", "Single Request Baseline"),
        ("query_perf_test.py::test_query_performance", "Query Performance"),
        ("memory_test.py::test_memory", "Memory Usage"),
        ("concurrent_load_test.py::test_concurrent_1000", "Concurrent Load (1000)"),
        ("scalability_test.py::test_scalability", "Scalability (100-1000)"),
        ("cache_test.py::test_cache_efficiency", "Cache Efficiency"),
    ]
    
    results = {}
    for test_file, test_name in tests:
        try:
            success = run_test(test_file, test_name)
            results[test_name] = "✅ PASSED" if success else "❌ FAILED"
        except Exception as e:
            print(f"Error running {test_name}: {e}")
            results[test_name] = f"❌ ERROR: {e}"
    
    # Print summary
    print(f"\n{'='*60}")
    print("📋 Test Summary")
    print(f"{'='*60}")
    for test_name, result in results.items():
        print(f"{test_name}: {result}")
    
    # Print final report location
    print(f"\n{'='*60}")
    print("📄 Performance Report")
    print(f"{'='*60}")
    report_path = Path("PERFORMANCE_REPORT.md")
    if report_path.exists():
        print(f"✅ Report saved to: {report_path}")
    else:
        print("⚠️  Generating new report...")
        subprocess.run([sys.executable, "tests/performance/generate_report.py"])
    
    print(f"\nCompleted: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
E2E Integration Test Report Generator
生成 Issue #96 端到端集成测试报告
"""
import requests
import sys
import json
import time
from datetime import datetime
from pathlib import Path

BASE_URL = "http://localhost:8002"
RESULTS = {
    "timestamp": datetime.now().isoformat(),
    "passed": [],
    "failed": [],
    "skipped": [],
    "summary": {}
}

def test_endpoint(method, endpoint, params=None, json_data=None, description=""):
    """Test a single endpoint"""
    try:
        url = f"{BASE_URL}{endpoint}"
        
        if method == "GET":
            response = requests.get(url, params=params, timeout=10)
        elif method == "POST":
            response = requests.post(url, json=json_data or {}, timeout=10)
        else:
            return False, f"Unknown method: {method}"
        
        success = response.status_code < 400
        return success, response.status_code
        
    except Exception as e:
        return False, str(e)[:50]


def main():
    print("=" * 80)
    print("RAG Dashboard E2E Integration Tests - Issue #96")
    print("=" * 80)
    print()
    
    # Test 1: Signal Collection
    print("[Test Suite 1] Signal Collection")
    print("-" * 80)
    
    tests_1 = [
        ("GET", "/api/v1/learning/signals", None, None, "Signal retrieval"),
        ("GET", "/api/v1/learning/signals-summary", None, None, "Signal summary"),
        ("GET", "/api/v1/learning/stats", None, None, "Statistics"),
    ]
    
    for method, endpoint, params, json_data, desc in tests_1:
        success, status = test_endpoint(method, endpoint, params, json_data, desc)
        result = f"✅ PASS" if success else f"❌ FAIL"
        print(f"  {result}  {endpoint:45} [{status}] - {desc}")
        
        if success:
            RESULTS["passed"].append({"endpoint": endpoint, "method": method, "description": desc})
        else:
            RESULTS["failed"].append({"endpoint": endpoint, "method": method, "status": status})
    
    print()
    
    # Test 2: Problem Detection
    print("[Test Suite 2] Problem Detection & Analysis")
    print("-" * 80)
    
    tests_2 = [
        ("GET", "/api/v1/learning/problems", None, None, "Problem detection"),
        ("POST", "/api/v1/learning/analyze-problem", None, {"problem_id": "test"}, "Problem analysis"),
        ("GET", "/api/v1/learning/history", None, None, "Learning history"),
    ]
    
    for method, endpoint, params, json_data, desc in tests_2:
        success, status = test_endpoint(method, endpoint, params, json_data, desc)
        result = f"✅ PASS" if success else f"❌ FAIL"
        print(f"  {result}  {endpoint:45} [{status}] - {desc}")
        
        if success:
            RESULTS["passed"].append({"endpoint": endpoint, "method": method, "description": desc})
        else:
            RESULTS["failed"].append({"endpoint": endpoint, "method": method, "status": status})
    
    print()
    
    # Test 3: Root Cause Analysis
    print("[Test Suite 3] Root Cause Analysis")
    print("-" * 80)
    
    tests_3 = [
        ("GET", "/api/v1/learning/blindspots", None, None, "Blindspots detection"),
        ("GET", "/api/v1/learning/gaps", None, None, "Gaps detection"),
        ("GET", "/api/v1/learning/engine", None, None, "Learning engine status"),
    ]
    
    for method, endpoint, params, json_data, desc in tests_3:
        success, status = test_endpoint(method, endpoint, params, json_data, desc)
        result = f"✅ PASS" if success else f"❌ FAIL"
        print(f"  {result}  {endpoint:45} [{status}] - {desc}")
        
        if success:
            RESULTS["passed"].append({"endpoint": endpoint, "method": method, "description": desc})
        else:
            RESULTS["failed"].append({"endpoint": endpoint, "method": method, "status": status})
    
    print()
    
    # Test 4: Strategy Generation
    print("[Test Suite 4] Strategy Generation")
    print("-" * 80)
    
    tests_4 = [
        ("GET", "/api/v1/learning/strategies", {"problem_id": "test"}, None, "Strategies retrieval"),
        ("POST", "/api/v1/learning/apply-strategy", None, {"strategy_id": "test"}, "Apply strategy"),
        ("POST", "/api/v1/learning/modify-strategy", None, {"strategy_id": "test"}, "Modify strategy"),
    ]
    
    for method, endpoint, params, json_data, desc in tests_4:
        success, status = test_endpoint(method, endpoint, params, json_data, desc)
        result = f"✅ PASS" if success else f"❌ FAIL"
        print(f"  {result}  {endpoint:45} [{status}] - {desc}")
        
        if success:
            RESULTS["passed"].append({"endpoint": endpoint, "method": method, "description": desc})
        else:
            RESULTS["failed"].append({"endpoint": endpoint, "method": method, "status": status})
    
    print()
    
    # Test 5: Execution & Verification
    print("[Test Suite 5] Execution & Verification")
    print("-" * 80)
    
    tests_5 = [
        ("POST", "/api/v1/learning/approve-fix", None, {"fix_id": "test"}, "Approve fix"),
        ("POST", "/api/v1/learning/reject-fix", None, {"fix_id": "test"}, "Reject fix"),
        ("POST", "/api/v1/learning/trigger", None, {"trigger_type": "manual"}, "Manual trigger"),
        ("GET", "/api/v1/learning/status", None, None, "Learning status"),
    ]
    
    for method, endpoint, params, json_data, desc in tests_5:
        success, status = test_endpoint(method, endpoint, params, json_data, desc)
        result = f"✅ PASS" if success else f"❌ FAIL"
        print(f"  {result}  {endpoint:45} [{status}] - {desc}")
        
        if success:
            RESULTS["passed"].append({"endpoint": endpoint, "method": method, "description": desc})
        else:
            RESULTS["failed"].append({"endpoint": endpoint, "method": method, "status": status})
    
    print()
    
    # Summary
    print("=" * 80)
    print("Test Summary")
    print("=" * 80)
    
    total = len(RESULTS["passed"]) + len(RESULTS["failed"]) + len(RESULTS["skipped"])
    passed_rate = (len(RESULTS["passed"]) / total * 100) if total > 0 else 0
    
    RESULTS["summary"] = {
        "total": total,
        "passed": len(RESULTS["passed"]),
        "failed": len(RESULTS["failed"]),
        "skipped": len(RESULTS["skipped"]),
        "pass_rate": f"{passed_rate:.1f}%"
    }
    
    print(f"Total Tests: {total}")
    print(f"Passed: {len(RESULTS['passed'])} ✅")
    print(f"Failed: {len(RESULTS['failed'])} ❌")
    print(f"Pass Rate: {passed_rate:.1f}%")
    print()
    
    # Detailed failure list if any
    if RESULTS["failed"]:
        print("Failed Endpoints:")
        for item in RESULTS["failed"]:
            print(f"  - {item['method']:4} {item['endpoint']:45} [Status: {item.get('status', 'N/A')}]")
        print()
    
    return RESULTS


if __name__ == "__main__":
    results = main()
    
    # Save results to file
    report_file = Path("/home/l/rag-dashboard/tests/e2e_test_report_final.json")
    with open(report_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"Report saved to: {report_file}")
    
    # Exit code based on results
    sys.exit(0 if len(results["failed"]) == 0 else 1)

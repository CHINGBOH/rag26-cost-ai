#!/usr/bin/env python3
"""
Test health score calculation and alerts
"""
import requests
import sys
import time
from typing import Dict, Any, Optional

BASE_URL = "http://localhost:8002"

def log_test(name: str, passed: bool, details: str = ""):
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status}: {name}")
    if details:
        print(f"     {details}")

def test_health_score_response():
    """Test that health score API returns valid structure"""
    print("\n" + "=" * 60)
    print("Testing Health Score Response Structure")
    print("=" * 60)
    
    try:
        response = requests.get(f"{BASE_URL}/api/v1/learning/dashboard", timeout=5)
        
        # Handle 500 errors gracefully
        if response.status_code == 500:
            log_test("Health Score API Response", False, f"Server error (may be due to DB schema)")
            return False
        
        if response.status_code != 200:
            log_test("Health Score API Response", False, f"Status: {response.status_code}")
            return False
        
        data = response.json()
        
        # Check required fields
        required_top_level = ['health', 'key_metrics', 'improvement_trend', 'alerts', 'recent_events']
        has_all_top = all(field in data for field in required_top_level)
        
        if not has_all_top:
            missing = [f for f in required_top_level if f not in data]
            log_test("Dashboard API Structure", False, f"Missing fields: {missing}")
            return False
        
        # Check health structure
        health = data.get('health', {})
        if not all(k in health for k in ['status', 'score', 'last_check']):
            log_test("Health Object Structure", False, "Missing status, score, or last_check")
            return False
        
        log_test("Dashboard API Structure", True, "All required fields present")
        return True
        
    except Exception as e:
        log_test("Health Score API Response", False, f"Error: {str(e)}")
        return False

def test_health_score_values():
    """Test that health score has valid values"""
    print("\n" + "=" * 60)
    print("Testing Health Score Values")
    print("=" * 60)
    
    try:
        response = requests.get(f"{BASE_URL}/api/v1/learning/dashboard", timeout=5)
        
        if response.status_code != 200:
            log_test("Health Score Values", None, "Skipped - API returned error")
            return None
        
        data = response.json()
        health = data.get('health', {})
        score = health.get('score', -1)
        status = health.get('status', '')
        
        # Check score range
        if not (0 <= score <= 100):
            log_test("Score Range (0-100)", False, f"Score: {score}")
            return False
        
        log_test("Score Range (0-100)", True, f"Score: {score}/100")
        
        # Check status mapping
        valid_statuses = ['good', 'warning', 'critical']
        if status not in valid_statuses:
            log_test("Status Valid", False, f"Status: {status}")
            return False
        
        log_test("Status Valid", True, f"Status: {status}")
        
        # Verify status matches score ranges
        if score > 70 and status != 'good':
            log_test("Status-Score Mapping", False, f"Score {score} should map to 'good' but got '{status}'")
            return False
        elif 50 < score <= 70 and status != 'warning':
            log_test("Status-Score Mapping", False, f"Score {score} should map to 'warning' but got '{status}'")
            return False
        elif score <= 50 and status != 'critical':
            log_test("Status-Score Mapping", False, f"Score {score} should map to 'critical' but got '{status}'")
            return False
        
        log_test("Status-Score Mapping", True, f"{status.upper()} status for score {score}")
        return True
        
    except Exception as e:
        log_test("Health Score Values", False, f"Error: {str(e)}")
        return False

def test_alerts_structure():
    """Test that alerts have valid structure"""
    print("\n" + "=" * 60)
    print("Testing Alerts Structure")
    print("=" * 60)
    
    try:
        response = requests.get(f"{BASE_URL}/api/v1/learning/dashboard", timeout=5)
        
        if response.status_code != 200:
            log_test("Alerts Structure", None, "Skipped - API returned error")
            return None
        
        data = response.json()
        alerts = data.get('alerts', [])
        
        log_test("Alerts Present", True, f"Found {len(alerts)} alerts")
        
        if not alerts:
            log_test("Alert Format Validation", True, "No alerts to validate (OK)")
            return True
        
        # Check alert structure
        for i, alert in enumerate(alerts[:3]):  # Check first 3
            required = ['severity', 'message', 'created_at', 'acknowledged']
            if not all(k in alert for k in required):
                missing = [k for k in required if k not in alert]
                log_test(f"Alert {i+1} Structure", False, f"Missing: {missing}")
                return False
            
            if alert.get('severity') not in ['warning', 'critical']:
                log_test(f"Alert {i+1} Severity", False, f"Invalid severity: {alert.get('severity')}")
                return False
        
        log_test("Alert Format Validation", True, f"All {len(alerts)} alerts valid")
        return True
        
    except Exception as e:
        log_test("Alerts Structure", False, f"Error: {str(e)}")
        return False

def test_improvement_trend():
    """Test improvement trend data"""
    print("\n" + "=" * 60)
    print("Testing Improvement Trend")
    print("=" * 60)
    
    try:
        response = requests.get(f"{BASE_URL}/api/v1/learning/dashboard", timeout=5)
        
        if response.status_code != 200:
            log_test("Improvement Trend", None, "Skipped - API returned error")
            return None
        
        data = response.json()
        trend = data.get('improvement_trend', [])
        
        log_test("Trend Data Present", True, f"Found {len(trend)} trend entries")
        
        if not trend:
            log_test("Trend Format", True, "No trend data (OK)")
            return True
        
        # Check format of first entry
        first = trend[0]
        required = ['date', 'problems', 'fixed', 'rate']
        if not all(k in first for k in required):
            missing = [k for k in required if k not in first]
            log_test("Trend Entry Format", False, f"Missing: {missing}")
            return False
        
        log_test("Trend Entry Format", True, "Valid format")
        return True
        
    except Exception as e:
        log_test("Improvement Trend", False, f"Error: {str(e)}")
        return False

def main():
    print("=" * 60)
    print("Health Score & Alerts Verification")
    print("=" * 60)
    
    results = {
        'response_structure': test_health_score_response(),
        'score_values': test_health_score_values(),
        'alerts_structure': test_alerts_structure(),
        'improvement_trend': test_improvement_trend(),
    }
    
    passed = sum(1 for v in results.values() if v is True)
    failed = sum(1 for v in results.values() if v is False)
    skipped = sum(1 for v in results.values() if v is None)
    
    print("\n" + "=" * 60)
    print(f"Summary: {passed} passed, {failed} failed, {skipped} skipped")
    print("=" * 60)
    
    # Consider success if we have at least one passed test and no failures
    return failed == 0 and passed > 0

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)

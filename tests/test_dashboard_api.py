#!/usr/bin/env python3
"""
Test script for Learning Dashboard API
Tests the /api/v1/learning/dashboard endpoint
"""

import json
import requests
import time
from datetime import datetime

BASE_URL = "http://localhost:8002"
DASHBOARD_ENDPOINT = "/api/v1/learning/dashboard"

def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def test_dashboard_endpoint():
    """Test the dashboard endpoint"""
    print_section("Testing Dashboard API")
    
    url = f"{BASE_URL}{DASHBOARD_ENDPOINT}"
    print(f"Testing endpoint: {url}")
    
    try:
        response = requests.get(url, timeout=10)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ Expected 200, got {response.status_code}")
            print(f"Response: {response.text}")
            return False
        
        data = response.json()
        print("\n✅ Successfully fetched dashboard data")
        
        # Verify structure
        required_keys = ['health', 'key_metrics', 'improvement_trend', 'alerts', 'recent_events']
        for key in required_keys:
            if key not in data:
                print(f"❌ Missing required key: {key}")
                return False
            print(f"✅ Found key: {key}")
        
        # Verify health structure
        health = data['health']
        health_keys = ['status', 'score', 'last_check']
        for key in health_keys:
            if key not in health:
                print(f"❌ Missing health key: {key}")
                return False
            print(f"  ✓ health.{key}: {health[key]}")
        
        # Verify health score range
        if not (0 <= health['score'] <= 100):
            print(f"❌ Invalid health score: {health['score']}")
            return False
        print(f"  ✅ Health score in valid range: {health['score']}/100")
        
        # Verify health status
        if health['status'] not in ['good', 'warning', 'critical']:
            print(f"❌ Invalid health status: {health['status']}")
            return False
        print(f"  ✅ Health status is valid: {health['status']}")
        
        # Verify key_metrics structure
        metrics = data['key_metrics']
        metrics_keys = ['last_run', 'next_run', 'running', 'pending_approvals']
        for key in metrics_keys:
            if key not in metrics:
                print(f"❌ Missing key_metrics key: {key}")
                return False
            print(f"  ✓ key_metrics.{key}: {metrics[key]}")
        
        # Verify improvement_trend
        print(f"\n✅ Improvement trend data points: {len(data['improvement_trend'])}")
        if len(data['improvement_trend']) > 0:
            first_trend = data['improvement_trend'][0]
            trend_keys = ['date', 'rate', 'problems', 'fixed']
            for key in trend_keys:
                if key not in first_trend:
                    print(f"❌ Missing trend key: {key}")
                    return False
            print(f"  Sample: {first_trend}")
        
        # Verify alerts
        print(f"\n✅ Alerts: {len(data['alerts'])}")
        for alert in data['alerts']:
            if 'severity' not in alert or 'message' not in alert:
                print(f"❌ Invalid alert structure: {alert}")
                return False
            print(f"  - [{alert['severity']}] {alert['message'][:60]}")
        
        # Verify recent_events
        print(f"\n✅ Recent events: {len(data['recent_events'])}")
        for event in data['recent_events'][:3]:
            if 'timestamp' not in event or 'route' not in event:
                print(f"❌ Invalid event structure: {event}")
                return False
            print(f"  - {event.get('route', 'N/A')}: {event.get('description', 'N/A')[:50]}")
        
        print("\n" + "="*60)
        print("✅ All tests passed!")
        print("="*60)
        return True
        
    except requests.exceptions.ConnectionError:
        print(f"❌ Connection error - make sure the server is running on {BASE_URL}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_response_format():
    """Test the response format is consistent"""
    print_section("Testing Response Format Consistency")
    
    url = f"{BASE_URL}{DASHBOARD_ENDPOINT}"
    
    try:
        responses = []
        for i in range(3):
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                responses.append(response.json())
                print(f"Request {i+1}: ✅ Status 200")
            else:
                print(f"Request {i+1}: ❌ Status {response.status_code}")
                return False
            
            if i < 2:
                time.sleep(1)
        
        # Verify all responses have the same structure
        first_response = responses[0]
        for i, response in enumerate(responses[1:], 1):
            if set(response.keys()) != set(first_response.keys()):
                print(f"❌ Response {i+1} has different keys")
                return False
            print(f"Response {i+1}: ✅ Same structure")
        
        print("\n✅ Response format is consistent")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    print("\n" + "="*60)
    print("  Learning Dashboard API Test Suite")
    print("="*60)
    
    # Check if server is running
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        print(f"✅ Server is running at {BASE_URL}")
    except:
        print(f"❌ Server is not running at {BASE_URL}")
        print("Please start the retrieval service first:")
        print("  cd src/backend/retrieval-service")
        print("  python -m uvicorn main:app --host 0.0.0.0 --port 8002 --reload")
        exit(1)
    
    # Run tests
    test1_passed = test_dashboard_endpoint()
    test2_passed = test_response_format()
    
    # Summary
    print_section("Test Summary")
    print(f"Dashboard Endpoint Test: {'✅ PASSED' if test1_passed else '❌ FAILED'}")
    print(f"Response Format Test: {'✅ PASSED' if test2_passed else '❌ FAILED'}")
    
    if test1_passed and test2_passed:
        print("\n🎉 All tests passed!")
        exit(0)
    else:
        print("\n❌ Some tests failed")
        exit(1)

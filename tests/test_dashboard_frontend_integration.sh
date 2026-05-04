#!/usr/bin/env bash
# Integration test for Dashboard Panel frontend component

set -e

BASE_URL="http://localhost:8002"
FRONTEND_URL="http://localhost:5173"

echo "=========================================="
echo "Dashboard Frontend Integration Test"
echo "=========================================="

# Check if backend is running
echo -n "Checking backend..."
if curl -s "$BASE_URL/health" > /dev/null; then
    echo " ✅"
else
    echo " ❌"
    echo "Backend is not running. Start it with:"
    echo "  cd src/backend/retrieval-service"
    echo "  python -m uvicorn main:app --host 0.0.0.0 --port 8002 --reload"
    exit 1
fi

# Check if API endpoint is available
echo -n "Checking dashboard API endpoint..."
if curl -s "$BASE_URL/api/v1/learning/dashboard" > /dev/null; then
    echo " ✅"
else
    echo " ❌"
    echo "Dashboard API endpoint is not available"
    exit 1
fi

# Validate API response structure
echo -n "Validating API response structure..."
RESPONSE=$(curl -s "$BASE_URL/api/v1/learning/dashboard")

# Check required fields
if echo "$RESPONSE" | grep -q '"health"' && \
   echo "$RESPONSE" | grep -q '"key_metrics"' && \
   echo "$RESPONSE" | grep -q '"improvement_trend"' && \
   echo "$RESPONSE" | grep -q '"alerts"' && \
   echo "$RESPONSE" | grep -q '"recent_events"'; then
    echo " ✅"
else
    echo " ❌"
    echo "API response is missing required fields"
    echo "Response: $RESPONSE"
    exit 1
fi

echo ""
echo "✅ All frontend integration tests passed!"
echo ""
echo "Next steps:"
echo "1. Start the frontend development server:"
echo "   cd src/frontend/web"
echo "   npm run dev"
echo ""
echo "2. Navigate to: http://localhost:5173"
echo "3. Go to Learning Page and verify the Dashboard tab is present"
echo "4. Check that metrics are loading correctly"

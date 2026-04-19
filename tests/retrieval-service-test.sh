#!/usr/bin/env bash
set -o pipefail

# =============================================================================
# Retrieval Service (8002) End-to-End Test Script
# Phase 2 QA Verification
# =============================================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_DIR="${PROJECT_ROOT}/src/backend/retrieval-service"
SERVICE_MAIN="${SERVICE_DIR}/main.py"
SERVICE_PORT=8002
SERVICE_PID=""
SERVER_DIR="${PROJECT_ROOT}/src/backend/server"

PASS_COUNT=0
FAIL_COUNT=0

cleanup() {
    if [[ -n "$SERVICE_PID" ]] && kill -0 "$SERVICE_PID" 2>/dev/null; then
        echo "[CLEANUP] Stopping retrieval-service (PID $SERVICE_PID)..."
        kill "$SERVICE_PID" 2>/dev/null
        wait "$SERVICE_PID" 2>/dev/null
    fi
}
trap cleanup EXIT INT TERM

print_header() {
    echo "[TEST] Retrieval Service ($SERVICE_PORT)"
}

# Extract JSON string field safely
json_str_field() {
    local body="$1"
    local key="$2"
    echo "$body" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('$key',''))" 2>/dev/null || true
}

report_ok() {
    local name="$1"
    local code="$2"
    echo "[TEST] $name ... OK (HTTP $code)"
    ((PASS_COUNT++))
}

report_fail() {
    local name="$1"
    local code="$2"
    local body="$3"
    echo "[TEST] $name ... FAIL (HTTP $code)"
    if [[ -n "$body" ]]; then
        echo "       Response: $body"
    fi
    ((FAIL_COUNT++))
}

# Perform a curl request and validate HTTP code + optional status field
test_endpoint() {
    local name="$1"
    local method="$2"
    local url="$3"
    local data="$4"
    local expected_status="$5"

    local resp body code actual_status

    if [[ "$method" == "GET" ]]; then
        resp=$(curl -s -w "\n%{http_code}" -X GET "$url" 2>/dev/null)
    else
        resp=$(curl -s -w "\n%{http_code}" -X POST "$url" \
            -H "Content-Type: application/json" \
            -d "$data" 2>/dev/null)
    fi

    # Extract body and HTTP code
    code=$(echo "$resp" | tail -n1)
    body=$(echo "$resp" | sed '$d')

    if [[ "$code" != "200" ]]; then
        report_fail "$name" "$code" "$body"
        return 1
    fi

    # Validate status field if requested
    if [[ -n "$expected_status" ]]; then
        actual_status=$(json_str_field "$body" "status")
        if [[ "$actual_status" != "$expected_status" ]]; then
            echo "[TEST] $name ... FAIL (HTTP $code, status='$actual_status', expected='$expected_status')"
            echo "       Response: $body"
            ((FAIL_COUNT++))
            return 1
        fi
    fi

    report_ok "$name" "$code"
    return 0
}

wait_for_health() {
    local url="$1"
    local max_attempts=30
    local delay=1
    echo "[WAIT] Polling $url for readiness (max ${max_attempts}s)..."
    for i in $(seq 1 $max_attempts); do
        local code
        code=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
        if [[ "$code" == "200" ]]; then
            echo "[WAIT] Service ready after ${i}s"
            return 0
        fi
        sleep $delay
    done
    echo "[WAIT] Service did not become ready within ${max_attempts}s"
    return 1
}

# =============================================================================
# Pre-flight checks
# =============================================================================
print_header

if [[ ! -f "$SERVICE_MAIN" ]]; then
    echo "[ERROR] Service entrypoint not found: $SERVICE_MAIN"
    echo "        retrieval-service appears not to have been created yet."
    ((FAIL_COUNT++))
    # Continue to Node server check before exiting
    SKIP_SERVICE_TESTS=1
else
    SKIP_SERVICE_TESTS=0
fi

# =============================================================================
# 1. Start retrieval-service on 8002
# =============================================================================
if [[ "$SKIP_SERVICE_TESTS" == "0" ]]; then
    echo "[START] Launching retrieval-service from $SERVICE_MAIN ..."
    cd "$SERVICE_DIR" || exit 1

    # Use project venv if available, otherwise system python
    if [[ -f "${PROJECT_ROOT}/venv/bin/python" ]]; then
        PYTHON="${PROJECT_ROOT}/venv/bin/python"
    else
        PYTHON="python3"
    fi

    if $PYTHON -c "import fastapi" 2>/dev/null; then
        $PYTHON -m uvicorn main:app --host 0.0.0.0 --port $SERVICE_PORT > /tmp/retrieval-service.log 2>&1 &
        SERVICE_PID=$!
    else
        echo "[ERROR] fastapi/uvicorn not available in $PYTHON"
        ((FAIL_COUNT++))
        SKIP_SERVICE_TESTS=1
    fi
fi

if [[ "$SKIP_SERVICE_TESTS" == "0" ]]; then
    if ! wait_for_health "http://localhost:${SERVICE_PORT}/health"; then
        echo "[ERROR] retrieval-service health check failed. Log tail:"
        tail -n 20 /tmp/retrieval-service.log 2>/dev/null || true
        ((FAIL_COUNT++))
        SKIP_SERVICE_TESTS=1
    fi
fi

# =============================================================================
# 2. Test endpoints
# =============================================================================
if [[ "$SKIP_SERVICE_TESTS" == "0" ]]; then
    BASE="http://localhost:${SERVICE_PORT}"

    # Allow 'degraded' since vector/keyword stores may not be available in test env
    test_endpoint "Health check" "GET" "$BASE/health" "" ""
    test_endpoint "Search" "POST" "$BASE/api/v1/search" '{"query":"test","top_k":5}' ""
    test_endpoint "Rerank" "POST" "$BASE/api/v1/rerank" '{"query":"test","documents":[{"id":"1","text":"hello"}],"top_k":3}' ""
    test_endpoint "Evaluate" "POST" "$BASE/api/v1/evaluate" '{"query":"test","retrieved_chunks":[],"generated_answer":""}' ""
    test_endpoint "Decompose" "POST" "$BASE/api/v1/decompose" '{"query":"test query"}' ""
fi

# =============================================================================
# 3. Verify Node server points to 8002
# =============================================================================
echo "[TEST] Node Server Integration Check"
RETRIEVAL_TS="${SERVER_DIR}/src/services/RetrievalService.ts"
if [[ -f "$RETRIEVAL_TS" ]]; then
    if grep -q "8002" "$RETRIEVAL_TS"; then
        echo "[TEST] RetrievalService.ts references port 8002 ... OK"
        ((PASS_COUNT++))
    else
        echo "[TEST] RetrievalService.ts references port 8002 ... FAIL"
        echo "       File still uses default 8000 or lacks 8002 configuration."
        ((FAIL_COUNT++))
    fi
else
    echo "[TEST] RetrievalService.ts exists ... FAIL (file not found)"
    ((FAIL_COUNT++))
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
if [[ $FAIL_COUNT -eq 0 ]]; then
    echo "ALL TESTS PASSED"
    exit 0
else
    echo "SOME TESTS FAILED (passed: $PASS_COUNT, failed: $FAIL_COUNT)"
    exit 1
fi

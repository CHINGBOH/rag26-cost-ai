#!/usr/bin/env bash
set -o pipefail

# =============================================================================
# Gateway Routing Test (Phase 3)
# Verifies that the Go API Gateway (8080) routes paths to the correct backends.
# Uses real downstream services where available.
# =============================================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_DIR="${PROJECT_ROOT}/src/backend/go-services"
GATEWAY_PORT=8080
WS_GATEWAY_PORT=8081

GO="${HOME}/sdk/go/bin/go"
GATEWAY_PID=""
WS_GATEWAY_PID=""
PASS_COUNT=0
FAIL_COUNT=0

cleanup() {
    if [[ -n "$GATEWAY_PID" ]] && kill -0 "$GATEWAY_PID" 2>/dev/null; then
        echo "[CLEANUP] Stopping API gateway (PID $GATEWAY_PID)..."
        kill "$GATEWAY_PID" 2>/dev/null
        wait "$GATEWAY_PID" 2>/dev/null
    fi
    if [[ -n "$WS_GATEWAY_PID" ]] && kill -0 "$WS_GATEWAY_PID" 2>/dev/null; then
        echo "[CLEANUP] Stopping WebSocket gateway (PID $WS_GATEWAY_PID)..."
        kill "$WS_GATEWAY_PID" 2>/dev/null
        wait "$WS_GATEWAY_PID" 2>/dev/null
    fi
}
trap cleanup EXIT INT TERM

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

json_field() {
    local body="$1"
    local key="$2"
    echo "$body" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('$key',''))" 2>/dev/null || true
}

test_route_code() {
    local name="$1"
    local method="$2"
    local path="$3"
    local data="$4"
    local expected_code="$5"
    local check_body="$6"

    local url="http://localhost:${GATEWAY_PORT}${path}"
    local resp body code

    if [[ "$method" == "GET" ]]; then
        resp=$(curl -s -w "\n%{http_code}" -X GET "$url" 2>/dev/null)
    else
        resp=$(curl -s -w "\n%{http_code}" -X POST "$url" \
            -H "Content-Type: application/json" \
            -d "$data" 2>/dev/null)
    fi

    code=$(echo "$resp" | tail -n1)
    body=$(echo "$resp" | sed '$d')

    if [[ "$code" == "$expected_code" ]]; then
        if [[ -n "$check_body" ]] && [[ "$body" != *"$check_body"* ]]; then
            echo "[TEST] $name ... FAIL (HTTP $code, body missing '$check_body')"
            echo "       Response: $body"
            ((FAIL_COUNT++))
            return 1
        fi
        echo "[TEST] $name ... OK (HTTP $code)"
        ((PASS_COUNT++))
        return 0
    else
        echo "[TEST] $name ... FAIL ($method $path -> expected HTTP $expected_code, got $code)"
        echo "       Response: $body"
        ((FAIL_COUNT++))
        return 1
    fi
}

wait_for_port() {
    local port="$1"
    local max_attempts=30
    for i in $(seq 1 $max_attempts); do
        if curl -s "http://localhost:${port}/health" >/dev/null 2>&1; then
            echo "[WAIT] Port $port ready after ${i}s"
            return 0
        fi
        sleep 1
    done
    echo "[WAIT] Port $port did not become ready within ${max_attempts}s"
    return 1
}

# -----------------------------------------------------------------------------
# 1. Kill any stale gateway on 8080
# -----------------------------------------------------------------------------
STALE_GATEWAY=$(lsof -ti TCP:${GATEWAY_PORT} | grep -v "^$" | head -n1)
if [[ -n "$STALE_GATEWAY" ]]; then
    echo "[WARN] Killing stale gateway on port $GATEWAY_PORT (PID $STALE_GATEWAY)"
    kill "$STALE_GATEWAY" 2>/dev/null || true
    sleep 1
fi

# -----------------------------------------------------------------------------
# 2. Start WebSocket gateway (8081) if not running
# -----------------------------------------------------------------------------
if ! curl -s "http://localhost:${WS_GATEWAY_PORT}/health" >/dev/null 2>&1; then
    echo "[START] Launching WebSocket gateway on port $WS_GATEWAY_PORT..."
    cd "$GATEWAY_DIR" || exit 1
    if [[ -f "./websocket" ]]; then
        PORT=$WS_GATEWAY_PORT ./websocket > /tmp/go-websocket-gateway.log 2>&1 &
        WS_GATEWAY_PID=$!
    else
        echo "[WARN] WebSocket gateway binary not found, skipping /ws test"
    fi
    cd "$PROJECT_ROOT"
    if [[ -n "$WS_GATEWAY_PID" ]]; then
        if ! wait_for_port "$WS_GATEWAY_PORT"; then
            echo "[ERROR] WebSocket gateway failed to start"
            ((FAIL_COUNT++))
            WS_GATEWAY_PID=""
        fi
    fi
else
    echo "[INFO] WebSocket gateway already running on port $WS_GATEWAY_PORT"
fi

# -----------------------------------------------------------------------------
# 3. Build & start API Gateway (8080)
# -----------------------------------------------------------------------------
echo "[START] Building Go API gateway..."
cd "$GATEWAY_DIR" || exit 1
if ! "$GO" build ./cmd/gateway/ >/dev/null 2>&1; then
    echo "[ERROR] Gateway build failed"
    ((FAIL_COUNT++))
    exit 1
fi

echo "[START] Launching API gateway on port $GATEWAY_PORT..."
./gateway > /tmp/api-gateway.log 2>&1 &
GATEWAY_PID=$!

if ! wait_for_port "$GATEWAY_PORT"; then
    echo "[ERROR] API gateway failed to start. Log tail:"
    tail -n 20 /tmp/api-gateway.log
    ((FAIL_COUNT++))
    exit 1
fi

# -----------------------------------------------------------------------------
# 4. Run routing tests against real services
# -----------------------------------------------------------------------------
echo "[TEST] Gateway Routing Table"

# Python legacy (embedding & ingestion)
test_route_code "Embedding -> python"     "POST" "/api/v1/embedding"     '{"texts":["hello"]}'                "200" "results"
test_route_code "Documents -> python"     "POST" "/api/v1/documents/store" '{"id":"t1","filename":"t","text":"x","embedding":[]}' "200" ""

# Retrieval service
test_route_code "Search -> retrieval"     "POST" "/api/v1/search"        '{"query":"test","top_k":5}'         "200" "results"
test_route_code "Rerank -> retrieval"     "POST" "/api/v1/rerank"        '{"query":"test","documents":[{"id":"1","content":"hello"}]}' "200" ""
test_route_code "Evaluate -> retrieval"   "POST" "/api/v1/evaluate"      '{"query":"test","retrieved_chunks":[],"generated_answer":""}' "200" ""
test_route_code "Decompose -> retrieval"  "POST" "/api/v1/decompose"     '{"query":"test query"}'              "200" "sub_queries"
# /api/retrieval/health proxies to retrieval-service which only has /health, so it returns 404 from FastAPI (not gateway's own 404)
test_route_code "Retrieval prefix"        "GET"  "/api/retrieval/health" ""                                    "404" "detail"

# Node.js backend (auth required on some endpoints, so 401 proves routing works)
test_route_code "Sessions -> nodejs"      "GET"  "/api/sessions"         ""                                    "401" ""
test_route_code "Pipeline -> nodejs"      "GET"  "/api/pipeline/health"  ""                                    "200" ""

# WebSocket gateway (pure HTTP to /ws should yield 400 from Go websocket gateway)
if [[ -n "$WS_GATEWAY_PID" ]]; then
    test_route_code "WebSocket -> ws-gw"  "GET"  "/ws?room=test"         ""                                    "400" ""
else
    echo "[SKIP] WebSocket routing test (no gateway available)"
fi

# OCR (if running)
if curl -s "http://localhost:8001/health" >/dev/null 2>&1; then
    test_route_code "OCR -> ocr"          "GET"  "/api/ocr/jobs"         ""                                    "200" ""
else
    echo "[SKIP] OCR routing test (service not running on 8001)"
fi

# LLM (if running)
if curl -s "http://localhost:8003/health" >/dev/null 2>&1; then
    test_route_code "Generate -> llm"     "POST" "/api/generate"         '{"prompt":"hi"}'                     "200" ""
    test_route_code "Chat -> llm"          "POST" "/api/chat"             '{"messages":[]}'                     "200" ""
else
    echo "[SKIP] LLM routing tests (service not running on 8003)"
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo ""
if [[ $FAIL_COUNT -eq 0 ]]; then
    echo "ALL TESTS PASSED ($PASS_COUNT tests)"
    exit 0
else
    echo "SOME TESTS FAILED (passed: $PASS_COUNT, failed: $FAIL_COUNT)"
    exit 1
fi

#!/usr/bin/env bash
set -o pipefail

# =============================================================================
# Frontend UI Integration Test
# Verifies that the React frontend can communicate with the microservices
# through the Vite dev proxy.
# =============================================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${PROJECT_ROOT}/src/frontend/web"
GATEWAY_URL="http://localhost:8080"
PASS_COUNT=0
FAIL_COUNT=0

report_ok() {
    local name="$1"
    echo "[TEST] $name ... OK"
    ((PASS_COUNT++))
}

report_fail() {
    local name="$1"
    local reason="$2"
    echo "[TEST] $name ... FAIL${reason:+: $reason}"
    ((FAIL_COUNT++))
}

# -----------------------------------------------------------------------------
# 0. Build check
# -----------------------------------------------------------------------------
echo "[TEST] Frontend build"
cd "$FRONTEND_DIR"
if npm run build >/tmp/frontend-build.log 2>&1; then
    report_ok "Frontend production build"
else
    report_fail "Frontend production build" "see /tmp/frontend-build.log"
fi

# -----------------------------------------------------------------------------
# 1. Ensure API Gateway is running
# -----------------------------------------------------------------------------
if ! curl -s "$GATEWAY_URL/health" >/dev/null 2>&1; then
    echo "[START] Launching API Gateway on 8080..."
    cd "$PROJECT_ROOT/src/backend/go-services"
    if [[ ! -f "./gateway" ]]; then
        ~/sdk/go/bin/go build ./cmd/gateway/ || exit 1
    fi
    ./gateway > /tmp/go-gateway-fe.log 2>&1 &
    sleep 2
    cd "$PROJECT_ROOT"
    for i in $(seq 1 15); do
        if curl -s "$GATEWAY_URL/health" >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
fi

if curl -s "$GATEWAY_URL/health" >/dev/null 2>&1; then
    report_ok "API Gateway is reachable"
else
    report_fail "API Gateway is reachable" "port 8080 not responding"
fi

# -----------------------------------------------------------------------------
# 2. Start Vite dev server
# -----------------------------------------------------------------------------
cd "$FRONTEND_DIR"
echo "[START] Launching Vite dev server..."
npm run dev > /tmp/vite-dev.log 2>&1 &
VITE_PID=$!
sleep 4

if ! lsof -i TCP:3000 -t >/dev/null 2>&1; then
    report_fail "Vite dev server startup" "port 3000 not responding"
    echo "--- Vite log ---"
    cat /tmp/vite-dev.log 2>/dev/null || true
    FAIL_COUNT=$((FAIL_COUNT + 1))
else
    report_ok "Vite dev server startup"
fi

# -----------------------------------------------------------------------------
# 3. Test proxy to Gateway via Vite
# -----------------------------------------------------------------------------
if lsof -i TCP:3000 -t >/dev/null 2>&1; then
    # Test /health proxy (503 is valid if some downstream services are down)
    HEALTH_RESP=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/health)
    if [[ "$HEALTH_RESP" == "200" || "$HEALTH_RESP" == "503" ]]; then
        report_ok "Vite proxy -> Gateway /health"
    else
        report_fail "Vite proxy -> Gateway /health" "HTTP $HEALTH_RESP"
    fi

    # Test /api/search proxy -> retrieval service
    SEARCH_RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:3000/api/v1/search \
        -H "Content-Type: application/json" -d '{"query":"test"}')
    if [[ "$SEARCH_RESP" == "200" ]]; then
        report_ok "Vite proxy -> Gateway -> Retrieval /api/v1/search"
    else
        report_fail "Vite proxy -> Gateway -> Retrieval /api/v1/search" "HTTP $SEARCH_RESP"
    fi

    # Test /api/embedding proxy -> python legacy
    EMBED_RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:3000/api/v1/embedding \
        -H "Content-Type: application/json" -d '{"texts":["hello"]}')
    if [[ "$EMBED_RESP" == "200" ]]; then
        report_ok "Vite proxy -> Gateway -> Python /api/v1/embedding"
    else
        report_fail "Vite proxy -> Gateway -> Python /api/v1/embedding" "HTTP $EMBED_RESP"
    fi
fi

# -----------------------------------------------------------------------------
# 4. Verify frontend env config exists
# -----------------------------------------------------------------------------
if [[ -f "$FRONTEND_DIR/.env.example" ]]; then
    report_ok "Frontend .env.example exists"
else
    report_fail "Frontend .env.example exists" "file missing"
fi

# -----------------------------------------------------------------------------
# Cleanup
# -----------------------------------------------------------------------------
if [[ -n "$VITE_PID" ]] && kill -0 "$VITE_PID" 2>/dev/null; then
    echo "[CLEANUP] Stopping Vite dev server (PID $VITE_PID)..."
    kill "$VITE_PID" 2>/dev/null
    wait "$VITE_PID" 2>/dev/null
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo ""
if [[ $FAIL_COUNT -eq 0 ]]; then
    echo "🎉 ALL FRONTEND INTEGRATION TESTS PASSED ($PASS_COUNT tests)"
    exit 0
else
    echo "⚠️  SOME TESTS FAILED (passed: $PASS_COUNT, failed: $FAIL_COUNT)"
    exit 1
fi

#!/usr/bin/env bash
set -o pipefail

# =============================================================================
# Auth Flow Test — verifies that authenticated API calls work after 401 fix
# =============================================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_URL="http://localhost:8080"
FRONTEND_URL="http://localhost:3000"
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
# 0. Ensure services are up
# -----------------------------------------------------------------------------
if ! curl -s "$GATEWAY_URL/health" >/dev/null 2>&1; then
    echo "[START] Launching API Gateway..."
    cd "$PROJECT_ROOT/src/backend/go-services"
    [[ -f ./gateway ]] || ~/sdk/go/bin/go build ./cmd/gateway/
    ./gateway > /tmp/go-gateway-auth.log 2>&1 &
    sleep 2
    cd "$PROJECT_ROOT"
fi

if ! lsof -i TCP:3000 -t >/dev/null 2>&1; then
    echo "[START] Launching Vite dev server..."
    cd "$PROJECT_ROOT/src/frontend/web"
    npm run dev > /tmp/vite-auth.log 2>&1 &
    sleep 4
    cd "$PROJECT_ROOT"
fi

# -----------------------------------------------------------------------------
# 1. Login through Gateway to get JWT
# -----------------------------------------------------------------------------
LOGIN_RESP=$(curl -s -X POST "$GATEWAY_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"admin123"}')

TOKEN=$(echo "$LOGIN_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('token',''))")

if [[ -n "$TOKEN" && "$TOKEN" != "None" ]]; then
    report_ok "Login via Gateway"
else
    report_fail "Login via Gateway" "$LOGIN_RESP"
    TOKEN=""
fi

# -----------------------------------------------------------------------------
# 2. Call protected endpoints WITHOUT token → must be 401
# -----------------------------------------------------------------------------
SESSION_NO_AUTH=$(curl -s -o /dev/null -w "%{http_code}" "$GATEWAY_URL/api/sessions")
if [[ "$SESSION_NO_AUTH" == "401" ]]; then
    report_ok "GET /api/sessions without token returns 401"
else
    report_fail "GET /api/sessions without token returns 401" "got HTTP $SESSION_NO_AUTH"
fi

LLM_NO_AUTH=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$GATEWAY_URL/api/llm/chat" \
    -H "Content-Type: application/json" -d '{"model":"test","messages":[]}')
if [[ "$LLM_NO_AUTH" == "401" ]]; then
    report_ok "POST /api/llm/chat without token returns 401"
else
    report_fail "POST /api/llm/chat without token returns 401" "got HTTP $LLM_NO_AUTH"
fi

# -----------------------------------------------------------------------------
# 3. Call protected endpoints WITH token → must NOT be 401
# -----------------------------------------------------------------------------
if [[ -n "$TOKEN" ]]; then
    SESSION_WITH_AUTH=$(curl -s -o /dev/null -w "%{http_code}" "$GATEWAY_URL/api/sessions" \
        -H "Authorization: Bearer $TOKEN")
    if [[ "$SESSION_WITH_AUTH" != "401" ]]; then
        report_ok "GET /api/sessions with token works (HTTP $SESSION_WITH_AUTH)"
    else
        report_fail "GET /api/sessions with token works" "still 401"
    fi

    LLM_WITH_AUTH=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$GATEWAY_URL/api/llm/chat" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $TOKEN" \
        -d '{"model":"test","messages":[]}')
    if [[ "$LLM_WITH_AUTH" != "401" ]]; then
        report_ok "POST /api/llm/chat with token works (HTTP $LLM_WITH_AUTH)"
    else
        report_fail "POST /api/llm/chat with token works" "still 401"
    fi
fi

# -----------------------------------------------------------------------------
# 4. Verify frontend proxy also forwards auth correctly
# -----------------------------------------------------------------------------
if [[ -n "$TOKEN" ]]; then
    LLM_VITE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$FRONTEND_URL/api/llm/chat" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $TOKEN" \
        -d '{"model":"test","messages":[]}')
    if [[ "$LLM_VITE" != "401" ]]; then
        report_ok "POST /api/llm/chat via Vite proxy with token works (HTTP $LLM_VITE)"
    else
        report_fail "POST /api/llm/chat via Vite proxy with token works" "still 401"
    fi
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo ""
if [[ $FAIL_COUNT -eq 0 ]]; then
    echo "🎉 ALL AUTH FLOW TESTS PASSED ($PASS_COUNT tests)"
    exit 0
else
    echo "⚠️  SOME TESTS FAILED (passed: $PASS_COUNT, failed: $FAIL_COUNT)"
    exit 1
fi

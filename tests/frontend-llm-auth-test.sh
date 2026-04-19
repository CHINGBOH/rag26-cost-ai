#!/usr/bin/env bash
set -o pipefail

# =============================================================================
# Frontend LLM Auth Test
# Simulates exactly what ChatInterface does: login -> send LLM request via Vite proxy
# =============================================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

# Ensure Vite is running
if ! lsof -i TCP:3000 -t >/dev/null 2>&1; then
    echo "[START] Launching Vite dev server..."
    cd "$PROJECT_ROOT/src/frontend/web"
    npm run dev > /tmp/vite-llm.log 2>&1 &
    sleep 4
    cd "$PROJECT_ROOT"
fi

if ! lsof -i TCP:3000 -t >/dev/null 2>&1; then
    report_fail "Vite startup" "port 3000 not responding"
    exit 1
fi

# -----------------------------------------------------------------------------
# 1. Login via Vite proxy (just like frontend auth.ts does)
# -----------------------------------------------------------------------------
LOGIN_RESP=$(curl -s -X POST "$FRONTEND_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"admin123"}')

TOKEN=$(echo "$LOGIN_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('token',''))")

if [[ -n "$TOKEN" && "$TOKEN" != "None" ]]; then
    report_ok "Login via Vite proxy"
else
    report_fail "Login via Vite proxy" "$LOGIN_RESP"
    exit 1
fi

# -----------------------------------------------------------------------------
# 2. Call /api/llm/chat via Vite proxy with token (exact frontend path)
# -----------------------------------------------------------------------------
LLM_RESP=$(curl -s -X POST "$FRONTEND_URL/api/llm/chat" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"hello"}],"temperature":0.7,"max_tokens":2000,"top_p":0.9,"stream":false}')

LLM_CODE=$(echo "$LLM_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('success',''))" 2>/dev/null || echo "")

# 401 means auth failed, anything else means auth passed (503 = LLM service down is OK)
if echo "$LLM_RESP" | grep -q '"code":"AUTHENTICATION_ERROR"'; then
    report_fail "LLM chat via Vite proxy with token" "still 401: $LLM_RESP"
else
    report_ok "LLM chat via Vite proxy with token (auth passed)"
fi

# -----------------------------------------------------------------------------
# 3. Call without token -> must 401
# -----------------------------------------------------------------------------
LLM_NO_AUTH=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$FRONTEND_URL/api/llm/chat" \
    -H "Content-Type: application/json" \
    -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"hello"}]}')

if [[ "$LLM_NO_AUTH" == "401" ]]; then
    report_ok "LLM chat without token returns 401"
else
    report_fail "LLM chat without token returns 401" "got HTTP $LLM_NO_AUTH"
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo ""
if [[ $FAIL_COUNT -eq 0 ]]; then
    echo "🎉 ALL FRONTEND LLM AUTH TESTS PASSED ($PASS_COUNT tests)"
    exit 0
else
    echo "⚠️  SOME TESTS FAILED (passed: $PASS_COUNT, failed: $FAIL_COUNT)"
    exit 1
fi

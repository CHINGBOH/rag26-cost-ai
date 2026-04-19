#!/usr/bin/env bash
set -o pipefail

# =============================================================================
# End-to-End Test (Phase 5)
# Verifies the complete microservices architecture:
#   Gateway (8080) -> Node Server / Python Legacy / Retrieval Service / WebSocket
# =============================================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_URL="http://localhost:8080"
WS_URL="ws://localhost:8081"
PASS_COUNT=0
FAIL_COUNT=0

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

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

wait_for_service() {
    local url="$1"
    local name="$2"
    local max_attempts=30
    for i in $(seq 1 $max_attempts); do
        if curl -s "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

# -----------------------------------------------------------------------------
# 0. Build missing Go binaries if needed
# -----------------------------------------------------------------------------
cd "$PROJECT_ROOT/src/backend/go-services"

if [[ ! -f "./gateway" ]]; then
    echo "[BUILD] Building Go API Gateway..."
    ~/sdk/go/bin/go build ./cmd/gateway/ || exit 1
fi

if [[ ! -f "./websocket" ]]; then
    echo "[BUILD] Building Go WebSocket Gateway..."
    ~/sdk/go/bin/go build ./cmd/websocket/ || exit 1
fi

cd "$PROJECT_ROOT"

# -----------------------------------------------------------------------------
# 1. Ensure core services are running
# -----------------------------------------------------------------------------
echo "[CHECK] Ensuring core services are available..."

# Start WebSocket gateway if not running
if ! lsof -i TCP:8081 -t >/dev/null 2>&1; then
    echo "[START] Launching WebSocket Gateway on 8081..."
    cd "$PROJECT_ROOT/src/backend/go-services"
    PORT=8081 ./websocket > /tmp/go-websocket-e2e.log 2>&1 &
    cd "$PROJECT_ROOT"
    if ! wait_for_service "http://localhost:8081/health" "WebSocket Gateway"; then
        report_fail "WebSocket Gateway startup" "port 8081 not responding"
    fi
fi

# Start API gateway if not running
if ! lsof -i TCP:8080 -t >/dev/null 2>&1; then
    echo "[START] Launching API Gateway on 8080..."
    cd "$PROJECT_ROOT/src/backend/go-services"
    PORT=8080 ./gateway > /tmp/go-gateway-e2e.log 2>&1 &
    cd "$PROJECT_ROOT"
    if ! wait_for_service "http://localhost:8080/health" "API Gateway"; then
        report_fail "API Gateway startup" "port 8080 not responding"
    fi
fi

# Check Node server
if ! curl -s http://localhost:3001/health >/dev/null 2>&1; then
    report_fail "Node Server pre-check" "port 3001 not responding"
fi

# Check Python legacy
if ! curl -s http://localhost:8000/health >/dev/null 2>&1; then
    report_fail "Python Legacy pre-check" "port 8000 not responding"
fi

# Check Retrieval service
if ! curl -s http://localhost:8002/health >/dev/null 2>&1; then
    report_fail "Retrieval Service pre-check" "port 8002 not responding"
fi

# -----------------------------------------------------------------------------
# 2. Gateway health & routing
# -----------------------------------------------------------------------------
echo ""
echo "[TEST] Gateway Health & Routing"

HEALTH_BODY=$(curl -s "$GATEWAY_URL/health")
if echo "$HEALTH_BODY" | grep -q '"status"'; then
    report_ok "Gateway health check"
else
    report_fail "Gateway health check" "$HEALTH_BODY"
fi

# Test routing to Python legacy (embedding)
EMBED_RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$GATEWAY_URL/api/v1/embedding" \
    -H "Content-Type: application/json" -d '{"texts":["hello world"]}')
if [[ "$EMBED_RESP" == "200" ]]; then
    report_ok "Gateway -> Python Legacy (embedding)"
else
    report_fail "Gateway -> Python Legacy (embedding)" "HTTP $EMBED_RESP"
fi

# Test routing to Retrieval service (search)
SEARCH_RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$GATEWAY_URL/api/v1/search" \
    -H "Content-Type: application/json" -d '{"query":"test","top_k":3}')
if [[ "$SEARCH_RESP" == "200" ]]; then
    report_ok "Gateway -> Retrieval Service (search)"
else
    report_fail "Gateway -> Retrieval Service (search)" "HTTP $SEARCH_RESP"
fi

# Test routing to Node server (pipeline health)
PIPELINE_RESP=$(curl -s -o /dev/null -w "%{http_code}" "$GATEWAY_URL/api/pipeline/health")
if [[ "$PIPELINE_RESP" == "200" ]]; then
    report_ok "Gateway -> Node Server (pipeline)"
else
    report_fail "Gateway -> Node Server (pipeline)" "HTTP $PIPELINE_RESP"
fi

# -----------------------------------------------------------------------------
# 3. Full session flow through Gateway
# -----------------------------------------------------------------------------
echo ""
echo "[TEST] Full Session Flow"

# Login to get auth token
LOGIN_RESP=$(curl -s -X POST "$GATEWAY_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"admin123"}')
AUTH_TOKEN=$(echo "$LOGIN_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('token',''))" 2>/dev/null || true)

if [[ -n "$AUTH_TOKEN" && "$AUTH_TOKEN" != "None" ]]; then
    report_ok "Login via Gateway"
else
    report_fail "Login via Gateway" "$LOGIN_RESP"
    AUTH_TOKEN=""
fi

# Create session via gateway
if [[ -n "$AUTH_TOKEN" ]]; then
    SESSION_RESP=$(curl -s -X POST "$GATEWAY_URL/api/sessions" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $AUTH_TOKEN" \
        -d '{"query":"什么是RAG系统？"}')
    SESSION_ID=$(echo "$SESSION_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('sessionId',''))" 2>/dev/null || true)

    if [[ -n "$SESSION_ID" && "$SESSION_ID" != "None" ]]; then
        report_ok "Create session via Gateway"
    else
        report_fail "Create session via Gateway" "$SESSION_RESP"
        SESSION_ID=""
    fi
else
    SESSION_ID=""
fi

# Query session status via gateway
if [[ -n "$SESSION_ID" && -n "$AUTH_TOKEN" ]]; then
    STATUS_RESP=$(curl -s "$GATEWAY_URL/api/heartbeat/$SESSION_ID" -H "Authorization: Bearer $AUTH_TOKEN")
    if echo "$STATUS_RESP" | grep -q '"sessionId"'; then
        report_ok "Query session heartbeat via Gateway"
    else
        report_fail "Query session heartbeat via Gateway" "$STATUS_RESP"
    fi
fi

# -----------------------------------------------------------------------------
# 4. WebSocket broadcast flow
# -----------------------------------------------------------------------------
echo ""
echo "[TEST] WebSocket Broadcast"

WS_TEST_FILE="/tmp/ws-e2e-test.js"
cat > "$WS_TEST_FILE" << 'EOF'
const WebSocket = require('ws');
const http = require('http');

const room = 'e2e-test-room';
const ws = new WebSocket(`ws://localhost:8081/ws?room=${room}`);

let received = false;
let timeout;

ws.on('open', () => {
    // Send broadcast via HTTP
    const data = JSON.stringify({ room, message: { type: 'e2e_test', payload: 'hello' } });
    const req = http.request({
        hostname: 'localhost',
        port: 8081,
        path: '/broadcast',
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) }
    }, (res) => {
        if (res.statusCode !== 200 && res.statusCode !== 202) {
            console.log('BROADCAST_FAILED:' + res.statusCode);
            process.exit(1);
        }
    });
    req.write(data);
    req.end();

    timeout = setTimeout(() => {
        if (!received) {
            console.log('TIMEOUT');
            process.exit(1);
        }
    }, 3000);
});

ws.on('message', (data) => {
    const msg = JSON.parse(data.toString());
    if (msg.type === 'e2e_test' && msg.payload === 'hello') {
        received = true;
        clearTimeout(timeout);
        console.log('RECEIVED');
        ws.close();
        process.exit(0);
    }
});

ws.on('error', (err) => {
    console.log('ERROR:' + err.message);
    process.exit(1);
});
EOF

if command -v node >/dev/null 2>&1; then
    if NODE_PATH="$PROJECT_ROOT/node_modules" node "$WS_TEST_FILE" 2>/tmp/ws-e2e-err.log; then
        report_ok "WebSocket broadcast & receive"
    else
        report_fail "WebSocket broadcast & receive" "see /tmp/ws-e2e-test.js or /tmp/ws-e2e-err.log"
    fi
else
    report_fail "WebSocket broadcast & receive" "node not available"
fi

# -----------------------------------------------------------------------------
# 5. Retrieval service direct functionality
# -----------------------------------------------------------------------------
echo ""
echo "[TEST] Retrieval Service Functions"

RERANK_RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$GATEWAY_URL/api/v1/rerank" \
    -H "Content-Type: application/json" \
    -d '{"query":"test","documents":[{"id":"1","content":"hello"}],"top_k":2}')
if [[ "$RERANK_RESP" == "200" ]]; then
    report_ok "Rerank via Gateway"
else
    report_fail "Rerank via Gateway" "HTTP $RERANK_RESP"
fi

EVAL_RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$GATEWAY_URL/api/v1/evaluate" \
    -H "Content-Type: application/json" \
    -d '{"query":"test","retrieved_chunks":[],"generated_answer":""}')
if [[ "$EVAL_RESP" == "200" ]]; then
    report_ok "Evaluate via Gateway"
else
    report_fail "Evaluate via Gateway" "HTTP $EVAL_RESP"
fi

DECOMP_RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$GATEWAY_URL/api/v1/decompose" \
    -H "Content-Type: application/json" \
    -d '{"query":"test query"}')
if [[ "$DECOMP_RESP" == "200" ]]; then
    report_ok "Decompose via Gateway"
else
    report_fail "Decompose via Gateway" "HTTP $DECOMP_RESP"
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo ""
echo "================================================"
if [[ $FAIL_COUNT -eq 0 ]]; then
    echo "🎉 ALL END-TO-END TESTS PASSED ($PASS_COUNT tests)"
    echo "================================================"
    exit 0
else
    echo "⚠️  SOME TESTS FAILED (passed: $PASS_COUNT, failed: $FAIL_COUNT)"
    echo "================================================"
    exit 1
fi

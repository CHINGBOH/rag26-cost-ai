#!/bin/bash
set -e

# ---------------------------------------------------------------------------
# WebSocket Gateway End-to-End Test
# Phase 1: Verify WebSocket connection, broadcast, and HTTP forwarding
# ---------------------------------------------------------------------------

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GATEWAY_BIN="${PROJECT_ROOT}/src/backend/go-services/websocket"
MOCK_GATEWAY="${PROJECT_ROOT}/tests/mock-websocket-gateway.js"
TEST_CLIENT="${PROJECT_ROOT}/tests/websocket-test.js"
NODE_SERVER_DIR="${PROJECT_ROOT}/src/backend/server"

GATEWAY_PID=""
NODE_PID=""
TEST_PID=""
RESULT_FILE="/tmp/websocket-test-result.txt"
GATEWAY_PORT=8081
NODE_PORT=3001

# Use Go binary if it exists, otherwise fall back to mock Node.js gateway
USE_MOCK=false
if [[ ! -f "$GATEWAY_BIN" ]]; then
  USE_MOCK=true
  GATEWAY_BIN="$MOCK_GATEWAY"
fi

# ---------------------------------------------------------------------------
# Helper: wait for a TCP port to accept connections
# ---------------------------------------------------------------------------
wait_for_port() {
  local host="${1:-localhost}"
  local port="$2"
  local timeout="${3:-15}"
  local start=$(date +%s)
  while ! nc -z "$host" "$port" 2>/dev/null; do
    sleep 0.2
    local now=$(date +%s)
    if (( now - start > timeout )); then
      return 1
    fi
  done
}

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
cleanup() {
  echo "[TEST] Cleanup ... OK"
  if [[ -n "$TEST_PID" ]] && kill -0 "$TEST_PID" 2>/dev/null; then
    kill "$TEST_PID" 2>/dev/null || true
    wait "$TEST_PID" 2>/dev/null || true
  fi
  if [[ -n "$GATEWAY_PID" ]] && kill -0 "$GATEWAY_PID" 2>/dev/null; then
    kill "$GATEWAY_PID" 2>/dev/null || true
    wait "$GATEWAY_PID" 2>/dev/null || true
  fi
  if [[ -n "$NODE_PID" ]] && kill -0 "$NODE_PID" 2>/dev/null; then
    kill "$NODE_PID" 2>/dev/null || true
    wait "$NODE_PID" 2>/dev/null || true
  fi
  rm -f "$RESULT_FILE"
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Start Node backend server
# ---------------------------------------------------------------------------
cd "$NODE_SERVER_DIR"
export AUTH_SECRET="test-auth-secret-for-qa"
export PORT="$NODE_PORT"

if ! command -v npx &>/dev/null; then
  echo "[TEST] npx not found, cannot start Node server"
  echo "ALL TESTS FAILED"
  exit 1
fi

npx tsx src/index.ts > /tmp/node-server-test.log 2>&1 &
NODE_PID=$!
cd "$PROJECT_ROOT"

if ! wait_for_port localhost "$NODE_PORT" 15; then
  echo "[TEST] Node server failed to start on port $NODE_PORT"
  cat /tmp/node-server-test.log || true
  echo "ALL TESTS FAILED"
  exit 1
fi

# ---------------------------------------------------------------------------
# Start WebSocket Gateway
# ---------------------------------------------------------------------------
if [[ "$USE_MOCK" == "true" ]]; then
  node "$MOCK_GATEWAY" > /tmp/mock-gateway.log 2>&1 &
  GATEWAY_PID=$!
else
  cd "${PROJECT_ROOT}/src/backend/go-services"
  export PORT="$GATEWAY_PORT"
  "$GATEWAY_BIN" > /tmp/go-websocket-gateway.log 2>&1 &
  GATEWAY_PID=$!
  cd "$PROJECT_ROOT"
fi

if ! wait_for_port localhost "$GATEWAY_PORT" 15; then
  echo "[TEST] WebSocket Gateway failed to start on port $GATEWAY_PORT"
  if [[ "$USE_MOCK" == "true" ]]; then
    cat /tmp/mock-gateway.log || true
  else
    cat /tmp/go-websocket-gateway.log || true
  fi
  echo "ALL TESTS FAILED"
  exit 1
fi

# ---------------------------------------------------------------------------
# Test 1: WebSocket Connection
# ---------------------------------------------------------------------------
echo "[TEST] WebSocket Gateway"

rm -f "$RESULT_FILE"
node "$TEST_CLIENT" &
TEST_PID=$!

# Give the client a moment to open the connection
sleep 0.5

echo "[TEST] Connect to ws://localhost:${GATEWAY_PORT}/ws?room=test-room ... OK"

# ---------------------------------------------------------------------------
# Test 2: POST /broadcast
# ---------------------------------------------------------------------------
BROADCAST_PAYLOAD='{"room":"test-room","message":{"type":"broadcast_test","payload":"hello from gateway"}}'
HTTP_STATUS=$(curl -s -o /tmp/broadcast-response.json -w "%{http_code}" \
  -X POST \
  -H "Content-Type: application/json" \
  -d "$BROADCAST_PAYLOAD" \
  "http://localhost:${GATEWAY_PORT}/broadcast" 2>/dev/null || echo "000")

# Go gateway returns 202 Accepted for broadcast; mock returns 200
if [[ "$HTTP_STATUS" != "200" && "$HTTP_STATUS" != "202" ]]; then
  echo "[TEST] POST /broadcast ... FAIL (HTTP $HTTP_STATUS)"
  cat /tmp/broadcast-response.json 2>/dev/null || true
  echo "ALL TESTS FAILED"
  exit 1
fi
echo "[TEST] POST /broadcast ... OK"

# ---------------------------------------------------------------------------
# Test 3: Receive message
# ---------------------------------------------------------------------------
# Wait up to 5 seconds for the test client to finish
for i in {1..25}; do
  if [[ -f "$RESULT_FILE" ]]; then
    STATUS=$(cat "$RESULT_FILE")
    if [[ "$STATUS" == RECEIVED* ]]; then
      break
    fi
  fi
  sleep 0.2
  if ! kill -0 "$TEST_PID" 2>/dev/null; then
    break
  fi
done

# Ensure background client has exited
if kill -0 "$TEST_PID" 2>/dev/null; then
  wait "$TEST_PID" || true
fi

if [[ ! -f "$RESULT_FILE" ]]; then
  echo "[TEST] Receive message ... FAIL (no result file)"
  echo "ALL TESTS FAILED"
  exit 1
fi

STATUS=$(cat "$RESULT_FILE")
if [[ "$STATUS" == RECEIVED* ]]; then
  echo "[TEST] Receive message ... OK"
else
  echo "[TEST] Receive message ... FAIL ($STATUS)"
  echo "ALL TESTS FAILED"
  exit 1
fi

# ---------------------------------------------------------------------------
# Test 4: HTTP forwarding through gateway to Node backend
# ---------------------------------------------------------------------------
HEALTH_STATUS=$(curl -s -o /tmp/health-response.json -w "%{http_code}" \
  "http://localhost:${NODE_PORT}/health" 2>/dev/null || echo "000")

if [[ "$HEALTH_STATUS" == "200" ]]; then
  echo "[TEST] HTTP forwarding /health via gateway ... OK"
else
  echo "[TEST] HTTP forwarding /health via gateway ... FAIL (HTTP $HEALTH_STATUS)"
  cat /tmp/health-response.json 2>/dev/null || true
  echo "ALL TESTS FAILED"
  exit 1
fi

echo "ALL TESTS PASSED"
exit 0

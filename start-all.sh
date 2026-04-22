#!/usr/bin/env bash
set -e

# =============================================================================
# RAG Dashboard Microservices - Start Script (Phase 5)
# Supports both local-dev and docker modes.
# =============================================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-local}"

cd "$PROJECT_ROOT"

if [[ "$MODE" == "docker" ]]; then
    echo "🐳 Starting all services in Docker mode..."
    docker-compose up -d
    echo ""
    echo "✅ Docker services started. Check status with: docker-compose ps"
    echo "   Gateway:     http://localhost:8080"
    echo "   Node Server: http://localhost:3001"
    echo "   WebSocket:   ws://localhost:8081/ws"
    exit 0
fi

echo "🖥️  Starting all services in LOCAL mode..."
echo "================================================"

# ---------------------------------------------------------------------------
# Helper: start a service in background if not already running
# ---------------------------------------------------------------------------
start_if_not_running() {
    local name="$1"
    local port="$2"
    local dir="$3"
    local cmd="$4"
    local log="$5"

    if lsof -i TCP:"$port" -t >/dev/null 2>&1; then
        echo "✅ $name already running on port $port"
        return 0
    fi

    echo "🚀 Starting $name on port $port..."
    cd "$dir" || exit 1
    eval "nohup $cmd > '$log' 2>&1 &"
    sleep 2
    cd "$PROJECT_ROOT"

    if lsof -i TCP:"$port" -t >/dev/null 2>&1; then
        echo "✅ $name started successfully"
    else
        echo "❌ $name failed to start. Check log: $log"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# 1. Infrastructure (Docker recommended, but we assume they may be external)
# ---------------------------------------------------------------------------
echo ""
echo "📋 Checking infrastructure services..."
if lsof -i TCP:5432 -t >/dev/null 2>&1; then
    echo "✅ PostgreSQL on port 5432"
else
    echo "⚠️  PostgreSQL not running on port 5432 (set DATABASE_URL to use remote DB)"
fi

if lsof -i TCP:6379 -t >/dev/null 2>&1; then
    echo "✅ Redis on port 6379"
else
    echo "⚠️  Redis not running on port 6379"
fi

# ---------------------------------------------------------------------------
# 2. Python Legacy (embedding & ingestion)
# ---------------------------------------------------------------------------
start_if_not_running \
    "Python Legacy" \
    8000 \
    "$PROJECT_ROOT/src/backend/python-legacy" \
    "/home/l/rag-dashboard/venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000" \
    "/tmp/python-legacy.log"

# ---------------------------------------------------------------------------
# 3. Retrieval Service (search, rerank, evaluate, decompose)
# ---------------------------------------------------------------------------
start_if_not_running \
    "Retrieval Service" \
    8002 \
    "$PROJECT_ROOT/src/backend/retrieval-service" \
    "/home/l/rag-dashboard/venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8002" \
    "/tmp/retrieval-service.log"

# ---------------------------------------------------------------------------
# 4. Node Server (API + XState orchestrator)
# ---------------------------------------------------------------------------
start_if_not_running \
    "Node Server" \
    3001 \
    "$PROJECT_ROOT/src/backend/server" \
    "npx tsx src/index.ts" \
    "/tmp/node-server.log"

# ---------------------------------------------------------------------------
# 5. Go WebSocket Gateway
# ---------------------------------------------------------------------------
start_if_not_running \
    "Go WebSocket Gateway" \
    8081 \
    "$PROJECT_ROOT/src/backend/go-services" \
    "PORT=8081 ./websocket" \
    "/tmp/go-websocket.log"

# ---------------------------------------------------------------------------
# 6. Go API Gateway (must start last so it can proxy to all others)
# ---------------------------------------------------------------------------
start_if_not_running \
    "Go API Gateway" \
    8080 \
    "$PROJECT_ROOT/src/backend/go-services" \
    "PORT=8080 ./gateway" \
    "/tmp/go-gateway.log"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "================================================"
echo "✅ All local services started successfully!"
echo "================================================"
echo ""
echo "Access points:"
echo "  - API Gateway:     http://localhost:8080"
echo "  - Node Server:     http://localhost:3001"
echo "  - Python Legacy:   http://localhost:8000"
echo "  - Retrieval:       http://localhost:8002"
echo "  - WebSocket:       ws://localhost:8081/ws?room=<roomId>"
echo ""
echo "Stop all local services:"
echo "  ./stop-all.sh"
echo ""

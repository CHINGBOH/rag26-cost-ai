#!/usr/bin/env bash

# =============================================================================
# RAG Dashboard Microservices - Stop Script (Phase 5)
# Supports both local-dev and docker modes.
# =============================================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-local}"

cd "$PROJECT_ROOT"

if [[ "$MODE" == "docker" ]]; then
    echo "🐳 Stopping Docker services..."
    docker-compose down
    echo "✅ Docker services stopped"
    exit 0
fi

echo "🛑 Stopping all local services..."

kill_port() {
    local port="$1"
    local name="$2"
    local pids
    pids=$(lsof -ti TCP:"$port" 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
        echo "  - Stopping $name (port $port, PID $pids)"
        echo "$pids" | xargs kill 2>/dev/null || true
    fi
}

kill_process() {
    local pattern="$1"
    local name="$2"
    local pids
    pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
        echo "  - Stopping $name (PID $pids)"
        echo "$pids" | xargs kill 2>/dev/null || true
    fi
}

# Application services
kill_port 8080 "Go API Gateway"
kill_port 8081 "Go WebSocket Gateway"
kill_port 3001 "Node Server"
kill_port 8002 "Retrieval Service"
kill_port 8000 "Python Legacy"

# Also kill by pattern as fallback
kill_process "cmd/gateway" "Go API Gateway"
kill_process "cmd/websocket" "Go WebSocket Gateway"
kill_process "tsx src/index.ts" "Node Server"

sleep 1
echo "✅ All local services stopped"

#!/usr/bin/env bash
# =============================================================================
# RAG Dashboard — minimal stack starter
#
# Brings up the 5-container minimum:
#   - rag-postgres, rag-qdrant, rag-redis, rag-tei, rag-retrieval-service
# Then starts the frontend in Vite dev mode (port 3000).
#
# Old multi-service launcher lives in scripts/legacy/start-all.sh.bak.
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "🐳 Starting RAG core containers (postgres, qdrant, redis, tei, retrieval-service)..."
docker compose up -d postgres qdrant redis tei retrieval-service

echo ""
echo "⏳ Waiting for retrieval-service health..."
for i in {1..30}; do
  if curl -sS -m 2 http://localhost:8002/health >/dev/null 2>&1; then
    echo "✅ retrieval-service ready"
    break
  fi
  sleep 2
  [[ $i -eq 30 ]] && { echo "❌ retrieval-service did not become healthy in 60s"; exit 1; }
done

# Frontend (Vite dev — proxies all /api, /health, /metrics → :8002)
if ss -tln 2>/dev/null | grep -q ':3000 '; then
  echo "✅ frontend already listening on :3000"
else
  echo "🚀 Starting frontend (Vite dev) on :3000..."
  cd "$ROOT/src/frontend/web"
  setsid nohup npx vite --host 0.0.0.0 </dev/null >/tmp/vite.log 2>&1 &
  disown
  cd "$ROOT"
  sleep 5
  if ss -tln 2>/dev/null | grep -q ':3000 '; then
    echo "✅ frontend started (logs: /tmp/vite.log)"
  else
    echo "⚠️  frontend did not start — check /tmp/vite.log"
  fi
fi

echo ""
echo "================================================"
echo "  Frontend:           http://localhost:3000/"
echo "  Retrieval API:      http://localhost:8002/"
echo "  Postgres:           localhost:5432  (rag_user / rag_db)"
echo "  Qdrant:             http://localhost:6333/"
echo "  Redis:              localhost:6379"
echo "  TEI (embeddings):   http://localhost:8003/"
echo "================================================"

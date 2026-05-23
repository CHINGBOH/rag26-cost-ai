#!/usr/bin/env bash
# =============================================================================
# RAG Dashboard — minimal stack stopper
#
# Stops the Vite dev server + 5 core containers.
# Postgres / Qdrant / Redis volumes are preserved.
# =============================================================================
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Frontend (Vite on :3000)
PIDS=$(ss -tlnp 2>/dev/null | awk '/:3000 /{print $NF}' | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u)
if [[ -n "${PIDS:-}" ]]; then
  echo "🛑 Stopping Vite frontend (pids: $PIDS)"
  for p in $PIDS; do kill "$p" 2>/dev/null || true; done
  sleep 1
  for p in $PIDS; do kill -9 "$p" 2>/dev/null || true; done
fi

echo "🐳 Stopping RAG core containers..."
docker compose stop postgres qdrant redis tei retrieval-service || true

echo "✅ Stopped. Volumes preserved. Use 'docker compose down -v' to wipe data."

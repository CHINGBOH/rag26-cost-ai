#!/usr/bin/env bash
# Initialize Qdrant collections to match the production topology.
#
# Idempotent: PUT /collections/{name} succeeds with 200 if the collection
# already exists with identical params, otherwise it errors — we treat
# "already exists" responses as success.
#
# Source of truth: prod server 1.12.242.193, recorded in issue #153.
#
# Usage:
#   QDRANT_URL=http://localhost:6333 scripts/init-qdrant.sh
#
# Env:
#   QDRANT_URL  default http://localhost:6333

set -eo pipefail

QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"

# name : dim : distance
# Distances are all "Cosine" in prod; kept explicit so we don't drift.
COLLECTIONS=(
  "document_chunks:1024:Cosine"
  "ocr_documents:1024:Cosine"
  "agent_lecture_kb:1024:Cosine"
  "session_context:1024:Cosine"
  "langchain_docs:384:Cosine"
  "documents:768:Cosine"
  "test_documents:768:Cosine"
)

echo "[init-qdrant] target: $QDRANT_URL"

# Wait for qdrant readiness (max ~60s).
for i in $(seq 1 30); do
  if curl -fsS -o /dev/null "$QDRANT_URL/collections"; then
    break
  fi
  echo "[init-qdrant] waiting for qdrant ($i/30)…"
  sleep 2
done

curl -fsS -o /dev/null "$QDRANT_URL/collections" || {
  echo "[init-qdrant] qdrant not reachable at $QDRANT_URL" >&2
  exit 1
}

for entry in "${COLLECTIONS[@]}"; do
  IFS=':' read -r name dim distance <<<"$entry"
  payload=$(printf '{"vectors":{"size":%s,"distance":"%s"}}' "$dim" "$distance")

  http_code=$(curl -sS -o /tmp/qdrant-init-resp.json -w "%{http_code}" \
    -X PUT "$QDRANT_URL/collections/$name" \
    -H 'Content-Type: application/json' \
    -d "$payload")

  if [[ "$http_code" == "200" ]]; then
    echo "[init-qdrant] ✓ created $name (dim=$dim $distance)"
  elif grep -q "already exists" /tmp/qdrant-init-resp.json 2>/dev/null; then
    echo "[init-qdrant] = exists $name (dim=$dim $distance)"
  else
    echo "[init-qdrant] ✗ FAILED $name (http=$http_code)" >&2
    cat /tmp/qdrant-init-resp.json >&2
    echo >&2
    exit 1
  fi
done

echo "[init-qdrant] done"

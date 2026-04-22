#!/usr/bin/env bash
# reset_db.sh — 完全清空所有数据库（保留表结构和 query_history 日志）
# 执行: bash scripts/reset_db.sh
set -euo pipefail

echo "=== RAG 数据库重置 ==="
echo "警告：将清空 PostgreSQL 文档数据、Qdrant、Redis，保留 query_history"
echo ""

# ── PostgreSQL ──────────────────────────────────────────────────────────────
echo "▶ PostgreSQL: 清空文档数据..."
docker exec postgres-rag psql -U rag_user -d rag_db -c "
TRUNCATE TABLE ocr_quarantine RESTART IDENTITY CASCADE;
TRUNCATE TABLE ocr_tasks RESTART IDENTITY CASCADE;
TRUNCATE TABLE chart_series RESTART IDENTITY CASCADE;
TRUNCATE TABLE fee_rates RESTART IDENTITY CASCADE;
TRUNCATE TABLE division_codes RESTART IDENTITY CASCADE;
TRUNCATE TABLE quota_materials RESTART IDENTITY CASCADE;
TRUNCATE TABLE quota_items RESTART IDENTITY CASCADE;
TRUNCATE TABLE price_records RESTART IDENTITY CASCADE;
TRUNCATE TABLE text_chunks RESTART IDENTITY CASCADE;
TRUNCATE TABLE documents RESTART IDENTITY CASCADE;
SELECT 'PostgreSQL: 清空完成，保留 query_history' as status;
" 2>&1

# ── Qdrant ──────────────────────────────────────────────────────────────────
echo ""
echo "▶ Qdrant: 重建 documents collection..."
# 删除旧集合
curl -sf -X DELETE "http://localhost:6333/collections/documents" > /dev/null 2>&1 && echo "  已删除旧 documents 集合" || echo "  documents 集合不存在，跳过"

# 重建 documents 集合 (1024-dim, COSINE)
curl -sf -X PUT "http://localhost:6333/collections/documents" \
  -H "Content-Type: application/json" \
  -d '{
    "vectors": {
      "size": 1024,
      "distance": "Cosine",
      "on_disk": false
    },
    "hnsw_config": {
      "m": 16,
      "ef_construct": 200
    }
  }' | python3 -m json.tool 2>/dev/null | grep -E '"status"|"result"' || echo "  Qdrant 集合创建完成"

# 删除/重建 sessions 集合
curl -sf -X DELETE "http://localhost:6333/collections/sessions" > /dev/null 2>&1 || true
curl -sf -X PUT "http://localhost:6333/collections/sessions" \
  -H "Content-Type: application/json" \
  -d '{
    "vectors": {
      "size": 1024,
      "distance": "Cosine"
    }
  }' > /dev/null 2>&1 && echo "  sessions 集合已重建" || true

echo "  Qdrant 重置完成"

# ── Redis ───────────────────────────────────────────────────────────────────
echo ""
echo "▶ Redis: 清空缓存..."
if docker exec rag-redis redis-cli FLUSHDB > /dev/null 2>&1; then
  echo "  Redis FLUSHDB 完成"
else
  echo "  Redis 未运行，跳过"
fi

# ── 验证 ────────────────────────────────────────────────────────────────────
echo ""
echo "=== 验证 ==="
echo -n "PostgreSQL text_chunks 行数: "
docker exec postgres-rag psql -U rag_user -d rag_dashboard -t -c "SELECT count(*) FROM text_chunks;" 2>/dev/null | tr -d ' \n'
echo ""

echo -n "Qdrant documents vectors: "
curl -sf "http://localhost:6333/collections/documents" 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('result', {}).get('vectors_count', 0))
" 2>/dev/null || echo "0"

echo ""
echo "✅ 数据库重置完成"

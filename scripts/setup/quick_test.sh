#!/bin/bash
echo "=== RAG Dashboard 快速测试 ==="
echo ""
echo "1. 健康检查"
curl -s http://localhost:8000/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"  状态: {d['status']}\"); [print(f\"    {'✅' if v=='healthy' else '❌'} {k}: {v}\") for k,v in d['services'].items()]"
echo ""
echo "2. 搜索测试"
curl -s -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"测试","top_k":3}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"  状态: {d['status']}\"); print(f\"  结果数: {len(d['data']['results'])}\")"
echo ""
echo "3. OCR 服务"
curl -s http://localhost:8001/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"  状态: {d['status']}\"); print(f\"  Paddle: {d.get('paddle_available')}\")"
echo ""
echo "=== 测试完成 ==="

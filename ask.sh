#!/bin/bash
QUERY="${1:-测试}"
echo "🧠 提问: $QUERY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
curl -s -X POST http://localhost:8080/api/v1/agent \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"$QUERY\", \"max_iterations\": 3}" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
print('💬 回答:\n')
print(data.get('answer', '无回答'))
print('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
print(f'📊 置信度: {data.get(\"evaluation\", {}).get(\"confidence\", 0):.2f}')
print(f'🔄 迭代: {data.get(\"iterations\", 1)} 轮')
print(f'📎 引用: {len(data.get(\"chunks\", []))} 篇')
print(f'🆔 session: {data.get(\"session_id\", \"\")[:8]}...')
"

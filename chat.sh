#!/bin/bash
# RAG 交互聊天 — 输入一行回车即得回答
URL="http://localhost:8080/api/v1/agent"
if [ ! -t 0 ]; then
  # 管道/重定向模式：读一行就退出
  read -r q
  [ -z "$q" ] && exit 0
  curl -s -X POST "$URL" -H "Content-Type: application/json" \
    -d "{\"query\":\"$q\",\"max_iterations\":3}" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('answer','❌ 错误'))"
  exit 0
fi
# 交互模式：循环聊天
echo "🧠 RAG Chat (Ctrl+D 或 exit 退出)"
while IFS= read -rp "> " q; do
  [[ "$q" == "exit" ]] && break
  [[ -z "$q" ]] && continue
  curl -s -X POST "$URL" -H "Content-Type: application/json" \
    -d "{\"query\":\"$q\",\"max_iterations\":3}" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('answer','❌ 错误'));print('—'*40)"
done

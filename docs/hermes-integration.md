# RAG26 × Hermes 集成方案

## 架构决策

```
Vite 前端 (React)     ← 呈现代理 — 图表、卡片、格式化回答
       │
RAG26 API (:8002)     ← 能力层
  ├── /api/v1/agent   ← 完整推理链 + presentation_payloads
  ├── /api/v1/tools/* ← 41 个 tool 独立 API
  ├── /api/v1/search  ← 混合检索
  └── /api/v1/rag     ← 检索+生成
       │
       ├─────────────────────┬──────────────────────┐
       │                     │                      │
  rag CLI                  MCP (可选)           Hermes gateway
  (运维/批处理)             (对话工具)            (多平台接入)
```

## 三层调用方式

### 1. Vite 前端 → 直接 HTTP

用户在前端聊天，调用 `/api/v1/agent`，获得结构化呈现（计算链、图表、引用卡片）。

### 2. Hermes CLI → rag tool

```bash
# 运维巡检
rag health && rag stats

# 批量查询
for m in "C30混凝土" "HRB400钢筋"; do
  rag tool price_query -k "{\"material_name\":\"$m\",\"year_month\":\"202512\"}" --json
done

# Cron 定时
# 每天 9:00 健康巡检
# 每天 18:00 知识库统计
```

### 3. Hermes MCP → Tool API

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  rag26:
    command: "python3"
    args: ["/home/l/rag26-cost-ai/mcp/rag_mcp_server.py"]
    env:
      RAG_URL: "http://localhost:8002"
    timeout: 180
```

Hermes 自动获得: `mcp_rag26_agent_query`, `mcp_rag26_price_query`, `mcp_rag26_search`, `mcp_rag26_calculator`, `mcp_rag26_python_eval`, `mcp_rag26_system_info` 等工具。

## Tool API 设计

```
POST /api/v1/tools/{name}
{"kwargs": {"param1": "value1", ...}}

GET  /api/v1/tools/list        → 列出 41 个 tool 及签名
GET  /api/v1/tools/{name}/schema → 单个 tool 的 JSON Schema
```

所有 tool 返回 `{"tool": "name", "result": ...}`。

## 部署

```bash
# 1. 重启 retrieval-service 加载新 tool API
cd /home/l/rag26-cost-ai
docker compose restart retrieval-service

# 2. 验证 tool API
curl http://localhost:8002/api/v1/tools/list | python3 -m json.tool | head

# 3. Hermes MCP（可选）
hermes mcp add rag26 --command python3 \
  --args /home/l/rag26-cost-ai/mcp/rag_mcp_server.py \
  --env RAG_URL=http://localhost:8002

# 4. Hermes skill
# cost-intel skill 已安装到 ~/.hermes/skills/mlops/cost-intel/
# 使用: hermes -s cost-intel

# 5. Cron 巡检
hermes cron create "0 9 * * *" \
  --name "RAG26 健康巡检" \
  --skills cost-intel \
  --prompt "运行 rag health && rag stats，报告异常"
```

## 隔离保证

```
Hermes → rag CLI (子进程) → HTTP → RAG26 API → PG/Qdrant
                                    Hermes 不持有 DB 密码
```

Hermes 通过 `hermes config set` 存 MCP 配置，通过 `.env` 存 API URL。生产 DB 密码只在 RAG26 的 docker-compose 环境变量中。

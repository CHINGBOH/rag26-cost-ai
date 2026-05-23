# RAG26 工具化 / API 化 / CLI 化 架构设计

## 现状问题

RAG26 的 39 个 @tool 是 LangChain 内部函数，只在 agent graph 的 executor_node
里被 LLM 通过 tool_choice 机制调用。对外暴露的 76 个 REST API 端点是另一套粒度：
- `/api/v1/agent` → 跑完整 graph（黑盒）
- `/api/v1/search` → 混合检索（粗粒度）
- `/api/v1/learning/*` → 学习系统（内部管理）

**没有直接调用 `price_query`、`vector_search`、`hybrid_search` 等工具的外部接口。**

## 整改目标

1. 39 个 @tool → 独立的可调用能力单元
2. CLI 可以单独调用任意 tool
3. API 可以单独调用任意 tool
4. Hermes 可以通过 CLI/API/MCP 任意方式接入
5. Agent graph 继续作为"智能编排层"存在，但退居为高级能力

## 三层架构

```
┌──────────────────────────────────────────────────────────────┐
│                     调用层                                    │
│  Hermes Agent  │  CLI (rag)  │  MCP Client  │  Web Frontend  │
└────────┬──────────────┬──────────┬──────────────┬────────────┘
         │              │          │              │
    ┌────▼────┐   ┌─────▼──────┐   │         ┌────▼─────────┐
    │  MCP    │   │  CLI HTTP  │   │         │  React 前端   │
    │ Server  │   │  Client    │   │         │  (现有)       │
    └────┬────┘   └─────┬──────┘   │         └────┬─────────┘
         │              │          │              │
         └──────────────┼──────────┘              │
                        │                         │
┌───────────────────────▼─────────────────────────▼───────────┐
│                   API 层 (FastAPI :8002)                     │
│                                                              │
│  /api/v1/tools/<tool_name>     ← 新增：逐 tool 调用          │
│  /api/v1/tools/list            ← 新增：列出所有可用 tool     │
│  /api/v1/agent                  ← 现有：完整 graph            │
│  /api/v1/search                 ← 现有：混合检索              │
│  /api/v1/rag                    ← 现有：检索+生成             │
│  /api/v1/sandbox/execute        ← 现有：代码执行              │
│  ... (其余 70 个端点保持不变)                                │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                   工具层 (tools.py 不变)                      │
│                                                              │
│  Round 1 (14): concept_search, price_query, price_trend,     │
│    rule_clause_search, text_search, hybrid_search,           │
│    pdf_page_search, vector_search, keyword_search,           │
│    category_search, get_catalog_map, calculator, python_eval │
│  Round 2 (8):  list_tables ... stats_overview                │
│  Round 3 (7):  concept_neighbors ... find_knowledge_gaps     │
│  Round 4 (4):  forecast_series ... cluster_records           │
│  Round 6 (7):  regex_extract ... proactive_explore           │
│                                                              │
│  共计 41 个 @tool，每个有签名 + docstring + JSON 返回值       │
└──────────────────────────────────────────────────────────────┘
```

## Tool 分类与 API 路由设计

### 第一类：检索工具 (14) — 只读，幂等，无副作用

| Tool | API 路由 | 描述 |
|------|---------|------|
| concept_search | /api/v1/tools/concept_search | 概念命中+证据下钻 |
| vector_search | /api/v1/tools/vector_search | pgvector 语义检索 |
| keyword_search | /api/v1/tools/keyword_search | PostgreSQL FTS |
| category_search | /api/v1/tools/category_search | 目录索引检索 |
| graph_search | /api/v1/tools/graph_search | 知识图谱检索 |
| topology_search | /api/v1/tools/topology_search | 拓扑遍历 |
| hybrid_search | /api/v1/tools/hybrid_search | 混合召回 RRF |
| text_search | /api/v1/tools/text_search | 语义+全文混合 |
| pdf_page_search | /api/v1/tools/pdf_page_search | PDF 页级证据 |
| rule_clause_search | /api/v1/tools/rule_clause_search | 条文二跳检索 |
| price_query | /api/v1/tools/price_query | 材料价格查询 |
| price_trend | /api/v1/tools/price_trend | 价格走势 |
| get_catalog_map | /api/v1/tools/get_catalog_map | 章节目录 |
| proactive_explore | /api/v1/tools/proactive_explore | 主动穿透 |

### 第二类：数据库工具 (8) — 只读

| Tool | API 路由 |
|------|---------|
| list_tables | /api/v1/tools/list_tables |
| describe_table | /api/v1/tools/describe_table |
| sql_query | /api/v1/tools/sql_query |
| aggregate_query | /api/v1/tools/aggregate_query |
| list_documents | /api/v1/tools/list_documents |
| fetch_chunk | /api/v1/tools/fetch_chunk |
| similar_chunks | /api/v1/tools/similar_chunks |
| stats_overview | /api/v1/tools/stats_overview |

### 第三类：图谱工具 (7) — 只读

| Tool | API 路由 |
|------|---------|
| concept_neighbors | /api/v1/tools/concept_neighbors |
| concept_path | /api/v1/tools/concept_path |
| entity_cooccur | /api/v1/tools/entity_cooccur |
| upstream_downstream | /api/v1/tools/upstream_downstream |
| expand_question | /api/v1/tools/expand_question |
| suggest_followup | /api/v1/tools/suggest_followup |
| find_knowledge_gaps | /api/v1/tools/find_knowledge_gaps |

### 第四类：计算/数据科学 (11) — 只读，沙箱隔离

| Tool | API 路由 |
|------|---------|
| calculator | /api/v1/tools/calculator |
| python_eval | /api/v1/tools/python_eval |
| forecast_series | /api/v1/tools/forecast_series |
| outlier_detect | /api/v1/tools/outlier_detect |
| correlate | /api/v1/tools/correlate |
| cluster_records | /api/v1/tools/cluster_records |
| regex_extract | /api/v1/tools/regex_extract |
| unit_convert | /api/v1/tools/unit_convert |
| date_math | /api/v1/tools/date_math |
| compare_values | /api/v1/tools/compare_values |
| number_stats | /api/v1/tools/number_stats |

### 第五类：可视化 (1)

| Tool | API 路由 |
|------|---------|
| chart_spec | /api/v1/tools/chart_spec |

### 元端点

| 端点 | 描述 |
|------|------|
| GET /api/v1/tools/list | 列出所有可用 tool 的名称+签名+描述 |
| GET /api/v1/tools/{name}/schema | 单个 tool 的 JSON Schema |

## CLI 改造

```
rag tool vector_search "C30混凝土 价格" -k 8
rag tool price_query --material "C30商品混凝土" --month 202512
rag tool hybrid_search "楼梯面层 玻璃地板 人工费" -k 10
rag tool sql_query "SELECT count(*) FROM price_records WHERE year_month='202512'"
rag tool stats_overview
rag tool calculator "(100+50*0.1)*0.2044"
rag tool list                          # 列出所有 tool

rag search "关键词"                     # 现有：快捷混合检索
rag agent "复杂问题"                    # 现有：跑完整 graph
rag chat                               # 现有：交互式
```

## Hermes 接入方案分析

### 方案 A：MCP（推荐）

```
Hermes → MCP Server (fastmcp) → HTTP → /api/v1/tools/<name>
```

优点：
- 工具自动发现（MCP list_tools → 读取 /api/v1/tools/list）
- Hermes 原生集成，无需额外配置
- 工具隔离：Hermes 只看到 MCP tool，不碰 DB

缺点：
- 多一层 MCP 进程
- 工具数量多（41个），token 消耗大 → 需要 Tool Filtering

### 方案 B：Skill + CLI

```
Hermes → cost-intel skill (instructions) → terminal(rag tool ...)
```

优点：
- 零依赖，只靠 CLI
- Hermes 通过终端调用，完全隔离
- Skill 可以按需加载，渐进式披露

缺点：
- 每次调用走 terminal 工具，慢
- JSON 解析需要 skill 指导

### 方案 C：直接 API

```
Hermes → web_search/terminal + curl → /api/v1/tools/<name>
```

优点：最简单
缺点：没有工具发现机制

### 推荐组合：MCP + Skill

```
Hermes 启动时:
  MCP Server → 自动发现 41 个 RAG26 tool → 注册为 mcp_rag26_*

Hermes 使用时:
  cost-intel skill 加载 → 指导何时用哪个 tool
  agent_query(complex) → 走完整 graph
  mcp_rag26_price_query(simple) → 直接调 tool
```

Skill 负责：查询词优化、工具选择策略、计算工作流
MCP 负责：工具注册、参数校验、结果返回
Agent graph 负责：多步推理、复杂编排

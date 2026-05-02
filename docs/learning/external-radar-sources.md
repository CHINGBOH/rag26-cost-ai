# 外部技术雷达 — 信号源目录

> #94 Phase B 产物。**外部信号入口（I5）** 必须常开，至少一个端口持续接收。

---

## 候选源评估

| 源 | 信号密度 | 噪音比 | 抓取难度 | 频率 | 状态 |
|----|----------|--------|----------|------|------|
| arxiv.org `cs.IR` + `cs.CL` | 高 | 中（关键词过滤后低） | 低（RSS） | 每日 | ✅ 推荐 P0 |
| HuggingFace trending models | 中 | 低 | 低（HTTP API） | 每日 | ✅ 推荐 P0 |
| GitHub releases watch list | 高 | 低 | 低（GitHub API） | 每日 | ✅ 推荐 P0 |
| `langchain` / `langgraph` 仓库 issues 趋势 | 中 | 高 | 低 | 每周 | ⚠️ P1 |
| OWASP / NIST AI 风险公告 | 高 | 低 | 中（HTML） | 每周 | ⚠️ P1 |
| 国家发改委 / 行业造价新规 | 极高（业务相关） | 极低 | 高（PDF） | 每月 | ⚠️ P2 — 业务团队订阅 |
| Twitter/X 关键 KOL | 中 | 极高 | 中（API 受限） | 实时 | ❌ 不做 |
| 自项目 issue/PR 流 | 中 | 低 | 低 | 实时 | ✅ 已通过 GH MCP 闭环 |

---

## P0 三源具体抓取规则

### Source 1 — arxiv RAG/Retrieval daily

- URL 模板：`https://export.arxiv.org/rss/cs.IR` + `cs.CL`
- 过滤关键词（标题或摘要含其一即入选）：
  ```
  RAG, retrieval-augmented, agentic retrieval, query rewriting,
  reranking, embedding, dense retrieval, hybrid search,
  knowledge graph QA, GraphRAG, contract verification, self-RAG
  ```
- 落库字段：`title, abstract, authors, link, published_at, source='arxiv', tags`
- 评分：标题命中关键词 +2，摘要命中 +1，>= 2 进推荐区

### Source 2 — HuggingFace trending

- URL：`https://huggingface.co/api/models?sort=trending&filter=feature-extraction`
- 过滤：`pipeline_tag in {feature-extraction, sentence-similarity, text-classification}`
- 关注点：embedding 模型新版（bge / m3 / mxbai / nomic / jina）
- 落库字段：`model_id, downloads, likes, last_modified, library_name, tags`
- 评分：last_modified 7 天内 + downloads > 1000 触发推送

### Source 3 — GitHub releases watch

- 监控仓库白名单：
  ```
  langchain-ai/langchain
  langchain-ai/langgraph
  qdrant/qdrant
  milvus-io/milvus
  pgvector/pgvector
  elastic/elasticsearch
  huggingface/transformers
  huggingface/text-embeddings-inference
  deepset-ai/haystack
  run-llama/llama_index
  ```
- API：`GET /repos/{owner}/{repo}/releases/latest`
- 落库字段：`repo, tag_name, name, published_at, body, source='github_release'`
- 评分：major/minor 升级 → 推到 architect inbox；patch 仅记录

---

## 数据库

```sql
CREATE TABLE tech_radar (
  id          BIGSERIAL PRIMARY KEY,
  source      TEXT NOT NULL,        -- arxiv | hf_trending | github_release | manual
  external_id TEXT,                 -- arxiv id / model_id / release tag
  title       TEXT NOT NULL,
  summary     TEXT,
  url         TEXT,
  published_at TIMESTAMPTZ,
  fetched_at  TIMESTAMPTZ DEFAULT NOW(),
  score       INT DEFAULT 0,
  tags        TEXT[],
  status      TEXT DEFAULT 'new',   -- new | reviewing | adopted | dismissed
  reviewer    TEXT,                 -- 人工评审填
  decision_note TEXT,
  related_issue INT,                -- 采纳后关联的 issue 号
  UNIQUE (source, external_id)
);
CREATE INDEX idx_tech_radar_fetched ON tech_radar(fetched_at DESC);
CREATE INDEX idx_tech_radar_status  ON tech_radar(status);
CREATE INDEX idx_tech_radar_source  ON tech_radar(source);
```

---

## 采集器骨架

`scripts/tech_radar/` 下每个源一个文件：

- `fetch_arxiv.py` — RSS 抓取 + 关键词过滤 + 上数据库（idempotent on UNIQUE 约束）
- `fetch_hf_trending.py` — HF API + 评分
- `fetch_github_releases.py` — GitHub releases API + 仓库白名单
- `radar_runner.py` — 调度入口（cron 每日 04:00 跑）

每个采集器必须：
1. 输出结构化日志（`actor=tech_radar src=arxiv inserted=12 dup=87`）
2. 失败不影响其他源（独立 try/except）
3. 完成后写一行 `signal_health` 记录：`source, fetched_at, inserted, errors`

---

## 闭环：人工评审 → 架构改动

```
tech_radar.status='new'
    ↓ (架构师在 /learning/radar 看板浏览)
status='reviewing'
    ↓ (decision: adopt | dismiss)
adopted → 自动开 GitHub issue + 关联 milestone（用 GH MCP）
       → status='adopted', related_issue=#NNN
dismissed → status='dismissed', decision_note=理由
```

**不变量约束**：每条 `adopted` 雷达条目 → 必须在 14 天内有对应 PR/commit，否则 architect inbox 高亮。这是 I5 的"最近 7 天非空"之外的二级保证。

---

## 下一步

1. SQL migration 建表
2. 实现 `fetch_arxiv.py` 一个源（最易，做 PoC）
3. 设 cron / GitHub Action 每日 04:00 跑
4. 前端 `/learning/radar` 区接 `GET /api/v1/learning/radar?status=new`
5. 评审操作走 `POST /api/v1/learning/radar/{id}/decision`

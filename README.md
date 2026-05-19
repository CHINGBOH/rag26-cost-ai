# Commercial Agent — 私有化优先的工程商务 Agent

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5.x-3178C6?logo=typescript&logoColor=white)
![Go](https://img.shields.io/badge/Go-1.21+-00ADD8?logo=go&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-green)
![Milvus](https://img.shields.io/badge/Milvus-2.4+-00A1EA?logo=milvus&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow)

**从工程造价 RAG，升级为面向商务员 / 投标专员 / 商务经理的工程商务 Agent 底座。**  
当前第一可落地模块：**投标废标风险审查**。

[工程商务蓝图](docs/commercial-agent-blueprint.md) · [投标风险审查模块](docs/tender-risk-agent.md) · [架构设计](docs/architecture.md) · [快速开始](#-快速开始)

</div>

---

## 为什么做它

工程商务工作不是单纯“查资料”，而是一条高价值、高责任、文档密集的业务链：

```text
商机判断 → 读标书 → 报价接单 → 防废标 → 签合同 → 向执行移交
```

其中最适合作为第一刀切入的，是：

# 投标废标风险审查

因为它同时满足：

- 文档极密集
- 条款容错率极低
- 一处小错可直接废标
- 客户能立刻判断系统有没有价值
- 现有 OCR / RAG / Agent 底座可直接复用

典型高危问题：

- 董事长 / 法定代表人要求**签字**，却误做成**盖章**
- 授权委托书主体或格式错误
- 附件、资质、社保、业绩、财报、承诺函遗漏
- 投标保证金到账时间理解错误
- 正副本份数、密封、装订、电子签章、逐页签章不合规

---

## 产品定位

### 顶层定位

> **私有化优先的工程商务 Agent**

服务对象：

- 商务员 / 商务经理
- 投标专员
- 报价与接单负责人
- 合同签订前的业务把关人

### 当前主线

> **投标废标风险审查 Agent**

### 后续扩展

- 商机判断 Agent
- 报价与投标协同 Agent
- 合同关键条款审查 Agent
- 商务向执行移交 Agent

详细路线见：[docs/commercial-agent-blueprint.md](docs/commercial-agent-blueprint.md)

---

## 私有化优先原则

投标文件和商务资料属于企业核心敏感文档。本项目默认遵循：

1. 文档默认不出客户内网
2. OCR、向量库、审查结果可本地化
3. LLM Provider 可替换：本地开源模型、客户自有模型服务、企业级 API
4. 每条高危风险都应给原文证据，不做无出处判断
5. 系统提供“风险预审”，不替代最终人工签署责任

---

## 当前已落地：投标风险规则预扫 API

### 1. 查看规则库

```http
GET /api/v1/commercial/tender/rule-catalog
```

### 2. 对已解析文本做风险预扫

```http
POST /api/v1/commercial/tender/review-preview
```

请求示例：

```json
{
  "document_name": "某项目招标文件.txt",
  "max_hits_per_rule": 4,
  "text": "投标文件须由法定代表人签字并加盖公章，否则作无效投标处理。"
}
```

输出重点字段：

- `critical_count`
- `high_count`
- `risks[].category`
- `risks[].title`
- `risks[].evidence.excerpt`
- `risks[].recommended_action`

第一版规则库已覆盖：

- 否决投标 / 无效投标
- 签字与盖章
- 资格条件
- 必交附件
- 时间节点
- 保证金 / 保函
- 份数 / 密封 / 装订 / 电子签章

模块说明见：[docs/tender-risk-agent.md](docs/tender-risk-agent.md)

---

## 保留并复用的底层能力

本仓库原本的建设工程造价 RAG 能力并未废弃，而是被保留为工程商务 Agent 的底座与后续能力模块。

### 已有能力

- PDF / 扫描件 OCR 流水线
- 混合召回：向量 + 全文 + 结构化表
- Rerank 精排
- LangGraph RAG pipeline
- LangGraph ReAct Agent
- 结构化工具调用
- PostgreSQL + pgvector / Milvus 可切换
- Redis / Qdrant / Docker 化服务

---

## 核心架构

```text
前端 / 工作台
  ↓
Go 网关层
  ↓
TypeScript 编排服务  +  Python 检索服务
  ↓
OCR / RAG / Agent / 商务风险规则库
  ↓
PostgreSQL + pgvector / Milvus / Redis / Qdrant
```

### 投标风险审查目标工作流

```text
上传招标文件
  ↓
OCR / 文档解析
  ↓
章节切分与索引
  ↓
规则引擎先扫硬风险
  ↓
RAG 检索相关章节
  ↓
LLM 进行专项审查：签章、资格、附件、时间、格式
  ↓
合并去重 / 排序
  ↓
导出审查报告
```

---

## 项目结构

```text
RAG26/
├── src/backend/retrieval-service/
│   ├── app/
│   │   ├── tender_review.py              # 新增：工程商务 / 投标风险规则预扫 API
│   │   ├── api.py                        # 原 RAG / Agent API
│   │   ├── agent/                        # LangGraph Agent
│   │   └── rag_pipeline.py
│   ├── infrastructure/
│   └── tests/
├── docs/
│   ├── commercial-agent-blueprint.md    # 新增：工程商务 Agent 顶层蓝图
│   ├── tender-risk-agent.md             # 新增：投标风险审查模块说明
│   └── architecture.md
├── ocr_tools/
├── ocr_web_service/
├── config/
├── infrastructure/
└── docker-compose.yml
```

---

## 快速开始

### 前置要求

- Docker 20.10+ / Docker Compose
- Python 3.10+
- Node.js 18+
- Go 1.21+（网关服务可选）
- NVIDIA GPU + CUDA 12.x（OCR 加速可选）

### 1. 启动基础设施

```bash
cd infrastructure
docker compose up -d
```

### 2. 启动检索服务

```bash
cd src/backend/retrieval-service
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8002 --reload
```

### 3. 验证投标风险预扫接口

```bash
curl -X POST http://localhost:8002/api/v1/commercial/tender/review-preview \
  -H "Content-Type: application/json" \
  -d '{
    "document_name": "demo.txt",
    "max_hits_per_rule": 3,
    "text": "投标文件须由法定代表人签字并加盖公章，否则作无效投标处理。投标保证金须在递交截止时间前到账。"
  }'
```

---

## 已有 RAG / Agent 接口

保留原有能力：

- `POST /api/v1/search`
- `POST /api/v1/rag`
- `POST /api/v1/agent`
- `POST /api/v1/agent/stream`
- `POST /api/v1/rerank`
- `POST /api/v1/evaluate`

这些接口可继续作为后续商务 Agent 的通用检索、问答和多步执行底座。

---

## 路线图

### V1 — 当前

- 顶层定位升级为工程商务 Agent
- 投标风险规则库骨架
- 风险预扫 API
- 文档化产品边界与私有化原则

### V2

- 文档上传后自动触发审查
- 与现有 OCR / RAG / Agent 链路打通
- 生成完整风险 JSON 审查报告

### V3

- 前端商务工作台
- 风险卡片与核对清单
- Word / PDF 导出
- 本地模型 Provider 配置

### V4

- 企业私有化部署包
- 项目权限隔离
- 审计日志
- 历史项目库与废标案例库

### V5

- 商机判断
- 报价协同
- 合同审查
- 商务向执行移交

---

## 技术栈

| 层 | 技术 |
|---|---|
| RAG 编排 | LangGraph |
| 向量检索 | Milvus / pgvector |
| 全文检索 | PostgreSQL |
| Session 缓存 | Qdrant |
| 缓存 | Redis |
| OCR | PaddleOCR |
| 后端 | Python / TypeScript / Go |
| 前端 | React + TypeScript |
| 部署 | Docker Compose |

---

## 许可证

MIT License

<div align="center">

# 🏗️ RAG26 Cost AI

**面向工程造价场景的多拓扑 RAG、OCR 识别与智能体协同工作台**  
*A multi-service RAG, OCR, and Agent orchestration platform for construction cost intelligence*

<p>
<img alt="Python" src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white">
<img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white">
<img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL%20%2B%20pgvector-316192?style=for-the-badge&logo=postgresql&logoColor=white">
<img alt="Qdrant" src="https://img.shields.io/badge/Qdrant-VectorDB-DC382D?style=for-the-badge">
<img alt="LangGraph" src="https://img.shields.io/badge/LangGraph-Agent%20Runtime-FF6F00?style=for-the-badge">
</p>

<p>
<img alt="status" src="https://img.shields.io/badge/status-active-success?style=flat-square">
<img alt="architecture" src="https://img.shields.io/badge/architecture-polyglot--rag-blue?style=flat-square">
<img alt="license" src="https://img.shields.io/badge/license-MIT-green?style=flat-square">
</p>

</div>

---

## 📖 简介 · About

**RAG26 Cost AI** 是专门针对**工程造价、工程量清单核算与建材指标库**研发的混合拓扑 RAG 智能系统。针对工程行业“长表格、非标扫描件、强专业术语、跨构件依赖”等痛点，系统深度结合 OCR 结构化解析、混合检索（BM25 + 向量密排 + 知识图谱关联）与多智能体动态协同，提供高置信度的工程造价推理与指标核算。

---

## 🏛️ 核心目录架构 · Repository Layout

```text
rag26-cost-ai/
├── src/                  # 🚀 核心后端检索、排序与多智能体 Agent 编排服务
├── ocr_tools/            # 🔍 工程图纸与造价表格 OCR 结构化解析工具集
├── ocr_web_service/      # 🌐 OCR 高并发切片与识别微服务
├── packages/shared/      # 🔄 前后端与跨服务共享的数据契约模型
├── sql/                  # 🗄️ 核心数据库 Schema DDL 与 pgvector 索引定义
├── tests/                # 🧪 全链路回归测试与造价准确率评测集
├── docs/                 # 📚 系统架构设计、多拓扑路由设计与 API 文档
├── main.py               # ⚡ 顶级主入口 (一键拉起或引导核心服务)
├── requirements.txt      # 📦 统一环境依赖清单 (零脚手架噪音)
└── README.md             # 🌟 唯一项目门面
```

---

## 🚀 快速开始 · Quickstart

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 启动核心引擎
```bash
python main.py
```

### 3. 运行造价检索与准确率测试
```bash
pytest tests/
```

---

## 🧩 核心功能矩阵 · Feature Matrix

- **多拓扑混合检索**：支持稠密向量检索 (pgvector / Qdrant) 与 BM25 稀疏检索互补重排 (Rerank)；
- **工程级 OCR 切片解析**：针对造价清单、工程图纸表单进行网格级 OCR 重构与语义对齐；
- **知识图谱关联分析**：基于工程定额规范与主材分类构建实体关系图谱，精准识别非标主材与超额造价；
- **Agent 执行可观测性**：全链路记录 Agent 检索证据链与计算推导过程，杜绝模型幻觉。

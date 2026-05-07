# RAG 架构检测工具使用指南

## 📦 工具概览

| 工具 | 用途 | 优先级 |
|------|------|--------|
| **LangFuse** | 全链路追踪、可视化 | 🔴 P0 |
| **Ragas** | 语义质量审计 | 🟡 P1 |
| **Promptfoo** | Prompt/Retrieval A/B 测试 | 🟢 P2 |

---

## 🚀 快速开始

### 1. LangFuse 启动

```bash
cd infrastructure
docker-compose -f docker-compose.langfuse.yml up -d

# 访问: http://localhost:3001
```

#### TypeScript 集成说明

Node orchestrator 当前未接入活跃的 Langfuse SDK 调用链；如需恢复该能力，应重新按实际运行时路径接入，而不是依赖已删除的历史示例工具文件。

---

### 2. Ragas 评估

```bash
cd src/backend/python-legacy
pip install ragas
python ragas_eval.py
```

---

### 3. Promptfoo A/B 测试

```bash
npm install -g promptfoo
cd infrastructure
promptfoo eval
```

---

## 📊 架构检测清单

| 检测维度 | 工具 | 判定标准 |
|----------|------|----------|
| 检索质量 | Ragas | context_relevancy > 0.6 |
| 事实一致性 | Ragas | faithfulness > 0.7 |
| 回答相关性 | Ragas | answer_relevance > 0.7 |
| 链路追踪 | LangFuse | 每步耗时 < 2s |
| Prompt 效果 | Promptfoo | 通过率 > 80% |

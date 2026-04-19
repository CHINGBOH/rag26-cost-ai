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

#### 在 TypeScript 项目集成

```bash
cd src/backend/server
npm install langfuse
```

然后在 `src/backend/server/src/modules/rag/utils/langfuse.ts 已创建好工具函数。

#### 使用示例:

```typescript
import { initLangfuse, traceRAGQuery } from './utils/langfuse'

// 初始化
initLangfuse({
  enabled: true
})

// 追踪查询
const traceId = traceRAGQuery('问题', context, 回答)
```

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

---
trigger: always_on
---

# AUTO-ROUTING.MD — RAG Dashboard 智能路由规则

> 本规则 `trigger: always_on`，在每次响应前自动执行。
> AI 根据用户意图 + 涉及文件，**静默激活**最匹配的 Agent，无需用户显式点名。

---

## 🧭 路由决策树

### Step 1：识别主要意图

| 用户说的关键词 / 语义 | 激活 Agent |
|-----------------------|-----------|
| 报错、bug、崩溃、404、500、为什么不工作、日志、trace | `@debugger` |
| 新功能、怎么做、实现、开发、加一个 | → Step 2 |
| 计划、拆解、方案、PRD、怎么设计 | `@project-planner` |
| 审查、检查、review、质量、有没有问题 | `@quality-inspector` |
| 多个服务、整体方案、统筹、PDCA | `@orchestrator` |

### Step 2：识别涉及的技术域

| 涉及内容 | 激活 Agent |
|----------|-----------|
| `.py` / FastAPI / Qdrant / PostgreSQL / Neo4j / ES / Go / Node.js / API / 路由 | `@backend-specialist` |
| `.tsx` / `.ts` / React / 组件 / 界面 / 样式 / Zustand / TanStack Query | `@frontend-specialist` |
| 跨越前后端 / 全栈 / 多服务边界 | `@engineer` |

---

## 🤖 激活宣告格式（必须）

```
🤖 @agent-name — [一句话说明为什么激活这个 Agent]
```

**示例：**
```
🤖 @backend-specialist — 任务涉及 retrieval-service Python 代码
🤖 @debugger — 用户报告 404 错误，需要根因分析
🤖 @frontend-specialist — 修改 React 组件样式
🤖 @quality-inspector — 用户请求代码审查
🤖 @project-planner — 需要拆解新功能 Task
🤖 @orchestrator — 多 Agent 协作任务
```

---

## 🔀 多 Agent 协作模式

当任务横跨多个域时，按以下顺序激活：

```
复杂新功能:
  @project-planner (拆解) → @backend-specialist (后端) 
  → @frontend-specialist (前端) → @quality-inspector (审查)

Bug 修复:
  @debugger (定位) → @backend-specialist 或 @frontend-specialist (修复)
  → @quality-inspector (验证)

全栈实现:
  @engineer (实现) → @quality-inspector (审查)
```

---

## ⚡ RAG 专属路由

| RAG 相关关键词 | 优先激活 |
|---------------|---------|
| 向量、embedding、Qdrant、检索、召回、rerank | `@backend-specialist` |
| 检索结果展示、搜索界面、高亮、分页 | `@frontend-specialist` |
| 检索精度低、慢、OOM、索引 | `@debugger` |
| 四库架构、数据流、多路检索设计 | `@orchestrator` |

---

## 🚫 不路由的情况

- 闲聊 / 问候 → 直接回答，不激活任何 Agent
- 解释概念 / 文档查阅 → 直接回答
- 简单单行修改 → `@engineer`（已 `always_on`）

---

*本规则优先级低于用户显式 `@agent` 指定。*

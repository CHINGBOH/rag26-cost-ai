/**
 * 专业版 LangChain RAG 架构分析报告生成器
 * 目标读者：技术人员、架构师、开发者
 */

import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const REPORT_TITLE = 'LangChain RAG 架构全面分析报告';
const REPORT_SUBTITLE = '专业版';
const OUTPUT_FILE = path.join(__dirname, '../../LangChain-RAG-Report-Professional.md');

const reportContent = `
# ${REPORT_TITLE}
## ${REPORT_SUBTITLE}

> 生成时间: ${new Date().toLocaleString('zh-CN')}
> 版本: v1.0

---

## 一、执行摘要

本报告对 LangChain/LangGraph 的 RAG（检索增强生成）架构进行了全面的技术分析，旨在为现有的 XState 架构提供迁移和整合的技术路径。报告涵盖组件架构、RAG 模式、状态管理、持久化机制、Multi-Agent 设计以及 Memory 管理等核心主题。

### 1.1 关键发现

| 维度 | 发现 | 影响 |
|------|------|------|
| **状态管理** | LangGraph 采用基于 TypedDict 的强类型状态 + Channel 机制 | 与 XState Context 类似，可映射 |
| **持久化** | Checkpoint 机制支持线程级状态恢复 | 对应现有 Redis 持久化方案 |
| **RAG 模式** | 支持 2-Step、Agentic、Hybrid 三种架构 | 可根据场景选择合适模式 |
| **Multi-Agent** | 四种模式：Subagents/Handoffs/Skills/Router | 需根据并行性和延迟要求选择 |

---

## 二、LangChain 核心组件架构

### 2.1 组件生态系统

LangChain 的强大之处在于组件之间的有机协作：

\`\`\`
┌─────────────────────────────────────────────────────────────────────┐
│                        LangChain 组件架构                              │
├─────────────────────────────────────────────────────────────────────┤
│  📥 输入处理: Text input → Document loaders → Text splitters → Docs  │
│  🔢 嵌入存储: Documents → Embedding models → Vectors → Vector stores│
│  🔍 检索: User Query → Embedding → Query vector → Retrievers        │
│  🤖 生成: Chat models → Tools → Tool results → AI response         │
│  🎯 编排: Agents → Memory, Tools, Retrievers                        │
└─────────────────────────────────────────────────────────────────────┘
\`\`\`

### 2.2 组件分类

| 类别 | 用途 | 关键组件 | 典型场景 |
|------|------|----------|----------|
| **Models** | AI 推理和生成 | Chat models, LLMs, Embedding models | 文本生成、推理 |
| **Tools** | 外部能力扩展 | APIs, databases, web scrapers | 搜索、数据访问 |
| **Agents** | 编排和推理控制 | ReAct agents, tool calling agents | 非确定性工作流 |
| **Memory** | 上下文保持 | Message history, custom state | 多轮对话 |
| **Retrievers** | 信息检索 | Vector retrievers, web retrievers | RAG、知识库搜索 |
| **Document Loaders** | 数据摄取 | PDF, HTML, Markdown loaders | 数据导入 |
| **Vector Stores** | 语义索引 | Chroma, Pinecone, FAISS, Qdrant | 相似度搜索 |

---

## 三、RAG 架构模式深度分析

### 3.1 三种 RAG 架构对比

| 架构 | 描述 | 控制力 | 灵活性 | 延迟 | 适用场景 |
|------|------|--------|--------|------|----------|
| **2-Step RAG** | 顺序执行：检索→生成 | 高 | 低 | ⚡ 快 | FAQ、文档问答 |
| **Agentic RAG** | Agent 动态决定检索时机 | 低 | 高 | ⏳ 可变 | 复杂推理、研究助手 |
| **Hybrid** | 结合两者 + 验证层 | 中 | 中 | ⏳ 可变 | 领域 Q&A、质量敏感场景 |

### 3.2 2-Step RAG

\`\`\`
[用户问题] → [检索相关文档] → [生成回答] → [返回用户]
\`\`\`

**特点**：
- 检索始终先于生成执行
- 架构简单，行为可预测
- LLM 调用次数确定（通常 1-2 次）
- 适合检索作为明确前提的场景

**代码示意**：
\`\`\`python
def simple_rag(query: str, retriever, llm) -> str:
    docs = retriever.invoke(query)  # 检索
    context = "\\n\\n".join([doc.page_content for doc in docs])
    response = llm.invoke(f"Context: {context}\\n\\nQuestion: {query}")
    return response.content
\`\`\`

### 3.3 Agentic RAG

\`\`\`
[用户输入] 
    ↓
[Agent (LLM)]
    ↓
{需要外部信息?} ─┬─ Yes → [使用工具搜索]
                 │         ↓
                 │    {足够回答?}
                 │      ├─ No  → 回到 Agent 重新推理
                 │      └─ Yes → [生成最终回答]
                 └─ No  → [生成直接回答]
    ↓
[返回用户]
\`\`\`

**特点**：
- LLM 驱动的动态检索决策
- 支持多轮检索-推理循环
- 延迟不可预测但灵活性高
- 适合需要判断何时检索的场景

**实现要点**：
\`\`\`python
from langchain.tools import tool
from langchain.agents import create_agent

@tool
def retrieve_context(query: str):
    """检索相关信息"""
    docs = vectorstore.similarity_search(query, k=5)
    return "\\n\\n".join([f"Source: {doc.metadata}\\n{doc.page_content}" for doc in docs])

agent = create_agent(
    model="claude-sonnet-4",
    tools=[retrieve_context],
    system_prompt="你有检索工具可用，当需要事实信息时请使用。"
)
\`\`\`

### 3.4 Custom Workflow RAG (LangGraph)

LangGraph 允许组合三种节点类型：

| 节点类型 | 说明 | LLM 调用 | 典型用途 |
|----------|------|----------|----------|
| **Model Node** | LLM 推理 | ✅ | 查询重写、意图分类、答案生成 |
| **Deterministic Node** | 确定性逻辑 | ❌ | 向量检索、结果过滤 |
| **Agent Node** | 自主决策 | ✅ | 复杂推理、多工具协调 |

**完整示例**：
\`\`\`python
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

class RAGState(TypedDict):
    question: str
    rewritten_query: str
    documents: list[str]
    answer: str
    iterations: int

def rewrite_query(state: RAGState) -> dict:
    """Model Node: 重写查询"""
    response = llm.with_structured_output(RewrittenQuery).invoke([
        {"role": "system", "content": "重写以下查询使其更清晰..."},
        {"role": "user", "content": state["question"]}
    ])
    return {"rewritten_query": response.query}

def retrieve(state: RAGState) -> dict:
    """Deterministic Node: 执行检索"""
    docs = retriever.invoke(state["rewritten_query"])
    return {"documents": [doc.page_content for doc in docs]}

def grade_documents(state: RAGState) -> str:
    """Conditional Edge: 评估文档相关性"""
    docs_content = state["documents"][-1].content  # 假设最后一个消息是工具结果
    score = grade_model.invoke(f"Query: {state['question']}\\nDoc: {docs_content}")
    return "generate_answer" if score.binary_score == "yes" else "rewrite_query"

workflow = (
    StateGraph(RAGState)
    .add_node("rewrite", rewrite_query)
    .add_node("retrieve", retrieve)
    .add_node("generate_answer", generate_answer)
    .add_edge(START, "rewrite")
    .add_edge("rewrite", "retrieve")
    .add_conditional_edges("retrieve", grade_documents, {
        "generate_answer": "generate_answer",
        "rewrite_query": "rewrite"
    })
    .add_edge("generate_answer", END)
    .compile()
)
\`\`\`

---

## 四、LangGraph 核心机制

### 4.1 状态管理

LangGraph 使用 **TypedDict** 定义强类型状态：

\`\`\`python
from typing import TypedDict, Annotated
from operator import add

class State(TypedDict):
    question: str                        # 必填字段
    rewritten_query: str                 # 可选字段
    documents: Annotated[list, add]     # 带 Reducer 的列表（累加）
    answer: str | None                   # 联合类型
    iterations: int                      # 默认值需在节点中处理
\`\`\`

**关键概念**：

| 概念 | 说明 | 类比 |
|------|------|------|
| **Channel** | 状态值的容器 | XState 的 context key |
| **Reducer** | 合并多个更新的策略 | XState 的 actions |
| **Version** | 跟踪变化的向量时钟 | 乐观锁/版本号 |

### 4.2 Checkpoint 持久化机制

Checkpoint 是 LangGraph 状态持久化的核心：

\`\`\`python
class Checkpoint(TypedDict):
    v: int                              # 格式版本
    id: str                             # UUID，单调递增
    ts: str                             # ISO 8601 时间戳
    channel_values: dict[str, Any]      # 各 Channel 的值
    channel_versions: ChannelVersions   # 向量时钟
    versions_seen: dict[str, ChannelVersions]  # 各节点的视角
    updated_channels: list[str] | None  # 本步骤更新的 Channel
\`\`\`

**超步（Super-step）边界**：
- 一次超步 = 所有调度节点执行完成的完整 tick
- 每个超步边界创建 Checkpoint
- 可从任意 Checkpoint 恢复执行

### 4.3 线程（Thread）模型

\`\`\`python
# 必须指定 thread_id
config = {"configurable": {"thread_id": "user_session_123"}}

# 获取最新状态
current_state = graph.get_state(config)

# 获取历史状态
historical_state = graph.get_state({
    "configurable": {
        "thread_id": "user_session_123",
        "checkpoint_id": "1ef663ba-28fe-6528-8002-5a559208592c"
    }
})
\`\`\`

**与 XState 的映射**：

| LangGraph | XState | 说明 |
|-----------|--------|------|
| State | Context | 状态数据 |
| Node | Action/Service | 状态转换逻辑 |
| Edge | Transition | 状态流转 |
| Conditional Edge | Guard | 条件判断 |
| Checkpoint | 状态持久化 | Redis/Postgres 存储 |
| Subgraph | 嵌套 StateMachine | invoke 子状态机 |
| Thread | Session | 对话会话 |

---

## 五、Multi-Agent 模式

### 5.1 四种主要模式

| 模式 | 工作方式 | 分布式开发 | 并行化 | 多跳 | 直接交互 |
|------|----------|:----------:|:------:|:----:|:--------:|
| **Subagents** | 主 Agent 协调子 Agent | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐ |
| **Handoffs** | Tool 调用切换 Agent | - | - | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Skills** | 按需加载专业上下文 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Router** | 分类后路由到专门 Agent | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | - | ⭐⭐⭐ |

### 5.2 性能对比分析

#### 单次请求（买咖啡）

| 模式 | 模型调用次数 | 说明 |
|------|:------------:|------|
| Subagents | 4 | 主 Agent 协调开销 |
| Handoffs | 3 | ✅ 直接切换 |
| Skills | 3 | ✅ 上下文复用 |
| Router | 3 | ✅ 分类后执行 |

#### 重复请求

| 模式 | 第2次调用 | 总计 | 说明 |
|------|:--------:|:----:|------|
| Subagents | 4 | 8 | 无状态重复执行 |
| Handoffs | 2 | 5 | ✅ Agent 保持激活 |
| Skills | 2 | 5 | ✅ 上下文已加载 |
| Router | 3 | 6 | 需重新分类 |

#### 多领域（Python/JS/Rust 对比）

| 模式 | 调用次数 | Token 消耗 | 说明 |
|------|:--------:|:----------:|------|
| Subagents | 5 | ~9K | ✅ 并行子 Agent |
| Handoffs | 7+ | ~14K+ | 顺序执行开销大 |
| Skills | 3 | ~15K | 上下文累积 |
| Router | 5 | ~9K | ✅ 并行路由 |

### 5.3 模式选择决策树

\`\`\`
需要 Multi-Agent?
    │
    ├─ 需要并行执行? → Subagents / Router
    │                       │
    │                       ├─ 固定路由? → Router
    │                       └─ 动态决策? → Subagents
    │
    ├─ 需要状态保持? → Handoffs / Skills
    │                       │
    │                       ├─ 频繁切换? → Handoffs
    │                       └─ 上下文累积? → Skills
    │
    └─ 单 Agent 足够? → 使用单一 Agent + 动态 Tools
\`\`\`

---

## 六、Memory 管理

### 6.1 两种 Memory 类型

| 类型 | 作用域 | 实现方式 | 类比 |
|------|--------|----------|------|
| **Short-term** | 会话内 | State + Checkpointer | 工作记忆 |
| **Long-term** | 跨会话 | Store (namespaced KV) | 长期记忆 |

### 6.2 人类记忆类型映射

| 记忆类型 | 存储内容 | Agent 应用 | 实现方式 |
|----------|----------|------------|----------|
| **语义记忆** | 事实 | 用户 Profile、偏好 | Profile 或 Collection |
| **情景记忆** | 经历 | Few-shot examples | Few-shot prompt |
| **程序记忆** | 规则/技能 | Agent Prompt | 工具定义、System Prompt |

### 6.3 Memory 写入策略

| 策略 | 触发时机 | 优点 | 缺点 |
|------|----------|------|------|
| **Hot path** | 主流程中同步 | 实时、即时可用 | 增加延迟 |
| **Background** | 异步后台任务 | 不阻塞主流程 | 可能不同步 |

**建议**：对于 RAG Agent，使用 Hot path 写入关键记忆（如检索结果摘要），Background 写入次要信息（如用户偏好）。

---

## 七、与 XState 架构的整合策略

### 7.1 概念映射表

| LangGraph | XState | 数据结构示例 |
|-----------|--------|--------------|
| State | Context | \`{ question, documents, answer }\` |
| Node | Action/Service | \`retrieve(), generate()\` |
| Edge | Transition | \`{ target: 'generate' }\` |
| Conditional Edge | Guard | \`{ cond: (ctx) => ctx.documents.length > 0 }\` |
| Checkpoint | Persistence | Redis hash |
| Subgraph | invoke | \`invoke: 'subAgent'\` |
| Thread | Session ID | \`thread_id: 'user_123'\` |

### 7.2 RAG Agent 状态设计

\`\`\`python
from typing import TypedDict, Literal
from typing_extensions import Annotated

class RAGState(TypedDict):
    # 核心字段
    query: str
    intent: str | None
    rewritten_query: str | None

    # 检索相关
    retrieval_results: Annotated[list[dict], "append"]
    graded_docs: list[dict]
    fusion_score: list[tuple[str, float]]

    # 生成相关
    answer: str | None
    reasoning_chain: Annotated[list[str], "append"]

    # 元信息
    error: str | None
    iterations: int
    status: Literal["idle", "retrieving", "generating", "completed", "error"]
\`\`\`

### 7.3 状态流转设计

\`\`\`
┌─────────┐
│  idle   │ ──query──→ ┌──────────────────┐
└─────────┘            │ intent_classify │
                       └────────┬────────┘
                                │ intent
                       ┌────────▼────────┐
                       │  query_rewrite  │ (Model Node)
                       └────────┬────────┘
                                │ rewritten_query
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
    ┌─────▼─────┐         ┌─────▼─────┐         ┌─────▼─────┐
    │  vector   │         │  keyword  │         │   graph   │
    │  search   │         │   search  │         │   search  │
    └─────┬─────┘         └─────┬─────┘         └─────┬─────┘
          │                     │                     │
          └─────────────────────┼─────────────────────┘
                                │ merge + deduplicate
                       ┌────────▼────────┐
                       │  grade_docs    │ (LLM 评估)
                       └────────┬────────┘
                                │ pass/fail
              ┌─────────────────┼─────────────────┐
              │                 │                 │
        ┌─────▼─────┐     ┌─────▼─────┐     ┌─────▼─────┐
        │  < max?   │     │ generate  │     │ rewrite   │
        │ iters?    │     │  answer   │     │  query    │
        └─────┬─────┘     └─────┬─────┘     └───────────┘
              │                 │
              │ No              │ yes
        ┌─────▼─────┐     ┌─────▼─────┐
        │  completed│     │ continue  │
        └───────────┘     └───────────┘
\`\`\`

### 7.4 工具层整合

\`\`\`python
# 封装现有 four_db_tools.py 为 LangChain Tools

from langchain.tools import tool
from typing import Optional

class VectorSearchTool:
    name = "vector_search"
    description = "语义相似度检索，适合问概念、含义类问题"

    def __init__(self, qdrant_client=None):
        self.client = qdrant_client

    def execute(self, query: str, top_k: int = 10) -> ToolResult:
        results = self.client.search(
            collection_name="documents",
            query_vector=self.embed(query),
            limit=top_k
        )
        return ToolResult(
            success=True,
            content=self._format_results(results)
        )

# 类似的还有：
# - KeywordSearchTool (Elasticsearch)
# - GraphSearchTool (Neo4j)
# - StructuredQueryTool (结构化查询)
\`\`\`

---

## 八、错误处理与容错

### 8.1 错误分类

| 错误类型 | 示例 | 处理策略 |
|----------|------|----------|
| **检索超时** | Vector DB 无响应 | 降级到关键词检索 |
| **LLM 失败** | API 限流/网络错误 | 重试 + 降级回答 |
| **上下文超限** | 文档过多超出窗口 | 截断 + 优先级排序 |
| **工具执行失败** | 外部 API 错误 | 记录日志 + 跳过 |

### 8.2 建议的超时配置

| 操作 | 建议超时 | 重试次数 |
|------|----------|----------|
| 向量检索 | 30s | 2 |
| 关键词检索 | 15s | 2 |
| 图谱查询 | 30s | 1 |
| LLM 生成 | 60s | 2 |
| 文档重排 | 20s | 1 |

---

## 九、结论与建议

### 9.1 架构选择

| 场景 | 推荐架构 | 理由 |
|------|----------|------|
| 简单 FAQ | 2-Step RAG | 低延迟、可预测 |
| 复杂推理 | Agentic RAG | 动态检索、灵活 |
| 多源综合 | Custom Workflow + Router | 并行查询、综合 |
| 多轮对话 | Agentic RAG + Short-term Memory | 状态保持 |

### 9.2 实施路径

1. **Phase 1**: 封装现有四库工具为 LangChain Tools
2. **Phase 2**: 实现 2-Step RAG 作为基础
3. **Phase 3**: 添加 Agentic 路由和验证循环
4. **Phase 4**: 集成 Memory 管理
5. **Phase 5**: 性能优化和监控

### 9.3 关键技术决策

| 决策点 | 建议 | 备选 |
|--------|------|------|
| 状态管理 | XState 保持，新增 RAG Context 字段 | 迁移到 LangGraph |
| 持久化 | 复用现有 Redis | 迁移到 LangGraph Checkpointer |
| 工具调用 | 封装为 XState actions | 迁移到 LangChain Tools |
| LLM 调用 | 统一接口，支持多 provider | 直接使用 LangChain |

---

## 附录 A：参考代码结构

\`\`\`
src/
├── rag/
│   ├── __init__.py
│   ├── state.py              # RAG 状态定义
│   ├── nodes/
│   │   ├── __init__.py
│   │   ├── classify.py       # 意图分类
│   │   ├── rewrite.py        # 查询重写
│   │   ├── retrieve.py       # 检索执行
│   │   ├── grade.py          # 文档评估
│   │   └── generate.py       # 答案生成
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── vector.py          # 向量检索
│   │   ├── keyword.py        # 关键词检索
│   │   ├── graph.py          # 图谱检索
│   │   └── unified.py        # 统一工具
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── short_term.py     # 短时记忆
│   │   └── long_term.py      # 长时记忆
│   └── xstate/
│       ├── __init__.py
│       ├── machine.py        # XState 机器定义
│       └── adapter.py        # LangChain 适配器
\`\`\`

---

## 附录 B：术语表

| 术语 | 定义 |
|------|------|
| RAG | Retrieval-Augmented Generation，检索增强生成 |
| Agent | 能够自主决策并执行工具的 AI 系统 |
| Checkpoint | 状态快照，用于恢复和持久化 |
| Thread | 会话线程，对应一个对话上下文 |
| Superstep | LangGraph 中的执行单元，多个节点可并行 |
| Reducer | 状态合并策略 |
| Channel | 状态值的容器 |

---

*报告结束*

**文档版本**: v1.0  
**生成工具**: LangChain RAG Report Generator  
**最后更新**: ${new Date().toLocaleString('zh-CN')}
`;

fs.writeFileSync(OUTPUT_FILE, reportContent, 'utf-8');
console.log(`✅ 专业版报告已生成: ${OUTPUT_FILE}`);

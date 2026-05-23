# RAG Agent 架构完善方案

## 版本信息
- 版本: 1.0
- 日期: 2026-04-19
- 目标: 为RAG Agent实现铺路

---

## 一、现有架构分析

### 1.1 现有组件关系

```
┌─────────────────────────────────────────────────────────────────────┐
│                          现有架构                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐      ┌──────────────────┐      ┌──────────────┐ │
│  │ Recursion    │      │ ReactAgent        │      │ Cascade      │ │
│  │ StateMachine │ ←──→ │ (LangChain)      │ ←──→ │ Retrieval    │ │
│  │ (XState v5)  │      │                   │      │ Service      │ │
│  └──────────────┘      └──────────────────┘      └──────────────┘ │
│         ↑                      ↑                      ↑           │
│         │                      │                      │           │
│  ┌──────┴──────────────────────┴──────────────────────┴───────┐  │
│  │                    SessionPersistenceService                 │  │
│  │                    (Redis + File System)                    │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 现有状态机 (RecursionContext)

```typescript
// 当前状态定义
type RecursionState = 'idle' | 'decomposing' | 'dispatching' | 'retrieving' |
                      'ranking' | 'generating' | 'evaluating' | 'completed' | 'failed'
```

### 1.3 识别出的关键缺陷

| 缺陷 | 现状 | 影响 |
|-----|------|-----|
| **RAG状态机缺失** | 只有RecursionContext，没有RAG专用状态机 | 无法追踪RAG特有的检索/生成流程 |
| **Tool接口不完整** | `createFourDatabaseTools()`返回模拟数据 | 无法真正执行四库检索 |
| **Memory管理缺失** | 只有SessionPersistence，无Thread Memory | Agent无法记住推理过程 |
| **Event桥接缺失** | Tool执行结果无法触发状态转换 | 状态机与Agent执行脱节 |
| **RAG Context缺失** | 无query、retrievedDocs、response结构 | 状态无法追踪RAG完整上下文 |

---

## 二、目标架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                          目标架构                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    RAG StateMachine (XState v5)              │  │
│  │                                                              │  │
│  │   ┌─────────┐    ┌───────────┐    ┌────────────┐            │  │
│  │   │  idle   │──→→│ retrieving│──→→│ generating │──→complete │  │
│  │   └─────────┘    └───────────┘    └────────────┘            │  │
│  │        ↑                ↓                ↓                   │  │
│  │        │                ↓                ↓                   │  │
│  │        └────── error ◀─┴─────── error ◀─┘                   │  │
│  │                                                              │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                    ┌─────────┴─────────┐                            │
│                    │   Tool Bridge     │                            │
│                    │ (Event Channel)   │                            │
│                    └─────────┬─────────┘                            │
│                              │                                      │
│  ┌──────────────────────────┼──────────────────────────────────┐  │
│  │                          ▼                                   │  │
│  │   ┌─────────────────────────────────────────────────────┐    │  │
│  │   │              LangChain Tools (四库)                 │    │  │
│  │   │  ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐ │    │  │
│  │   │  │Vector   │ │ Keyword  │ │  Graph  │ │Calculator│ │    │  │
│  │   │  │Search   │ │ Search   │ │ Search  │ │          │ │    │  │
│  │   │  └────┬────┘ └────┬─────┘ └────┬────┘ └────┬─────┘ │    │  │
│  │   └───────┼──────────┼───────────┼───────────┼────────┘    │  │
│  └───────────┼──────────┼───────────┼───────────┼────────────┘  │
│              ▼          ▼           ▼           ▼               │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │              CascadeRetrievalService (四库检索)            │   │
│  └───────────────────────────────────────────────────────────┘   │
│                              │                                      │
│  ┌──────────────────────────┼──────────────────────────────────┐  │
│  │                          ▼                                   │  │
│  │   ┌─────────────────────────────────────────────────────┐    │  │
│  │   │              Memory Management                        │    │  │
│  │   │  ┌─────────────────┐  ┌─────────────────────────┐    │    │  │
│  │   │  │  Thread Memory  │  │   Session Memory        │    │    │  │
│  │   │  │  (短期对话记忆)  │  │   (长期知识存储)        │    │    │  │
│  │   │  └─────────────────┘  └─────────────────────────┘    │    │  │
│  │   └─────────────────────────────────────────────────────┘    │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 RAG状态机设计

```typescript
// RAG专用状态定义
type RAGState =
  | 'idle'                    // 初始状态，等待查询
  | 'query_understanding'     // 理解用户查询
  | 'planning'                // 规划检索策略
  | 'retrieving'              // 执行检索
  | 'retrieved'               // 检索完成，待处理
  | 'reasoning'               // AI推理/思考
  | 'generating'              // 生成回答
  | 'evaluating'              // 评估答案质量
  | 'completed'               // 完成
  | 'failed'                  // 失败
  | 'awaiting_human_review'   // 等待人工审核

// RAG上下文
interface RAGContext {
  // 查询信息
  query: string
  queryEmbedding?: number[]
  intent?: QueryIntent

  // 检索结果
  retrievedChunks: RetrievedChunk[]
  retrievalStrategy?: RetrievalStrategy

  // 生成结果
  response?: string
  citations?: Citation[]

  // 评估信息
  confidence?: number
  evaluation?: RoundEvaluation

  // 元数据
  sessionId: string
  threadId: string
  currentDepth: number
  iterations: number
  error?: Error
}
```

---

## 三、核心模块设计

### 3.1 Tool Bridge (工具桥接层)

```typescript
// 桥接LangChain Tool到XState Event
class ToolBridge {
  constructor(
    private machine: AnyInterpreter,
    private eventEmitter: EventEmitter
  ) {}

  // 将Tool结果转换为状态机事件
  async executeToolAndEmit(
    toolName: string,
    args: Record<string, any>
  ): Promise<ToolResult> {
    const tool = this.getTool(toolName)
    const result = await tool.invoke(args)

    // 发射Tool结果事件到状态机
    this.machine.emit({
      type: 'TOOL_COMPLETE',
      tool: toolName,
      result,
      timestamp: Date.now()
    })

    return result
  }

  // 获取当前状态机可用的工具列表
  getAvailableTools(): string[] {
    return this.machine.getSnapshot().context.availableTools
  }
}
```

### 3.2 Thread Memory (短期记忆)

```typescript
// 对话线程内的短期记忆
interface ThreadMemory {
  threadId: string
  messages: Message[]
  toolExecutions: ToolExecution[]
  reasoningSteps: ReasoningStep[]
  createdAt: number
  updatedAt: number
}

class ThreadMemoryService {
  private store: Map<string, ThreadMemory> = new Map()

  addMessage(threadId: string, message: Message): void {
    const memory = this.getOrCreate(threadId)
    memory.messages.push(message)
    memory.updatedAt = Date.now()
  }

  addToolExecution(threadId: string, execution: ToolExecution): void {
    const memory = this.getOrCreate(threadId)
    memory.toolExecutions.push(execution)
    memory.updatedAt = Date.now()
  }

  getContextForLLM(threadId: string, maxTokens?: number): string {
    // 压缩记忆以适应LLM上下文限制
  }

  clear(threadId: string): void {
    this.store.delete(threadId)
  }
}
```

### 3.3 Session Memory (长期记忆)

```typescript
// 跨会话的长期知识存储
interface MemoryEntry {
  id: string
  content: string
  embedding?: number[]
  metadata: {
    source: string
    createdAt: number
    accessCount: number
    lastAccessedAt: number
    tags: string[]
  }
}

class SessionMemoryService {
  constructor(private vectorStore: VectorStoreInterface) {}

  async store(
    content: string,
    metadata: MemoryMetadata
  ): Promise<string> {}

  async recall(
    query: string,
    topK?: number
  ): Promise<MemoryEntry[]> {}

  async updateAccessStats(entryId: string): Promise<void> {}

  async getRelevantMemories(
    context: string,
    threshold?: number
  ): Promise<MemoryEntry[]> {}
}
```

---

## 四、实施计划

### 4.1 阶段一：架构基础 (1-2天)

1. **创建RAG状态机**
   - 定义RAGContext接口
   - 实现RAG StateMachine (XState v5)
   - 添加状态转换逻辑

2. **完善Tool Bridge**
   - 重构现有tools.ts
   - 实现真正的四库连接
   - 添加错误处理和重试

### 4.2 阶段二：Memory管理 (1-2天)

1. **Thread Memory**
   - 实现消息历史管理
   - 实现推理步骤记录
   - 实现上下文压缩

2. **Session Memory**
   - 实现向量存储集成
   - 实现记忆检索
   - 实现访问统计

### 4.3 阶段三：集成测试 (1天)

1. 端到端RAG流程测试
2. 状态持久化测试
3. Memory恢复测试

---

## 五、文件结构

```
src/backend/server/src/modules/
├── rag/                          # RAG模块 (新增)
│   ├── index.ts
│   ├── context.ts               # RAGContext定义
│   ├── machine.ts               # RAG StateMachine
│   ├── tool-bridge.ts          # Tool桥接层
│   ├── memory/
│   │   ├── thread-memory.ts    # 短期记忆
│   │   └── session-memory.ts   # 长期记忆
│   └── types.ts
│
├── agent/                        # 现有Agent模块 (重构)
│   ├── src/
│   │   ├── types.ts
│   │   ├── tools.ts            # 复用为Tool定义
│   │   ├── react-loop.ts      # 复用核心逻辑
│   │   └── factory.ts
│   └── (保持现有结构)
│
└── retrieval/                    # 现有检索模块 (复用)
    └── src/
        ├── index.ts
        └── cascade-retrieval.ts
```

---

## 六、接口定义

### 6.1 RAG Machine API

```typescript
interface RAGMachineAPI {
  // 启动RAG流程
  start(query: string, options?: RAGOptions): Promise<RAGResult>

  // 获取当前状态
  getState(): RAGStateInfo

  // 中断流程
  interrupt(): void

  // 恢复流程
  resume(): void

  // 获取记忆上下文
  getMemoryContext(): string
}
```

### 6.2 Tool接口

```typescript
interface RAGTool {
  name: string
  description: string
  execute(args: ToolArgs): Promise<ToolResult>
  validate(args: ToolArgs): ValidationResult
}
```

---

## 七、关键设计决策

### 7.1 为什么复用而非重写？

| 方案 | 优点 | 缺点 |
|-----|------|-----|
| **复用现有组件** | 工作量小、风险低、保持一致 | 需要适配层 |
| **完全重写** | 架构干净 | 工作量大、可能破坏现有功能 |

**决策**: 复用 + 适配层

### 7.2 状态机 vs 直接调用

| 方案 | 适用场景 |
|-----|---------|
| **状态机驱动** | 需要持久化、检查点、回滚 |
| **直接调用** | 简单场景、无状态要求 |

**决策**: 核心流程用状态机，工具执行用直接调用

### 7.3 Memory存储选型

| 方案 | 适用场景 |
|-----|---------|
| **Redis** | 高性能、需持久化 |
| **内存** | 开发测试、低延迟 |
| **向量存储** | 语义检索 |

**决策**: Thread Memory用内存，Session Memory用向量存储 + Redis持久化

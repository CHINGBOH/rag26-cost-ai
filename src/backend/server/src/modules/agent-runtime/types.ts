/**
 * Agent Runtime 核心类型定义
 * Agent 内建 Channel + Runtime + Evaluator + ToolRegistry
 */

// ==================== 工具相关 ====================

export interface ToolArgs {
  query?: string;
  topK?: number;
  expression?: string;
  filters?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ToolResult {
  success: boolean;
  data?: unknown;
  error?: string;
  latencyMs: number;
  metadata?: Record<string, unknown>;
}

export interface ToolDefinition {
  name: string;
  description: string;
  execute: (args: ToolArgs) => Promise<ToolResult>;
}

// ==================== Channel 状态 ====================

export type AgentStatus =
  | 'idle'
  | 'understanding'
  | 'planning'
  | 'retrieving'
  | 'generating'
  | 'evaluating'
  | 'reflecting'
  | 'completed'
  | 'failed';

export type QueryIntent =
  | 'factual'        // 事实查询（定额子目、费率系数）
  | 'comparative'    // 对比查询（跨版本、跨时间）
  | 'analytical'     // 分析查询（价格走势）
  | 'computational'  // 计算查询（费率反推）
  | 'procedural';    // 流程查询（填报规则）

export type RetrievalStrategy =
  | 'vector_only'
  | 'keyword_only'
  | 'hybrid'
  | 'graph_first'
  | 'structured_first';

export interface RetrievedChunk {
  id: string;
  content: string;
  source: string;
  database: 'vector' | 'keyword' | 'graph' | 'structured';
  score: number;
  metadata?: {
    page?: number;
    section?: string;
    docName?: string;
    [key: string]: unknown;
  };
}

export interface Citation {
  chunkId: string;
  docId: string;
  docName?: string;
  pageNumber?: number;
  text: string;
  sourceDb: 'vector' | 'keyword' | 'graph' | 'structured';
  score: number;
}

export interface Calculation {
  formula: string;
  inputs: Record<string, number>;
  result: number;
  explanation: string;
}

export interface EvaluationResult {
  completeness: number;      // 信息完整性 [0, 1]
  consistency: number;       // 逻辑一致性 [0, 1]
  confidence: number;        // 综合置信度 [0, 1]
  informationGain: number;   // 信息增益
  sourceDiversity: number;   // 来源多样性 [0, 1]
  factConsistency: number;   // 事实一致性 [0, 1]
  coverageEstimate: number;  // 覆盖率估计 [0, 1]
  overall: number;           // 综合得分
  passed: boolean;           // 是否通过
  suggestions?: string[];    // 优化建议
}

export interface AgentState {
  // 查询信息
  query: string;
  normalizedQuery?: string;
  intent?: QueryIntent;
  subQueries?: string[];

  // 检索结果
  retrievedChunks: RetrievedChunk[];
  retrievalStrategy?: RetrievalStrategy;

  // 生成结果
  answer?: string;
  citations?: Citation[];
  calculations?: Calculation[];

  // 评估结果
  evaluation?: EvaluationResult;

  // 工具执行记录
  toolResults: Map<string, ToolResult>;

  // 迭代控制
  iteration: number;
  maxIterations: number;

  // 状态
  status: AgentStatus;
  error?: string;

  // 元数据
  sessionId: string;
  createdAt: number;
  updatedAt: number;
}

// ==================== Reducer ====================

export type MergeStrategy = 'lastWriteWins' | 'append' | 'merge' | 'sum';

export interface StateReducer<T = any> {
  (current: T, update: T): T;
}

export interface ChannelConfig {
  maxHistorySize?: number;      // 历史版本最大保留数
  reducers?: Record<string, StateReducer>;
}

// ==================== Runtime ====================

export interface RuntimeConfig {
  maxIterations: number;        // 最大迭代次数
  confidenceThreshold: number;  // 置信度阈值
  enableAutoReflect: boolean;   // 是否启用自动反思
  timeoutMs: number;            // 总超时时间
}

export interface AgentResult {
  success: boolean;
  answer?: string;
  citations?: Citation[];
  calculations?: Calculation[];
  evaluation?: EvaluationResult;
  iterations: number;
  error?: string;
  state: AgentState;
}

export interface AgentEvent {
  type: 'state_change' | 'tool_call' | 'tool_result' | 'generation' | 'evaluation' | 'iteration' | 'complete' | 'error';
  timestamp: number;
  payload: Record<string, unknown>;
}

export type AgentEventHandler = (event: AgentEvent) => void;

// ==================== 扩展接口 ====================

export interface ToolRegistry {
  register(tool: ToolDefinition): void;
  unregister(name: string): void;
  get(name: string): ToolDefinition | undefined;
  list(): ToolDefinition[];
  execute(name: string, args: ToolArgs): Promise<ToolResult>;
}

export interface Evaluator {
  evaluate(state: AgentState): Promise<EvaluationResult>;
}

export interface LLMDriver {
  generate(state: AgentState): Promise<{ answer: string; citations: Citation[]; calculations?: Calculation[] }>;
  plan(state: AgentState): Promise<{ strategy: RetrievalStrategy; subQueries: string[] }>;
  understand(query: string): Promise<{ intent: QueryIntent; normalizedQuery: string }>;
  reflect(state: AgentState): Promise<{ suggestions: string[]; newStrategy?: RetrievalStrategy }>;
}

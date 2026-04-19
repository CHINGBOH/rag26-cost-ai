/**
 * 递归系统核心类型定义
 * 专家驱动的动态边界 RAG 系统
 */

// ==================== 基础类型 ====================

export type DatabaseTarget = 'vector' | 'graph' | 'sql' | 'knowledge';

export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed';

export type RecursionState = 
  | 'idle'
  | 'decomposing'
  | 'dispatching'
  | 'retrieving'
  | 'ranking'
  | 'generating'
  | 'evaluating'
  | 'deciding'
  | 'querying_external'
  | 'human_review'
  | 'completed'
  | 'failed';

// ==================== 文档块 ====================

export interface RetrievedChunk {
  id: string;
  content: string;
  source: string;              // 来源文档路径/ID
  database: DatabaseTarget;    // 来自哪个库
  score: number;               // 相似度分数
  metadata: {
    page?: number;
    section?: string;
    ocr_confidence?: number;
    timestamp?: number;
  };
}

// ==================== 递归轮次 ====================

export interface SubQuery {
  id: string;
  query: string;
  targetDB: DatabaseTarget;
  status: TaskStatus;
  latency?: number;
  resultCount?: number;
}

export interface RoundEvaluation {
  completeness: number;        // 完整性 0-1
  consistency: number;         // 一致性 0-1
  confidence: number;          // 置信度 0-1
  informationGain: number;     // 相比上一轮的信息增益
  sourceDiversity: number;     // 来源多样性
  factConsistency: number;     // 事实一致性
  coverageEstimate: number;    // 覆盖率估计
}

export interface Contradiction {
  chunkA: string;
  chunkB: string;
  description: string;
  severity: 'low' | 'medium' | 'high';
}

export interface RecursionRound {
  roundId: number;
  timestamp: number;
  
  // 查询拆解
  subQueries: SubQuery[];
  
  // 召回结果
  retrievedChunks: RetrievedChunk[];
  contradictions: Contradiction[];
  
  // 生成的答案
  generatedAnswer?: string;
  
  // 评估
  evaluation?: RoundEvaluation;
  
  // 决策
  decision?: ExpertDecision;
  
  // 专家判断理由
  expertReasoning?: string;
}

// ==================== 专家判断 ====================

export type ExpertDecision = 
  | 'satisfy'           // 满意，停止
  | 'continue'          // 继续递归
  | 'query_external'    // 查询外部（社区/网络）
  | 'human_review';     // 需要人工审核

export interface ContinueStrategy {
  focus: 'deeper' | 'broader' | 'clarify_contradiction';
  suggestedQueries: string[];
}

export interface ExternalQueryRequest {
  target: 'community' | 'web_search' | 'knowledge_base';
  query: string;
  context: string;      // 当前递归的上下文
}

export interface BoundaryAssessment {
  saturationLevel: 'low' | 'medium' | 'high';
  riskOfOverthinking: 'low' | 'medium' | 'high';
}

export interface ExpertJudgmentRequest {
  context: {
    originalQuery: string;
    currentDepth: number;
    recursionHistory: RecursionRound[];
  };
  
  currentState: {
    generatedAnswer: string;
    supportingEvidence: RetrievedChunk[];
    contradictionsFound: Contradiction[];
    confidenceSignals: Omit<RoundEvaluation, 'informationGain'>;
  };
  
  question: 'should_stop' | 'should_continue' | 'need_external_query';
}

export interface ExpertJudgmentResponse {
  decision: ExpertDecision;
  reasoning: string;
  continueStrategy?: ContinueStrategy;
  externalQuery?: ExternalQueryRequest;
  boundaryAssessment: BoundaryAssessment;
}

// ==================== 递归会话 ====================

export interface RecursionSession {
  id: string;
  originalQuery: string;
  createdAt: number;
  updatedAt: number;
  
  currentState: RecursionState;
  currentDepth: number;
  rounds: RecursionRound[];
  
  // 全局指标
  metrics: {
    totalChunksRetrieved: number;
    averageConfidence: number;
    maxDepthReached: number;
    totalLatency: number;
  };
  
  // 异常标记
  anomalies: Anomaly[];
  
  // 最终输出
  finalAnswer?: string;
  citations?: Citation[];
}

export interface Anomaly {
  id: string;
  timestamp: number;
  type: string;
  level: 'warning' | 'critical';
  message: string;
  context: any;
}

export interface Citation {
  claimId: string;
  claimText: string;
  supportingChunks: string[];
  confidence: number;
}

// ==================== 看板事件 ====================

export type DashboardEventType =
  | 'state_change'
  | 'recursion_round_start'
  | 'subquery_complete'
  | 'retrieval_complete'
  | 'generation_complete'
  | 'evaluation_complete'
  | 'expert_judgment'
  | 'boundary_detected'
  | 'external_query_start'
  | 'external_query_complete'
  | 'anomaly_alert'
  | 'human_review_required'
  | 'recursion_complete'
  | 'session_created'
  | 'vitals_update'
  | 'yolo_started'
  | 'yolo:layer_start'
  | 'yolo:layer_complete'
  | 'yolo:completed'
  | 'yolo:failed';

export interface DashboardEvent {
  type: DashboardEventType;
  sessionId: string;
  timestamp: number;
  payload: any;
}

// ==================== 系统指标 ====================

export interface SystemVitals {
  healthScore: number;         // 0-100
  recursionDepth: number;
  maxDepthReached: number;
  
  activeTasks: number;
  pendingTasks: number;
  completedTasks: number;
  
  confidenceTrend: 'up' | 'down' | 'stable';
  
  // 实时性能指标
  latency: {
    retrieval: number;
    generation: number;
    evaluation: number;
  };
}

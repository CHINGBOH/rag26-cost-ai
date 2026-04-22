/**
 * Chat 组件共享类型
 * 提取自 ChatInterface.tsx，用于消除循环依赖
 */

export type PipelineStage =
  | 'idle'
  | 'intent_analysis'
  | 'query_decomposition'
  | 'vector_retrieval'
  | 'knowledge_retrieval'
  | 'graph_retrieval'
  | 'reranking'
  | 'context_assembly'
  | 'llm_generation'
  | 'complete';

export interface PipelineState {
  stage: PipelineStage;
  progress: number;
  status: 'pending' | 'running' | 'completed' | 'error';
  details?: string;
  metrics?: Record<string, number>;
}

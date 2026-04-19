/**
 * RAG类型定义
 * 定义RAG流程中使用的所有类型
 */

import { z } from 'zod'
import { RetrievedChunkSchema, DatabaseTargetSchema } from '../common/types/src'

// ==================== 枚举定义 ====================

export const RAGStateSchema = z.enum([
  'idle',
  'query_understanding',
  'planning',
  'retrieving',
  'retrieved',
  'reasoning',
  'generating',
  'evaluating',
  'completed',
  'failed',
  'awaiting_human_review'
])
export type RAGState = z.infer<typeof RAGStateSchema>

export const QueryIntentSchema = z.enum([
  'factual',
  'explanatory',
  'analytical',
  'comparative',
  'procedural',
  'opinion'
])
export type QueryIntent = z.infer<typeof QueryIntentSchema>

export const RetrievalStrategySchema = z.enum([
  'vector_only',
  'keyword_only',
  'hybrid',
  'graph_first',
  'cascade'
])
export type RetrievalStrategy = z.infer<typeof RetrievalStrategySchema>

// ==================== 上下文类型 ====================

export interface RAGContext {
  sessionId: string
  threadId: string
  currentDepth: number
  maxDepth: number
  iterations: number
  maxIterations: number
  error?: Error

  query: string
  queryEmbedding?: number[]
  intent?: QueryIntent
  normalizedQuery?: string

  retrievedChunks: z.infer<typeof RetrievedChunkSchema>[]
  retrievalStrategy?: RetrievalStrategy
  fusionScores?: Map<string, number>

  response?: string
  citations?: Citation[]
  confidence?: number

  evaluation?: EvaluationResult
  reasoningSteps: ReasoningStep[]

  availableTools: string[]
  toolResults: Map<string, ToolResult>

  createdAt: number
  updatedAt: number
}

export interface Citation {
  chunkId: string
  docId: string
  pageNumber?: number
  score: number
  text: string
  sourceDb: z.infer<typeof DatabaseTargetSchema>
}

export interface EvaluationResult {
  completeness: number
  consistency: number
  confidence: number
  informationGain: number
  sourceDiversity: number
  factConsistency: number
  coverageEstimate: number
  overall: number
  passed: boolean
  suggestions?: string[]
}

export interface ReasoningStep {
  id?: string
  stepNumber: number
  type: 'planning' | 'retrieval' | 'analysis' | 'synthesis'
  content: string
  toolUsed?: string
  resultSummary?: string
  timestamp: number
}

// ==================== 事件类型 ====================

export const RAGEventSchema = z.discriminatedUnion('type', [
  z.object({
    type: z.literal('START'),
    query: z.string(),
    threadId: z.string().optional()
  }),
  z.object({
    type: z.literal('QUERY_UNDERSTOOD'),
    intent: QueryIntentSchema,
    normalizedQuery: z.string()
  }),
  z.object({
    type: z.literal('PLAN_CREATED'),
    strategy: RetrievalStrategySchema,
    subQueries: z.array(z.string())
  }),
  z.object({
    type: z.literal('RETRIEVE_COMPLETE'),
    chunks: z.array(z.any()),
    sources: z.record(z.string())
  }),
  z.object({
    type: z.literal('TOOL_COMPLETE'),
    toolName: z.string(),
    result: z.any()
  }),
  z.object({
    type: z.literal('TOOL_ERROR'),
    toolName: z.string(),
    error: z.string()
  }),
  z.object({
    type: z.literal('REASONING_COMPLETE'),
    steps: z.array(z.any()),
    synthesis: z.string()
  }),
  z.object({
    type: z.literal('GENERATION_COMPLETE'),
    response: z.string(),
    citations: z.array(z.any()),
    confidence: z.number()
  }),
  z.object({
    type: z.literal('EVALUATION_COMPLETE'),
    evaluation: z.any()
  }),
  z.object({
    type: z.literal('HUMAN_REVIEW'),
    approved: z.boolean(),
    feedback: z.string().optional()
  }),
  z.object({
    type: z.literal('ERROR'),
    error: z.any()
  }),
  z.object({
    type: z.literal('CANCEL')
  }),
  z.object({
    type: z.literal('RETRY')
  }),
  z.object({
    type: z.literal('TIMEOUT')
  })
])
export type RAGEvent = z.infer<typeof RAGEventSchema>

// ==================== 工具相关类型 ====================

export interface ToolArgs {
  query?: string
  topK?: number
  expression?: string
  filters?: Record<string, unknown>
  [key: string]: unknown
}

export interface ToolResult {
  success: boolean
  data?: unknown
  error?: string
  latencyMs: number
  metadata?: Record<string, unknown>
}

export interface ToolDefinition {
  name: string
  description: string
  parameters: z.ZodType<unknown>
  execute: (args: ToolArgs) => Promise<ToolResult>
}

// ==================== 配置类型 ====================

export const RAGOptionsSchema = z.object({
  maxIterations: z.number().min(1).max(20).default(5),
  maxDepth: z.number().min(1).max(10).default(3),
  confidenceThreshold: z.number().min(0).max(1).default(0.85),
  enableHumanReview: z.boolean().default(false),
  timeout: z.number().min(10000).max(300000).default(120000),
  retrieval: z.object({
    topK: z.number().default(10),
    vectorWeight: z.number().default(0.6),
    graphWeight: z.number().default(0.4),
    enableRerank: z.boolean().default(true),
    enableFusion: z.boolean().default(true)
  })
})
export type RAGOptions = z.infer<typeof RAGOptionsSchema>

// ==================== 结果类型 ====================

export interface RAGResult {
  success: boolean
  response?: string
  citations?: Citation[]
  confidence?: number
  evaluation?: EvaluationResult
  error?: string
  metadata: {
    totalLatencyMs: number
    iterations: number
    toolsUsed: string[]
    retrievalStats: {
      totalChunks: number
      sources: Record<string, number>
    }
  }
}

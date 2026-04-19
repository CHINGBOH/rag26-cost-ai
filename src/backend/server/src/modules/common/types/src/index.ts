/**
 * 模块间共享类型定义 - 基于 Zod Schema
 * 提供运行时类型安全和类型推断
 */

import { z } from 'zod'

// ==================== 基础 Schema ====================

export const NullableSchema = <T extends z.ZodTypeAny>(schema: T) => 
  schema.nullable().optional()

export const ApiResponseSchema = <T extends z.ZodTypeAny>(dataSchema: T) => z.object({
  success: z.boolean(),
  data: dataSchema.optional(),
  error: z.object({
    code: z.string(),
    message: z.string(),
    details: z.unknown().optional()
  }).optional(),
  meta: z.object({
    timestamp: z.number(),
    requestId: z.string().optional()
  }).optional()
})

export const PaginationParamsSchema = z.object({
  page: z.number().min(1),
  pageSize: z.number().min(1).max(100)
})

export const PaginatedResultSchema = <T extends z.ZodTypeAny>(itemSchema: T) => z.object({
  items: z.array(itemSchema),
  total: z.number(),
  page: z.number(),
  pageSize: z.number(),
  totalPages: z.number()
})

// ==================== 检索模块 Schema ====================

export const DatabaseTargetSchema = z.enum(['vector', 'keyword', 'graph', 'knowledge'])
export type DatabaseTarget = z.infer<typeof DatabaseTargetSchema>

export const RetrievedChunkSchema = z.object({
  id: z.string(),
  content: z.string(),
  source: z.string(),
  database: DatabaseTargetSchema,
  score: z.number(),
  metadata: z.record(z.unknown()).optional()
})
export type RetrievedChunk = z.infer<typeof RetrievedChunkSchema>

export const SubQuerySchema = z.object({
  id: z.string(),
  query: z.string(),
  targetDB: DatabaseTargetSchema,
  status: z.enum(['pending', 'processing', 'completed', 'failed']),
  result: z.array(RetrievedChunkSchema).optional()
})
export type SubQuery = z.infer<typeof SubQuerySchema>

export const RoundEvaluationSchema = z.object({
  completeness: z.number().min(0).max(1),
  consistency: z.number().min(0).max(1),
  confidence: z.number().min(0).max(1),
  informationGain: z.number().min(0).max(1),
  sourceDiversity: z.number().min(0).max(1),
  factConsistency: z.number().min(0).max(1),
  coverageEstimate: z.number().min(0).max(1)
})
export type RoundEvaluation = z.infer<typeof RoundEvaluationSchema>

export const RetrievalOptionsSchema = z.object({
  topK: z.number().optional(),
  enableRerank: z.boolean().optional(),
  enableFusion: z.boolean().optional(),
  timeout: z.number().optional()
})
export type RetrievalOptions = z.infer<typeof RetrievalOptionsSchema>

// ==================== 递归模块 Schema ====================

export const RecursionMetricsSchema = z.object({
  totalChunksRetrieved: z.number(),
  averageConfidence: z.number(),
  maxDepthReached: z.number(),
  totalLatency: z.number()
})
export type RecursionMetrics = z.infer<typeof RecursionMetricsSchema>

export const AnomalySchema = z.object({
  type: z.string(),
  message: z.string(),
  severity: z.enum(['warning', 'error', 'critical']),
  timestamp: z.number()
})
export type Anomaly = z.infer<typeof AnomalySchema>

export const ExpertDecisionSchema = z.object({
  shouldContinue: z.boolean(),
  confidence: z.number(),
  reason: z.string(),
  nextAction: z.enum(['continue', 'stop', 'escalate']).optional(),
  suggestedQueries: z.array(z.string()).optional()
})
export type ExpertDecision = z.infer<typeof ExpertDecisionSchema>

export const RecursionRoundSchema: z.ZodType<any> = z.lazy(() => z.object({
  id: z.string(),
  depth: z.number(),
  subQueries: z.array(SubQuerySchema),
  retrievedChunks: z.array(RetrievedChunkSchema),
  evaluation: RoundEvaluationSchema,
  answer: z.string().optional(),
  expertDecision: ExpertDecisionSchema,
  timestamp: z.number()
}))
export type RecursionRound = z.infer<typeof RecursionRoundSchema>

export const RecursionSessionSchema: z.ZodType<any> = z.lazy(() => z.object({
  id: z.string(),
  originalQuery: z.string(),
  createdAt: z.number(),
  updatedAt: z.number(),
  currentState: z.string(),
  currentDepth: z.number(),
  rounds: z.array(RecursionRoundSchema),
  metrics: RecursionMetricsSchema,
  anomalies: z.array(AnomalySchema)
}))
export type RecursionSession = z.infer<typeof RecursionSessionSchema>

// ==================== OCR 模块 Schema ====================

export const OCRTextBlockSchema = z.object({
  id: z.string(),
  text: z.string(),
  confidence: z.number(),
  bbox: z.tuple([z.number(), z.number(), z.number(), z.number()]),
  type: z.enum(['text', 'table', 'image'])
})
export type OCRTextBlock = z.infer<typeof OCRTextBlockSchema>

export const OCRPageSchema = z.object({
  pageNum: z.number(),
  width: z.number(),
  height: z.number(),
  textBlocks: z.array(OCRTextBlockSchema)
})
export type OCRPage = z.infer<typeof OCRPageSchema>

export const OCRResultSchema = z.object({
  docId: z.string(),
  filename: z.string(),
  pages: z.array(OCRPageSchema),
  totalPages: z.number(),
  processingTime: z.number(),
  metadata: z.record(z.unknown()).optional()
})
export type OCRResult = z.infer<typeof OCRResultSchema>

// ==================== 管道模块 Schema ====================

export const PipelineStatusSchema = z.enum(['pending', 'running', 'completed', 'failed', 'cancelled'])
export type PipelineStatus = z.infer<typeof PipelineStatusSchema>

export const PipelineStepSchema: z.ZodType<any> = z.lazy(() => z.object({
  id: z.string(),
  name: z.string(),
  status: PipelineStatusSchema,
  input: z.unknown().optional(),
  output: z.unknown().optional(),
  error: z.string().optional(),
  startedAt: z.number().optional(),
  completedAt: z.number().optional()
}))
export type PipelineStep = z.infer<typeof PipelineStepSchema>

export const PipelineJobSchema = z.object({
  id: z.string(),
  name: z.string(),
  status: PipelineStatusSchema,
  steps: z.array(PipelineStepSchema),
  currentStep: z.number(),
  data: z.unknown(),
  result: z.unknown().optional(),
  error: z.string().optional(),
  createdAt: z.number(),
  updatedAt: z.number()
})
export type PipelineJob = z.infer<typeof PipelineJobSchema>

export const PipelineConfigSchema = z.object({
  concurrency: z.number().optional(),
  retryCount: z.number().optional(),
  timeout: z.number().optional(),
  onStepComplete: z.function().args(z.any(), z.any()).returns(z.void()).optional(),
  onStepError: z.function().args(z.any(), z.any(), z.any()).returns(z.void()).optional()
})
export type PipelineConfig = z.infer<typeof PipelineConfigSchema>

// ==================== 存储模块 Schema ====================

export const CacheAdapterSchema = z.object({
  get: z.function().args(z.string()).returns(z.promise(z.unknown().optional())),
  set: z.function().args(z.string(), z.unknown(), z.number().optional()).returns(z.promise(z.void())),
  delete: z.function().args(z.string()).returns(z.promise(z.void())),
  has: z.function().args(z.string()).returns(z.promise(z.boolean())),
  clear: z.function().returns(z.promise(z.void()))
})
export type CacheAdapter<T = unknown> = Omit<z.infer<typeof CacheAdapterSchema>, 'get' | 'set'> & {
  get(key: string): Promise<T | undefined>
  set(key: string, value: T, ttl?: number): Promise<void>
}

export const QueueAdapterSchema = z.object({
  enqueue: z.function().args(z.unknown()).returns(z.promise(z.void())),
  dequeue: z.function().returns(z.promise(z.unknown().optional())),
  peek: z.function().returns(z.promise(z.unknown().optional())),
  size: z.function().returns(z.promise(z.number())),
  isEmpty: z.function().returns(z.promise(z.boolean()))
})
export type QueueAdapter<T = unknown> = Omit<z.infer<typeof QueueAdapterSchema>, 'enqueue' | 'dequeue' | 'peek'> & {
  enqueue(item: T): Promise<void>
  dequeue(): Promise<T | undefined>
  peek(): Promise<T | undefined>
}

export const StoreAdapterSchema = z.object({
  save: z.function().args(z.string(), z.unknown()).returns(z.promise(z.void())),
  load: z.function().args(z.string()).returns(z.promise(z.unknown().optional())),
  delete: z.function().args(z.string()).returns(z.promise(z.void())),
  list: z.function().returns(z.promise(z.array(z.string())))
})
export type StoreAdapter<T = unknown> = Omit<z.infer<typeof StoreAdapterSchema>, 'save' | 'load'> & {
  save(key: string, value: T): Promise<void>
  load(key: string): Promise<T | undefined>
}

// ==================== 专家模块 Schema ====================

export const ExpertJudgmentRequestSchema = z.object({
  context: z.string(),
  rounds: z.array(RecursionRoundSchema),
  metrics: RecursionMetricsSchema,
  query: z.string()
})
export type ExpertJudgmentRequest = z.infer<typeof ExpertJudgmentRequestSchema>

export const ExpertJudgmentResponseSchema = z.object({
  decision: ExpertDecisionSchema,
  reasoning: z.string(),
  confidence: z.number(),
  timestamp: z.number()
})
export type ExpertJudgmentResponse = z.infer<typeof ExpertJudgmentResponseSchema>

export const BoundaryAssessmentSchema = z.object({
  withinBoundaries: z.boolean(),
  boundaryType: z.string().optional(),
  suggestedAction: z.string(),
  confidence: z.number()
})
export type BoundaryAssessment = z.infer<typeof BoundaryAssessmentSchema>

// ==================== LLM 模块 Schema ====================

export const LLMConfigSchema = z.object({
  model: z.string(),
  temperature: z.number().optional(),
  maxTokens: z.number().optional(),
  topP: z.number().optional(),
  apiKey: z.string().optional(),
  baseUrl: z.string().optional()
})
export type LLMConfig = z.infer<typeof LLMConfigSchema>

export const LLMResponseSchema = z.object({
  text: z.string(),
  usage: z.object({
    promptTokens: z.number(),
    completionTokens: z.number(),
    totalTokens: z.number()
  }).optional(),
  finishReason: z.string().optional()
})
export type LLMResponse = z.infer<typeof LLMResponseSchema>

export const EmbeddingConfigSchema = z.object({
  model: z.string(),
  dimensions: z.number(),
  apiKey: z.string().optional(),
  baseUrl: z.string().optional()
})
export type EmbeddingConfig = z.infer<typeof EmbeddingConfigSchema>

// ==================== 认证模块 Schema ====================

export const UserSchema = z.object({
  id: z.string(),
  username: z.string(),
  email: z.string().optional(),
  roles: z.array(z.string()),
  permissions: z.array(z.string()),
  createdAt: z.number(),
  lastLoginAt: z.number().optional()
})
export type User = z.infer<typeof UserSchema>

export const AuthCredentialsSchema = z.object({
  username: z.string(),
  password: z.string()
})
export type AuthCredentials = z.infer<typeof AuthCredentialsSchema>

export const AuthTokenSchema = z.object({
  token: z.string(),
  refreshToken: z.string().optional(),
  expiresAt: z.number(),
  user: UserSchema
})
export type AuthToken = z.infer<typeof AuthTokenSchema>

// ==================== 监控模块 Schema ====================

export const MetricDataSchema = z.object({
  name: z.string(),
  value: z.number(),
  timestamp: z.number(),
  labels: z.record(z.string()).optional()
})
export type MetricData = z.infer<typeof MetricDataSchema>

export const AlertSchema = z.object({
  id: z.string(),
  level: z.enum(['info', 'warning', 'error', 'critical']),
  category: z.string(),
  message: z.string(),
  timestamp: z.number(),
  resolved: z.boolean().optional(),
  resolvedAt: z.number().optional()
})
export type Alert = z.infer<typeof AlertSchema>

export const HealthStatusSchema = z.object({
  service: z.string(),
  status: z.enum(['healthy', 'degraded', 'unhealthy']),
  latency: z.number(),
  timestamp: z.number(),
  details: z.unknown().optional()
})
export type HealthStatus = z.infer<typeof HealthStatusSchema>

// ==================== WebSocket 模块 Schema ====================

export const WebSocketEventSchema = z.object({
  type: z.string(),
  payload: z.unknown(),
  timestamp: z.number(),
  sessionId: z.string().optional()
})
export type WebSocketEvent = z.infer<typeof WebSocketEventSchema>

export const WebSocketConfigSchema = z.object({
  port: z.number(),
  path: z.string().optional(),
  heartbeatInterval: z.number().optional(),
  maxConnections: z.number().optional()
})
export type WebSocketConfig = z.infer<typeof WebSocketConfigSchema>

// ==================== 错误 Schema ====================

export const ModuleErrorSchema = z.object({
  message: z.string(),
  code: z.string(),
  details: z.unknown().optional()
})

export class ModuleError extends Error {
  constructor(
    message: string,
    public code: string,
    public details?: unknown
  ) {
    super(message)
    this.name = 'ModuleError'
  }

  toJSON() {
    return {
      name: this.name,
      message: this.message,
      code: this.code,
      details: this.details
    }
  }
}

export class ValidationError extends ModuleError {
  constructor(message: string, details?: unknown) {
    super(message, 'VALIDATION_ERROR', details)
    this.name = 'ValidationError'
  }
}

export class TimeoutError extends ModuleError {
  constructor(message: string, timeout: number) {
    super(message, 'TIMEOUT_ERROR', { timeout })
    this.name = 'TimeoutError'
  }
}

// ==================== 类型守卫 ====================

export const isRetrievedChunk = (value: unknown): value is RetrievedChunk => {
  return RetrievedChunkSchema.safeParse(value).success
}

export const isRecursionSession = (value: unknown): value is RecursionSession => {
  return RecursionSessionSchema.safeParse(value).success
}

export const isOCRResult = (value: unknown): value is OCRResult => {
  return OCRResultSchema.safeParse(value).success
}

export const isPipelineJob = (value: unknown): value is PipelineJob => {
  return PipelineJobSchema.safeParse(value).success
}

export const isModuleError = (value: unknown): value is ModuleError => {
  return value instanceof ModuleError
}

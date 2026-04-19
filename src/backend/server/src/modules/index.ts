/**
 * RAG Dashboard 模块系统统一入口
 * 提供管道式架构的所有核心模块
 *
 * 使用示例:
 * ```typescript
 * import { pipe, retrieval, recursion } from './modules'
 *
 * const result = await pipe(query)
 *   .through(retrieval.decompose())
 *   .through(recursion.createRecursionFlow({ maxDepth: 3 }))
 *   .execute()
 * ```
 */

// ==================== 基础设施 ====================
export { pipe, PipeBuilder, createPipe, compose, parallel, withTimeout, withRetry, withCache } from './common/pipe'
export { createEventBus, EventBus, globalEventBus, emitEvent, waitForEvent } from './common/event-bus'
export * from './common/types'

// ==================== 核心模块 ====================
export * as retrieval from './retrieval'
export * as recursion from './recursion'
export * as ocr from './ocr'
export * as agent from './agent'

// ==================== 支持模块 ====================
export * as pipeline from './pipeline'
export * as storage from './storage'
export * as expert from './expert'
export * as llm from './llm'

// ==================== 基础设施模块 ====================
export * as auth from './auth'
export * as metrics from './metrics'
export * as websocket from './websocket'

// ==================== 模块快捷导出 ====================

// Agent 快捷导出
export {
  ReactAgent,
  createAgent,
  AgentFactory,
  createFourDatabaseTools
} from './agent'
export type {
  StructuredOutput,
  AgentOptions,
  IndexReference,
  Calculation,
  AgentFramework,
  Agent
} from './agent'

// Retrieval 快捷导出
export {
  decompose,
  vectorSearch,
  keywordSearch,
  graphSearch,
  retrieve,
  rerank,
  fuseScores,
  evaluate,
  healthCheck as retrievalHealthCheck,
  createRetrievalPipeline
} from './retrieval'

// Recursion 快捷导出
export {
  createRecursionFlow,
  createSession,
  createRound,
  expertJudgment,
  evaluateRound,
  saveSession,
  getSession,
  getAllSessions,
  deleteSession,
  cleanupSessions
} from './recursion'

// OCR 快捷导出
export {
  parsePDF,
  parsePDFFromPath,
  ocrImage,
  ocrPDF,
  extractText,
  extractTextBlocks,
  chunkDocument,
  chunkFromBlocks,
  processDocument,
  healthCheck as ocrHealthCheck,
  createOCRPipeline
} from './ocr'

// Pipeline 快捷导出
export {
  createPipeline,
  createJob,
  parallel as pipelineParallel,
  serial as pipelineSerial
} from './pipeline'

// Storage 快捷导出
export {
  createCache,
  createQueue,
  createStore,
  cacheGet,
  cacheSet,
  enqueue,
  dequeue,
  storeSave,
  storeLoad
} from './storage'

// Expert 快捷导出
export {
  expertJudge,
  assessBoundary,
  evaluateQuality
} from './expert'

// LLM 快捷导出
export {
  generateText,
  createEmbedding,
  batchCreateEmbedding,
  streamGenerate,
  cosineSimilarity,
  createLLMPipeline
} from './llm'

// Auth 快捷导出
export {
  authenticate,
  createToken,
  verifyToken,
  authorize,
  hasRole,
  refreshToken,
  revokeToken,
  createAuthPipeline
} from './auth'

// Metrics 快捷导出
export {
  initMetrics,
  collectMetrics,
  recordLatency,
  counter,
  gauge,
  createAlert,
  getMetrics,
  getStats,
  healthCheck as metricsHealthCheck,
  getAlerts,
  resolveAlert,
  createMetricsPipeline
} from './metrics'

// WebSocket 快捷导出
export {
  createWebSocketServer,
  broadcast,
  subscribe,
  unsubscribe,
  formatEvent,
  createConnection,
  disconnect,
  getConnectionCount,
  sendTo,
  createWebSocketPipeline
} from './websocket'

/**
 * RAG上下文工厂
 * 创建和管理RAG状态机上下文
 */

import { z } from 'zod'
import { RetrievedChunkSchema } from '../common/types/src'
import { RAGContext, RAGOptions, ReasoningStep } from './types'

type RetrievedChunk = z.infer<typeof RetrievedChunkSchema>

export function createInitialContext(
  sessionId: string,
  options?: Partial<RAGOptions>
): RAGContext {
  const now = Date.now()
  const opts = {
    maxIterations: 5,
    maxDepth: 3,
    confidenceThreshold: 0.85,
    enableHumanReview: false,
    timeout: 120000,
    retrieval: { topK: 10, vectorWeight: 0.6, graphWeight: 0.4, enableRerank: true, enableFusion: true },
    ...options
  }

  return {
    sessionId,
    threadId: `thread_${sessionId}`,
    currentDepth: 0,
    maxDepth: opts.maxDepth,
    iterations: 0,
    maxIterations: opts.maxIterations,
    error: undefined,

    query: '',
    queryEmbedding: undefined,
    intent: undefined,
    normalizedQuery: undefined,

    retrievedChunks: [],
    retrievalStrategy: undefined,
    fusionScores: undefined,

    response: undefined,
    citations: undefined,
    confidence: undefined,

    evaluation: undefined,
    reasoningSteps: [],

    availableTools: ['vectorSearch', 'keywordSearch', 'graphSearch', 'calculator'],
    toolResults: new Map(),

    createdAt: now,
    updatedAt: now
  }
}

export function createReasoningStep(
  stepNumber: number,
  type: ReasoningStep['type'],
  content: string,
  toolUsed?: string,
  resultSummary?: string
): ReasoningStep {
  return {
    stepNumber,
    type,
    content,
    toolUsed,
    resultSummary,
    timestamp: Date.now()
  }
}

export function updateContext(
  context: RAGContext,
  updates: Partial<RAGContext>
): RAGContext {
  return {
    ...context,
    ...updates,
    updatedAt: Date.now()
  }
}

export function addReasoningStep(
  context: RAGContext,
  step: ReasoningStep
): RAGContext {
  return {
    ...context,
    reasoningSteps: [...context.reasoningSteps, step],
    updatedAt: Date.now()
  }
}

export function addToolResult(
  context: RAGContext,
  toolName: string,
  result: { success: boolean; data?: unknown; error?: string; latencyMs: number }
): RAGContext {
  const newResults = new Map(context.toolResults)
  newResults.set(toolName, result)
  return {
    ...context,
    toolResults: newResults,
    updatedAt: Date.now()
  }
}

export function mergeRetrievalResults(
  existingChunks: RetrievedChunk[],
  newChunks: RetrievedChunk[]
): RetrievedChunk[] {
  const chunkMap = new Map<string, RetrievedChunk>()

  for (const chunk of existingChunks) {
    chunkMap.set(chunk.id, chunk)
  }

  for (const chunk of newChunks) {
    if (!chunkMap.has(chunk.id)) {
      chunkMap.set(chunk.id, chunk)
    }
  }

  return Array.from(chunkMap.values())
}

export function calculateConfidence(
  chunks: RetrievedChunk[],
  reasoningSteps: ReasoningStep[]
): number {
  if (chunks.length === 0) return 0

  const avgScore = chunks.reduce((sum, c) => sum + (c.score || 0), 0) / chunks.length

  const diversityBonus = Math.min(0.1, chunks.length * 0.01)

  const reasoningBonus = Math.min(0.1, reasoningSteps.length * 0.02)

  return Math.min(1, avgScore + diversityBonus + reasoningBonus)
}

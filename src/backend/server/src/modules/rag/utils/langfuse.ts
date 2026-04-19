/**
 * LangFuse - RAG 全链路追踪集成
 *
 * 文档: https://langfuse.com/docs
 *
 * 使用:
 * 1. 启动: cd infrastructure && docker-compose -f docker-compose.langfuse.yml up -d
 * 2. 访问: http://localhost:3001 (默认账号: langfuse, 密码在 DB 里)
 * 3. 创建项目，获取 API Key
 * 4. 配置环境变量: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
 */

import { Langfuse } from 'langfuse'
import type { RAGContext, RAGEvent } from '../types'

let langfuseInstance: Langfuse | null = null

interface LangfuseConfig {
  publicKey?: string
  secretKey?: string
  baseUrl?: string
  enabled?: boolean
}

/**
 * 初始化 LangFuse
 */
export function initLangfuse(config: LangfuseConfig = {}): Langfuse | null {
  if (config.enabled === false) {
    return null
  }

  const publicKey = config.publicKey || process.env.LANGFUSE_PUBLIC_KEY
  const secretKey = config.secretKey || process.env.LANGFUSE_SECRET_KEY
  const baseUrl = config.baseUrl || process.env.LANGFUSE_HOST || 'http://localhost:3001'

  if (!publicKey || !secretKey) {
    console.warn('[LangFuse] 未配置 API Key，追踪功能已禁用')
    return null
  }

  try {
    langfuseInstance = new Langfuse({
      publicKey,
      secretKey,
      baseUrl,
    })
    console.log('[LangFuse] 追踪已启用')
    return langfuseInstance
  } catch (error) {
    console.error('[LangFuse] 初始化失败:', error)
    return null
  }
}

/**
 * 获取 LangFuse 实例
 */
export function getLangfuse(): Langfuse | null {
  return langfuseInstance
}

/**
 * 追踪 RAG 查询
 */
export function traceRAGQuery(
  query: string,
  context: RAGContext,
  response?: string,
  error?: Error,
  metadata?: Record<string, unknown>
): string | null {
  if (!langfuseInstance) return null

  const trace = langfuseInstance.trace({
    name: 'rag-query',
    input: { query, context },
    output: response ? { response } : undefined,
    metadata: {
      sessionId: context.sessionId,
      threadId: context.threadId,
      ...metadata,
    },
  })

  if (error) {
    trace.update({
      output: { error: error.message },
      metadata: { level: 'ERROR' },
    })
  }

  return trace.id
}

/**
 * 追踪检索步骤
 */
export function traceRetrieval(
  traceId: string,
  retrievedChunks: unknown[],
  strategy: string,
  latencyMs: number
): void {
  if (!langfuseInstance) return

  const span = langfuseInstance.span({
    name: 'retrieval',
    traceId,
    input: { strategy, retrievedCount: retrievedChunks.length },
    output: { chunks: retrievedChunks },
    metadata: { latencyMs },
  })
  span.end()
}

/**
 * 追踪生成步骤
 */
export function traceGeneration(
  traceId: string,
  prompt: string,
  response: string,
  model: string,
  tokenUsage?: { prompt: number; completion: number }
): void {
  if (!langfuseInstance) return

  const generation = langfuseInstance.generation({
    name: 'llm-generation',
    traceId,
    model,
    input: prompt,
    output: response,
    usage: tokenUsage
      ? {
          promptTokens: tokenUsage.prompt,
          completionTokens: tokenUsage.completion,
          totalTokens: tokenUsage.prompt + tokenUsage.completion,
        }
      : undefined,
  })
  generation.end()
}

/**
 * 追踪评估步骤
 */
export function traceEvaluation(
  traceId: string,
  evaluation: {
    completeness: number
    consistency: number
    confidence: number
    passed: boolean
  }
): void {
  if (!langfuseInstance) return

  const span = langfuseInstance.span({
    name: 'evaluation',
    traceId,
    input: {},
    output: evaluation,
  })
  span.end()
}

/**
 * 关闭 LangFuse 连接
 */
export async function shutdownLangfuse(): Promise<void> {
  if (langfuseInstance) {
    await langfuseInstance.shutdownAsync()
    langfuseInstance = null
  }
}

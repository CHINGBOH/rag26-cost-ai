/**
 * RAG状态机 - 基于XState v5
 * 管理RAG流程的完整生命周期
 */

import { setup, assign, fromPromise, createActor } from 'xstate'
import { EventEmitter } from 'events'
import { z } from 'zod'
import {
  RAGContext,
  RAGEvent,
  RAGOptions,
  RAGResult,
  ToolResult,
  EvaluationResult,
  ReasoningStep
} from './types'
import {
  createInitialContext,
  createReasoningStep,
  addReasoningStep,
  addToolResult,
  mergeRetrievalResults,
  calculateConfidence
} from './context'
import { RetrievedChunkSchema } from '../common/types/src'
import { CascadeRetrievalService, CascadeSearchResult } from '../retrieval/src/cascade-retrieval'

type RetrievedChunk = z.infer<typeof RetrievedChunkSchema>

function toError(error: unknown): Error {
  if (error instanceof Error) return error
  if (typeof error === 'string') return new Error(error)
  return new Error(String(error))
}

function emitEvent(
  eventEmitter: EventEmitter,
  sessionId: string,
  eventType: string,
  data: Record<string, unknown>
): void {
  eventEmitter.emit('rag-event', { sessionId, eventType, data, timestamp: Date.now() })
}

export interface RAGMachineConfig {
  retrievalService?: CascadeRetrievalService
  eventEmitter?: EventEmitter
  onStateChange?: (state: string, context: RAGContext) => void
  onError?: (error: Error, context: RAGContext) => void
}

export class RAGStateMachine {
  private machine: ReturnType<typeof this.createMachine>
  private actor: ReturnType<typeof createActor>
  private config: RAGMachineConfig
  private eventEmitter: EventEmitter
  private retrievalService?: CascadeRetrievalService

  constructor(config: RAGMachineConfig = {}) {
    this.config = config
    this.eventEmitter = config.eventEmitter || new EventEmitter()
    this.retrievalService = config.retrievalService

    this.machine = this.createMachine()
    this.actor = createActor(this.machine, {
      input: config
    })

    this.actor.subscribe((state) => {
      if (state.status === 'error') {
        const error = state.error as Error
        this.config.onError?.(error, state.context as RAGContext)
      } else {
        this.config.onStateChange?.(String(state.value), state.context as RAGContext)
      }
    })
  }

  private createMachine() {
    return setup({
      types: {
        context: {} as RAGContext,
        events: {} as RAGEvent,
        input: {} as RAGMachineConfig
      },
      actions: {
        assignQuery: assign({
          query: ({ event }) => {
            if (event.type === 'START') return event.query
            return ''
          },
          threadId: ({ event, context }) => {
            if (event.type === 'START') return event.threadId || context.threadId
            return context.threadId
          },
          updatedAt: () => Date.now()
        }),

        assignIntent: assign({
          intent: ({ event }) => {
            if (event.type === 'QUERY_UNDERSTOOD') return event.intent
            const output = (event as any).output
            if (output?.intent) return output.intent
            return undefined
          },
          normalizedQuery: ({ event }) => {
            if (event.type === 'QUERY_UNDERSTOOD') return event.normalizedQuery
            const output = (event as any).output
            if (output?.normalizedQuery) return output.normalizedQuery
            return undefined
          },
          updatedAt: () => Date.now()
        }),

        assignStrategy: assign({
          retrievalStrategy: ({ event }) => {
            if (event.type === 'PLAN_CREATED') return event.strategy
            const output = (event as any).output
            if (output?.strategy) return output.strategy
            return undefined
          },
          updatedAt: () => Date.now()
        }),

        assignRetrievalResults: assign({
          retrievedChunks: ({ event, context }) => {
            if (event.type === 'RETRIEVE_COMPLETE') {
              const chunks = (event.chunks as RetrievedChunk[]) || []
              return mergeRetrievalResults(context.retrievedChunks, chunks)
            }
            const output = (event as any).output as CascadeSearchResult
            if (output?.results) {
              const chunks: RetrievedChunk[] = output.results.map(r => ({
                id: r.chunkId,
                content: r.content,
                source: r.docId,
                database: (r.metadata?.source_db as any) || 'vector',
                score: r.score,
                metadata: { ...r.metadata, pageNumber: r.pageNumber }
              }))
              return mergeRetrievalResults(context.retrievedChunks, chunks)
            }
            return context.retrievedChunks
          },
          updatedAt: () => Date.now()
        }),

        assignToolResult: assign({
          toolResults: ({ event, context }) => {
            if (event.type === 'TOOL_COMPLETE') {
              const newResults = new Map(context.toolResults)
              newResults.set(event.toolName, {
                success: true,
                data: event.result,
                latencyMs: 0
              })
              return newResults
            }
            if (event.type === 'TOOL_ERROR') {
              const newResults = new Map(context.toolResults)
              newResults.set(event.toolName, {
                success: false,
                error: event.error,
                latencyMs: 0
              })
              return newResults
            }
            return context.toolResults
          },
          updatedAt: () => Date.now()
        }),

        assignGeneration: assign({
          response: ({ event }) => {
            if (event.type === 'GENERATION_COMPLETE') return event.response
            const output = (event as any).output
            if (output?.response) return output.response
            return undefined
          },
          citations: ({ event }) => {
            if (event.type === 'GENERATION_COMPLETE') return event.citations as any
            const output = (event as any).output
            if (output?.citations) return output.citations
            return undefined
          },
          confidence: ({ event }) => {
            if (event.type === 'GENERATION_COMPLETE') return event.confidence
            const output = (event as any).output
            if (typeof output?.confidence === 'number') return output.confidence
            return undefined
          },
          updatedAt: () => Date.now()
        }),

        assignEvaluation: assign({
          evaluation: ({ event }) => {
            if (event.type === 'EVALUATION_COMPLETE') return event.evaluation as EvaluationResult
            const output = (event as any).output
            if (output?.completeness !== undefined) return output as EvaluationResult
            return undefined
          },
          updatedAt: () => Date.now()
        }),

        incrementIterations: assign({
          iterations: ({ context }) => context.iterations + 1,
          updatedAt: () => Date.now()
        }),

        incrementDepth: assign({
          currentDepth: ({ context }) => context.currentDepth + 1,
          updatedAt: () => Date.now()
        }),

        assignError: assign({
          error: ({ event }) => {
            if (event.type === 'ERROR') return toError(event.error)
            if (event.type === 'TIMEOUT') return new Error('Operation timeout')
            return undefined
          },
          updatedAt: () => Date.now()
        }),

        addReasoningStep: assign({
          reasoningSteps: ({ event, context }) => {
            if (event.type === 'REASONING_COMPLETE') {
              const steps = event.steps as ReasoningStep[]
              return [...context.reasoningSteps, ...steps]
            }
            const output = (event as any).output
            if (output?.steps) {
              return [...context.reasoningSteps, ...output.steps]
            }
            return context.reasoningSteps
          },
          updatedAt: () => Date.now()
        })
      },
      actors: {
        understandQuery: fromPromise(async ({ input }: { input: RAGContext }): Promise<{
          intent: string
          normalizedQuery: string
        }> => {
          await new Promise(resolve => setTimeout(resolve, 100))
          const query = input.query.toLowerCase()

          let intent: string = 'factual'
          if (query.includes('为什么') || query.includes('怎么') || query.includes('如何')) {
            intent = 'explanatory'
          } else if (query.includes('比较') || query.includes('对比')) {
            intent = 'comparative'
          } else if (query.includes('分析') || query.includes('评估')) {
            intent = 'analytical'
          }

          return {
            intent,
            normalizedQuery: input.query.trim()
          }
        }),

        planRetrieval: fromPromise(async ({ input }: { input: RAGContext }): Promise<{
          strategy: string
          subQueries: string[]
        }> => {
          await new Promise(resolve => setTimeout(resolve, 50))

          const hasGraphTerms = input.query.includes('关系') || input.query.includes('关联')
          const hasCompareTerms = input.query.includes('比较') || input.query.includes('对比')
          const hasCalcTerms = input.query.includes('计算') || input.query.includes('多少') || input.query.includes('费率')

          let strategy = 'hybrid'
          if (hasGraphTerms) {
            strategy = 'graph_first'
          } else if (hasCompareTerms) {
            strategy = 'cascade'
          } else if (hasCalcTerms) {
            strategy = 'hybrid'
          }

          const subQueries = [input.normalizedQuery || input.query]

          return { strategy, subQueries }
        }),

        executeRetrieval: fromPromise(async ({ input }: { input: RAGContext }): Promise<CascadeSearchResult> => {
          const pythonApiUrl = process.env.PYTHON_API_URL || 'http://localhost:8000'
          const controller = new AbortController()
          const timeoutId = setTimeout(() => controller.abort(), 30000)

          try {
            const response = await fetch(`${pythonApiUrl}/api/search`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                query: input.query,
                top_k: 10,
                mode: 'hybrid',
                session_id: input.sessionId,
              }),
              signal: controller.signal,
            })

            clearTimeout(timeoutId)

            if (!response.ok) {
              const errorText = await response.text()
              throw new Error(`Search API error: ${response.status} - ${errorText}`)
            }

            const data = (await response.json()) as any
            const results = data.data?.results || data.results || []

            const mappedResults = results.map((r: any) => ({
              chunkId: r.chunk_id || r.id || `chunk_${Math.random().toString(36).slice(2, 9)}`,
              docId: r.doc_id || r.source || 'unknown',
              content: r.content || '',
              pageNumber: r.metadata?.page_number || r.page_number || 1,
              score: r.score || 0,
              metadata: r.metadata || {},
            }))

            return {
              results: mappedResults,
              graphEntities: [],
              keywordContexts: [],
              structuredData: [],
              latencyMs: data.data?.latency_ms || data.latency_ms || { total: 0, vector: 0, graph: 0, keyword: 0, structured: 0 },
            }
          } catch (error) {
            clearTimeout(timeoutId)
            console.warn('[executeRetrieval] Fallback to empty results:', error)
            return {
              results: [],
              graphEntities: [],
              keywordContexts: [],
              structuredData: [],
              latencyMs: { total: 0, vector: 0, graph: 0, keyword: 0, structured: 0 },
            }
          }
        }),

        reasonAboutResults: fromPromise(async ({ input }: { input: RAGContext }): Promise<{
          steps: ReasoningStep[]
          synthesis: string
        }> => {
          await new Promise(resolve => setTimeout(resolve, 150))

          const chunks = input.retrievedChunks
          const step: ReasoningStep = {
            stepNumber: input.reasoningSteps.length + 1,
            type: 'analysis',
            content: `分析了${chunks.length}个检索结果`,
            resultSummary: chunks.length > 0 ? `最相关: ${chunks[0]?.content?.substring(0, 50)}...` : undefined,
            timestamp: Date.now()
          }

          return {
            steps: [step],
            synthesis: '基于检索结果进行推理'
          }
        }),

        generateResponse: fromPromise(async ({ input }: { input: RAGContext }): Promise<{
          response: string
          citations: any[]
          confidence: number
        }> => {
          const chunks = input.retrievedChunks
          const confidence = calculateConfidence(chunks as RetrievedChunk[], input.reasoningSteps)

          // 构建引用信息
          const citations = chunks.slice(0, 5).map((c: RetrievedChunk) => ({
            chunkId: c.id,
            docId: c.source,
            score: c.score,
            text: (c.content || '').substring(0, 200),
            sourceDb: c.database
          }))

          // 如果有LLM API配置，调用LLM生成自然语言回答
          const apiKey = process.env.DEEPSEEK_API_KEY || process.env.OPENAI_API_KEY
          const baseUrl = process.env.LLM_BASE_URL || 'https://api.deepseek.com'
          const model = process.env.LLM_MODEL || 'deepseek-chat'

          if (apiKey && chunks.length > 0) {
            try {
              const contextText = chunks
                .slice(0, 5)
                .map((c: RetrievedChunk, i: number) => `[${i + 1}] ${(c.content || '').slice(0, 400)} (来源: ${c.source})`)
                .join('\n\n')

              const prompt = `基于以下检索到的信息，回答用户问题。要求：
1. 用中文清晰、简洁地表达
2. 不要直接复制原文，要整合信息后用自己的话回答
3. 在回答末尾标注参考来源（如：参考 doc_0.md）
4. 如果信息不足，明确说明"根据现有资料无法完全回答"

检索信息：
${contextText}

用户问题：${input.query}

请生成回答：`

              const llmResponse = await fetch(`${baseUrl}/v1/chat/completions`, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  'Authorization': `Bearer ${apiKey}`,
                },
                body: JSON.stringify({
                  model,
                  messages: [
                    { role: 'system', content: '你是一个专业的信息整合助手，基于检索到的知识回答用户问题。' },
                    { role: 'user', content: prompt },
                  ],
                  temperature: 0.7,
                  max_tokens: 2000,
                }),
              })

              if (llmResponse.ok) {
                const llmData = (await llmResponse.json()) as any
                const content = llmData.choices?.[0]?.message?.content || ''
                if (content) {
                  return { response: content, citations, confidence }
                }
              }
            } catch (err) {
              console.warn('[generateResponse] LLM call failed:', err)
            }
          }

          // 降级：基于检索结果生成模板回答
          const response = chunks.length > 0
            ? `基于检索到的${chunks.length}条相关信息回答: ${input.query}\n\n${chunks.slice(0, 3).map((c: RetrievedChunk, i: number) => `${i + 1}. ${(c.content || '').slice(0, 200)}...`).join('\n')}\n\n参考来源: ${chunks.slice(0, 3).map((c: RetrievedChunk) => c.source).join(', ')}`
            : `无法找到相关信息来回答: ${input.query}`

          return { response, citations, confidence }
        }),

        evaluateResponse: fromPromise(async ({ input }: { input: RAGContext }): Promise<EvaluationResult> => {
          const confidence = input.confidence || 0
          const hasCitations = (input.citations?.length || 0) > 0
          const chunks = input.retrievedChunks

          // 尝试调用Python后端的评估接口
          const pythonApiUrl = process.env.PYTHON_API_URL || 'http://localhost:8000'
          try {
            const controller = new AbortController()
            const timeoutId = setTimeout(() => controller.abort(), 10000)
            const response = await fetch(`${pythonApiUrl}/api/v1/evaluate`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                query: input.query,
                retrieved_chunks: chunks.map((c: RetrievedChunk) => ({
                  content: c.content,
                  score: c.score,
                  source: c.source,
                })),
                generated_answer: input.response || '',
                history_rounds: input.iterations,
              }),
              signal: controller.signal,
            })
            clearTimeout(timeoutId)

            if (response.ok) {
              const evalData = (await response.json()) as any
              return {
                completeness: evalData.completeness ?? 0.5,
                consistency: evalData.consistency ?? 0.5,
                confidence: evalData.confidence ?? confidence,
                informationGain: evalData.information_gain ?? (hasCitations ? 0.7 : 0.2),
                sourceDiversity: evalData.source_diversity ?? Math.min(1, chunks.length / 10),
                factConsistency: evalData.fact_consistency ?? 0.9,
                coverageEstimate: evalData.coverage_estimate ?? 0.5,
                overall: evalData.confidence ?? ((evalData.completeness + confidence) / 2),
                passed: (evalData.confidence ?? confidence) >= 0.7 && hasCitations,
                suggestions: !hasCitations ? ['建议增加检索来源'] : undefined,
              }
            }
          } catch (err) {
            console.warn('[evaluateResponse] Evaluation API unavailable, using local heuristic:', err)
          }

          // 本地启发式评估
          const completeness = chunks.length > 0 ? Math.min(0.95, chunks.length * 0.15 + 0.2) : 0.3
          const sourceDiversity = Math.min(1, new Set(chunks.map((c: RetrievedChunk) => c.source)).size / 3)
          const overall = (completeness + confidence + sourceDiversity) / 3

          const evaluation: EvaluationResult = {
            completeness,
            consistency: 0.85,
            confidence,
            informationGain: hasCitations ? 0.7 : 0.2,
            sourceDiversity,
            factConsistency: hasCitations ? 0.85 : 0.5,
            coverageEstimate: completeness * sourceDiversity,
            overall,
            passed: confidence >= 0.7 && hasCitations,
            suggestions: !hasCitations ? ['建议增加检索来源'] : confidence < 0.7 ? ['建议扩大检索范围或调整查询'] : undefined,
          }

          return evaluation
        })
      },
      guards: {
        hasMoreIterations: ({ context }) => context.iterations < context.maxIterations,
        hasMoreDepth: ({ context }) => context.currentDepth < context.maxDepth,
        evaluationPassed: ({ context }) => context.evaluation?.passed ?? false,
        hasError: ({ context }) => context.error !== undefined,
        shouldRetry: ({ context }) => {
          if (!context.evaluation) return true
          return !context.evaluation.passed && context.iterations < context.maxIterations
        }
      }
    }).createMachine({
      id: 'rag-machine',
      initial: 'idle',
      context: ({ input }) => createInitialContext(`session_${Date.now()}`, {}),
      states: {
        idle: {
          on: {
            START: {
              target: 'queryUnderstanding',
              actions: assign({
                query: ({ event }) => event.query,
                threadId: ({ event, context }) => event.threadId || context.threadId,
                createdAt: () => Date.now(),
                updatedAt: () => Date.now()
              })
            }
          }
        },

        queryUnderstanding: {
          entry: ({ context }) => {
            emitEvent(this.eventEmitter, context.sessionId, 'state_change', { to: 'queryUnderstanding' })
          },
          invoke: {
            src: 'understandQuery',
            input: ({ context }) => context,
            onDone: {
              target: 'planning',
              actions: ['assignIntent', assign({
                reasoningSteps: ({ context, event }) => [
                  ...context.reasoningSteps,
                  createReasoningStep(
                    context.reasoningSteps.length + 1,
                    'planning',
                    `理解查询: ${(event.output as any).normalizedQuery}`,
                    undefined,
                    `意图: ${(event.output as any).intent}`
                  )
                ]
              })]
            },
            onError: {
              target: 'failed',
              actions: assign({ error: ({ event }) => toError(event.error) })
            }
          },
          on: { CANCEL: 'cancelled' }
        },

        planning: {
          entry: ({ context }) => {
            emitEvent(this.eventEmitter, context.sessionId, 'state_change', { to: 'planning' })
          },
          invoke: {
            src: 'planRetrieval',
            input: ({ context }) => context,
            onDone: {
              target: 'retrieving',
              actions: ['assignStrategy', 'incrementIterations']
            },
            onError: {
              target: 'failed',
              actions: assign({ error: ({ event }) => toError(event.error) })
            }
          },
          on: { CANCEL: 'cancelled' }
        },

        retrieving: {
          entry: ({ context }) => {
            emitEvent(this.eventEmitter, context.sessionId, 'state_change', { to: 'retrieving' })
          },
          invoke: {
            src: 'executeRetrieval',
            input: ({ context }) => context,
            onDone: {
              target: 'reasoning',
              actions: ['assignRetrievalResults']
            },
            onError: {
              target: 'failed',
              actions: assign({ error: ({ event }) => toError(event.error) })
            }
          },
          on: { CANCEL: 'cancelled' }
        },

        reasoning: {
          entry: ({ context }) => {
            emitEvent(this.eventEmitter, context.sessionId, 'state_change', { to: 'reasoning' })
          },
          invoke: {
            src: 'reasonAboutResults',
            input: ({ context }) => context,
            onDone: {
              target: 'generating',
              actions: ['addReasoningStep']
            },
            onError: {
              target: 'failed',
              actions: assign({ error: ({ event }) => toError(event.error) })
            }
          },
          on: { CANCEL: 'cancelled' }
        },

        generating: {
          entry: ({ context }) => {
            emitEvent(this.eventEmitter, context.sessionId, 'state_change', { to: 'generating' })
          },
          invoke: {
            src: 'generateResponse',
            input: ({ context }) => context,
            onDone: {
              target: 'evaluating',
              actions: ['assignGeneration']
            },
            onError: {
              target: 'failed',
              actions: assign({ error: ({ event }) => toError(event.error) })
            }
          },
          on: { CANCEL: 'cancelled' }
        },

        evaluating: {
          entry: ({ context }) => {
            emitEvent(this.eventEmitter, context.sessionId, 'state_change', { to: 'evaluating' })
          },
          invoke: {
            src: 'evaluateResponse',
            input: ({ context }) => context,
            onDone: [
              {
                guard: ({ context }) => context.evaluation?.passed ?? false,
                target: 'completed',
                actions: 'assignEvaluation'
              },
              {
                guard: ({ context }) => {
                  if (!context.evaluation) return true
                  return !context.evaluation.passed && context.iterations < context.maxIterations
                },
                target: 'planning',
                actions: ['assignEvaluation', 'incrementDepth']
              },
              {
                target: 'completed',
                actions: 'assignEvaluation'
              }
            ],
            onError: {
              target: 'failed',
              actions: assign({ error: ({ event }) => toError(event.error) })
            }
          },
          on: { CANCEL: 'cancelled' }
        },

        completed: {
          type: 'final',
          entry: ({ context }) => {
            emitEvent(this.eventEmitter, context.sessionId, 'state_change', { to: 'completed' })
          }
        },

        failed: {
          entry: ({ context }) => {
            emitEvent(this.eventEmitter, context.sessionId, 'error', {
              error: context.error?.message,
              state: context.currentDepth > 0 ? 'failed' : 'unknown'
            })
          }
        },

        cancelled: {
          type: 'final'
        }
      }
    })
  }

  start(query: string, threadId?: string): void {
    this.actor.start()
    this.actor.send({ type: 'START', query, threadId })
  }

  send(event: RAGEvent): void {
    this.actor.send(event)
  }

  stop(): void {
    this.actor.stop()
  }

  getSnapshot(): { value: string; context: RAGContext } {
    return {
      value: String(this.actor.getSnapshot().value),
      context: this.actor.getSnapshot().context as RAGContext
    }
  }

  getResult(): RAGResult {
    const { context } = this.getSnapshot()
    const toolsUsed = Array.from(context.toolResults.keys())

    const sourceCounts: Record<string, number> = {}
    for (const chunk of context.retrievedChunks) {
      const db = (chunk as any).database || 'unknown'
      sourceCounts[db] = (sourceCounts[db] || 0) + 1
    }

    return {
      success: context.error === undefined,
      response: context.response,
      citations: context.citations,
      confidence: context.confidence,
      evaluation: context.evaluation,
      error: context.error?.message,
      metadata: {
        totalLatencyMs: context.updatedAt - context.createdAt,
        iterations: context.iterations,
        toolsUsed,
        retrievalStats: {
          totalChunks: context.retrievedChunks.length,
          sources: sourceCounts
        }
      }
    }
  }

  onEvent(callback: (event: { sessionId: string; eventType: string; data: Record<string, unknown>; timestamp: number }) => void): void {
    this.eventEmitter.on('rag-event', callback)
  }

  subscribe(callback: (state: { value: string; context: RAGContext }) => void): () => void {
    const subscription = this.actor.subscribe((state) => {
      callback({
        value: String(state.value),
        context: state.context as RAGContext
      })
    })
    return () => subscription.unsubscribe()
  }
}

export function createRAGMachine(config?: RAGMachineConfig): RAGStateMachine {
  return new RAGStateMachine(config)
}

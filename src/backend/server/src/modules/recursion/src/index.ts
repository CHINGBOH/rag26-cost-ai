/**
 * 递归模块 - 基于 XState v5 的递归查询处理
 * 提供管道式递归流程编排
 */

import {
  RecursionSession,
  RecursionRound,
  RecursionMetrics,
  SubQuery,
  RetrievedChunk,
  RoundEvaluation,
  ExpertDecision,
  Anomaly
} from '../../common/types'
import { EventBus } from '../../common/event-bus'
import { z } from 'zod'

// XState v5 导入
import {
  createMachine,
  createActor,
  fromPromise,
  assign,
  setup,
  ActorLogic
} from 'xstate'

// ==================== Schema 定义 ====================

export const RecursionConfigSchema = z.object({
  maxDepth: z.number().default(3),
  minConfidence: z.number().default(0.85),
  maxIterations: z.number().default(10),
  timeout: z.number().default(30000)
})

export type RecursionConfig = z.infer<typeof RecursionConfigSchema>

// ==================== 类型定义 ====================

export interface RecursionContext {
  session: RecursionSession
  query: string
  currentRound: number
  eventBus?: EventBus
}

export interface RecursionRoundResult {
  round: RecursionRound
  shouldContinue: boolean
  reason: string
}

export interface RecursionResult {
  session: RecursionSession
  finalAnswer: string
  rounds: RecursionRound[]
  completed: boolean
}

// ==================== 状态机事件类型 ====================

export type RecursionEvent =
  | { type: 'START'; query: string }
  | { type: 'DECOMPOSE' }
  | { type: 'RETRIEVE' }
  | { type: 'EVALUATE' }
  | { type: 'JUDGE' }
  | { type: 'GENERATE' }
  | { type: 'COMPLETE' }
  | { type: 'FAILED'; error: string }
  | { type: 'HUMAN_REVIEW'; approved: boolean }

// ==================== 默认配置 ====================

const defaultConfig: RecursionConfig = {
  maxDepth: 3,
  minConfidence: 0.85,
  maxIterations: 10,
  timeout: 30000
}

// ==================== XState v5 机器设置 ====================

const recursionMachineSetup = setup({
  types: {
    context: {} as RecursionContext,
    events: {} as RecursionEvent
  },
  actors: {
    decomposeQuery: fromPromise(async ({ input }: { input: { query: string } }) => {
      // 查询分解逻辑
      const subQueries: SubQuery[] = []
      subQueries.push({
        id: `sq_${Date.now()}_1`,
        query: `${input.query} 基础概念`,
        targetDB: 'vector',
        status: 'pending'
      })
      subQueries.push({
        id: `sq_${Date.now()}_2`,
        query: `${input.query} 实现方法`,
        targetDB: 'vector',
        status: 'pending'
      })
      return subQueries
    }),
    
    retrieveChunks: fromPromise(async ({ input }: { input: { query: string; subQueries: SubQuery[] } }) => {
      // 检索逻辑 - 返回模拟数据
      const chunks: RetrievedChunk[] = input.subQueries.map((sq, idx) => ({
        id: `chunk_${idx}_${Date.now()}`,
        content: `检索结果: ${sq.query}`,
        source: 'mock-source',
        database: sq.targetDB,
        score: 0.8 - idx * 0.1,
        metadata: {}
      }))
      return chunks
    }),
    
    evaluateRound: fromPromise(async ({ input }: { input: { query: string; chunks: RetrievedChunk[] } }) => {
      // 评估逻辑
      const avgScore = input.chunks.reduce((sum, c) => sum + c.score, 0) / input.chunks.length
      const evaluation: RoundEvaluation = {
        completeness: Math.min(avgScore * 1.2, 0.95),
        consistency: 0.8,
        confidence: avgScore,
        informationGain: 0.5,
        sourceDiversity: input.chunks.length > 1 ? 0.7 : 0.3,
        factConsistency: 0.85,
        coverageEstimate: Math.min(avgScore * 1.5, 0.95)
      }
      return evaluation
    }),
    
    expertJudgment: fromPromise(async ({ input }: { input: { evaluation: RoundEvaluation; depth: number } }) => {
      // 专家判断逻辑
      const decision: ExpertDecision = {
        shouldContinue: input.evaluation.confidence < 0.85 && input.depth < 3,
        confidence: input.evaluation.confidence,
        reason: input.evaluation.confidence < 0.85 ? '置信度不足' : '质量满足要求',
        nextAction: input.evaluation.confidence < 0.85 ? 'continue' : 'stop'
      }
      return decision
    })
  }
})

// ==================== 创建递归状态机 ====================

export function createRecursionMachine(config?: Partial<RecursionConfig>) {
  const cfg = { ...defaultConfig, ...config }

  return recursionMachineSetup.createMachine({
    id: 'recursion',
    initial: 'idle',
    context: {
      session: null as unknown as RecursionSession,
      query: '',
      currentRound: 0,
      eventBus: undefined
    },
    states: {
      idle: {
        on: {
          START: {
            target: 'decomposing',
            actions: assign({
              query: ({ event }) => event.query,
              session: ({ event }) => createSession(event.query, cfg),
              currentRound: 0
            })
          }
        }
      },
      
      decomposing: {
        invoke: {
          src: 'decomposeQuery',
          input: ({ context }) => ({ query: context.query }),
          onDone: {
            target: 'retrieving',
            actions: assign({
              session: ({ context, event }) => ({
                ...context.session,
                currentState: 'decomposing'
              })
            })
          },
          onError: {
            target: 'failed',
            actions: assign({
              session: ({ context }) => ({
                ...context.session,
                currentState: 'failed'
              })
            })
          }
        }
      },
      
      retrieving: {
        invoke: {
          src: 'retrieveChunks',
          input: ({ context }) => ({ 
            query: context.query, 
            subQueries: context.session.rounds[context.session.rounds.length - 1]?.subQueries || [] 
          }),
          onDone: {
            target: 'evaluating',
            actions: assign({
              session: ({ context, event }) => ({
                ...context.session,
                currentState: 'retrieving'
              })
            })
          },
          onError: {
            target: 'failed'
          }
        }
      },
      
      evaluating: {
        invoke: {
          src: 'evaluateRound',
          input: ({ context }) => ({
            query: context.query,
            chunks: context.session.rounds[context.session.rounds.length - 1]?.retrievedChunks || []
          }),
          onDone: {
            target: 'judging',
            actions: assign({
              session: ({ context, event }) => ({
                ...context.session,
                currentState: 'evaluating'
              })
            })
          },
          onError: {
            target: 'failed'
          }
        }
      },
      
      judging: {
        invoke: {
          src: 'expertJudgment',
          input: ({ context }) => ({
            evaluation: context.session.rounds[context.session.rounds.length - 1]?.evaluation || {
              completeness: 0, consistency: 0, confidence: 0, informationGain: 0, sourceDiversity: 0, factConsistency: 0, coverageEstimate: 0
            },
            depth: context.currentRound
          }),
          onDone: [
            {
              guard: ({ event }) => event.output.shouldContinue && event.output.nextAction === 'continue',
              target: 'retrieving',
              actions: assign({
                currentRound: ({ context }) => context.currentRound + 1,
                session: ({ context }) => ({
                  ...context.session,
                  currentState: 'judging'
                })
              })
            },
            {
              target: 'generating',
              actions: assign({
                session: ({ context }) => ({
                  ...context.session,
                  currentState: 'judging'
                })
              })
            }
          ],
          onError: {
            target: 'failed'
          }
        }
      },
      
      generating: {
        entry: assign({
          session: ({ context }) => ({
            ...context.session,
            currentState: 'generating'
          })
        }),
        after: {
          100: {
            target: 'completed'
          }
        }
      },
      
      completed: {
        type: 'final',
        entry: assign({
          session: ({ context }) => ({
            ...context.session,
            currentState: 'completed',
            updatedAt: Date.now()
          })
        })
      },
      
      failed: {
        type: 'final',
        entry: assign({
          session: ({ context }) => ({
            ...context.session,
            currentState: 'failed',
            updatedAt: Date.now()
          })
        })
      }
    }
  })
}

// ==================== 工厂函数 ====================

export function createRecursionFlow(config?: Partial<RecursionConfig>) {
  const cfg = RecursionConfigSchema.parse({ ...defaultConfig, ...config })
  const machine = createRecursionMachine(cfg)

  return async function startRecursion(
    input: { query: string; eventBus?: EventBus }
  ): Promise<RecursionResult> {
    const { query, eventBus } = input

    // 创建 actor
    const actor = createActor(machine)
    
    // 启动 actor
    actor.start()
    
    // 发送启动事件
    actor.send({ type: 'START', query })

    // 等待状态机完成
    return new Promise((resolve) => {
      const subscription = actor.subscribe((state) => {
        if (state.matches('completed') || state.matches('failed')) {
          subscription.unsubscribe()
          
          const context = actor.getSnapshot().context
          resolve({
            session: context.session,
            finalAnswer: '', // 实际应从生成步骤获取
            rounds: context.session.rounds,
            completed: state.matches('completed')
          })
        }
      })

      // 超时处理
      setTimeout(() => {
        subscription.unsubscribe()
        actor.stop()
        resolve({
          session: actor.getSnapshot().context.session,
          finalAnswer: '',
          rounds: actor.getSnapshot().context.session.rounds,
          completed: false
        })
      }, cfg.timeout)
    })
  }
}

// ==================== 会话管理 ====================

export function createSession(query: string, config?: Partial<RecursionConfig>): RecursionSession {
  const id = `rec_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  const now = Date.now()

  return {
    id,
    originalQuery: query,
    createdAt: now,
    updatedAt: now,
    currentState: 'idle',
    currentDepth: 0,
    rounds: [],
    metrics: {
      totalChunksRetrieved: 0,
      averageConfidence: 0,
      maxDepthReached: 0,
      totalLatency: 0
    },
    anomalies: []
  }
}

export function createRound(
  sessionId: string,
  depth: number,
  subQueries: SubQuery[],
  chunks: RetrievedChunk[]
): RecursionRound {
  return {
    id: `round_${sessionId}_${depth}_${Date.now()}`,
    sessionId,
    depth,
    subQueries,
    retrievedChunks: chunks,
    evaluation: {
      completeness: 0,
      consistency: 0,
      confidence: 0,
      informationGain: 0,
      sourceDiversity: 0,
      factConsistency: 0,
      coverageEstimate: 0
    },
    expertDecision: {
      shouldContinue: false,
      confidence: 0,
      reason: ''
    },
    timestamp: Date.now()
  }
}

// ==================== 专家判断 ====================

export function expertJudgment(config?: { minConfidence?: number }) {
  const minConfidence = config?.minConfidence ?? 0.85

  return async function judge(
    context: RecursionContext
  ): Promise<ExpertDecision> {
    const { session } = context
    const lastRound = session.rounds[session.rounds.length - 1]

    if (!lastRound) {
      return {
        shouldContinue: true,
        confidence: 0.5,
        reason: '首次检索，需要更多信息',
        nextAction: 'continue'
      }
    }

    const { evaluation } = lastRound
    const shouldContinue =
      evaluation.confidence < minConfidence &&
      context.currentRound < 3

    return {
      shouldContinue,
      confidence: evaluation.confidence,
      reason: shouldContinue
        ? '置信度不足，需要继续检索'
        : '检索质量满足要求',
      nextAction: shouldContinue ? 'continue' : 'stop'
    }
  }
}

// ==================== 评估 ====================

export function evaluateRound() {
  return function evaluate(context: RecursionContext): RoundEvaluation {
    const { session, currentRound } = context
    const lastRound = session.rounds[session.rounds.length - 1]

    if (!lastRound) {
      return {
        completeness: 0,
        consistency: 0,
        confidence: 0.5,
        informationGain: 0.5,
        sourceDiversity: 0,
        factConsistency: 0,
        coverageEstimate: 0
      }
    }

    const chunks = lastRound.retrievedChunks

    const avgScore = chunks.length > 0
      ? chunks.reduce((sum: number, c: RetrievedChunk) => sum + c.score, 0) / chunks.length
      : 0

    const sources = new Set(chunks.map((c: RetrievedChunk) => c.source))
    const sourceDiversity = Math.min(sources.size / 3, 1.0)

    const databases = new Set(chunks.map((c: RetrievedChunk) => c.database))
    const dbDiversity = databases.size / 4
    const diversity = (sourceDiversity + dbDiversity) / 2

    const informationGain = Math.max(0.1, 0.5 - currentRound * 0.1)
    const totalContentLength = chunks.reduce((sum: number, c: RetrievedChunk) => sum + c.content.length, 0)
    const completeness = Math.min(totalContentLength / 2000, 0.95)

    const variance = chunks.length > 0
      ? chunks.reduce((sum: number, c: RetrievedChunk) => sum + Math.pow(c.score - avgScore, 2), 0) / chunks.length
      : 0
    const consistency = Math.max(0.5, 1 - variance)

    return {
      completeness,
      consistency,
      confidence: (completeness + consistency + diversity) / 3,
      informationGain,
      sourceDiversity: diversity,
      factConsistency: consistency,
      coverageEstimate: Math.min(avgScore * diversity * 1.5, 0.95)
    }
  }
}

// ==================== 会话存储 ====================

const sessions: Map<string, RecursionSession> = new Map()

export function saveSession(session: RecursionSession): void {
  sessions.set(session.id, session)
}

export function getSession(id: string): RecursionSession | undefined {
  return sessions.get(id)
}

export function getAllSessions(): RecursionSession[] {
  return Array.from(sessions.values())
}

export function deleteSession(id: string): boolean {
  return sessions.delete(id)
}

export function cleanupSessions(maxAge: number = 24 * 60 * 60 * 1000): number {
  const now = Date.now()
  let cleaned = 0

  for (const [id, session] of sessions) {
    if (now - session.updatedAt > maxAge) {
      sessions.delete(id)
      cleaned++
    }
  }

  return cleaned
}

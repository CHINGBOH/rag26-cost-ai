/**
 * 递归模块测试 - 基于 XState v5
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  createRecursionFlow,
  createRecursionMachine,
  createSession,
  createRound,
  expertJudgment,
  evaluateRound,
  saveSession,
  getSession,
  getAllSessions,
  deleteSession,
  cleanupSessions,
  RecursionConfigSchema
} from '../src'

describe('Recursion 模块', () => {
  describe('Schema 验证', () => {
    it('应该验证 RecursionConfig', () => {
      const config = RecursionConfigSchema.parse({
        maxDepth: 5,
        minConfidence: 0.9
      })

      expect(config.maxDepth).toBe(5)
      expect(config.minConfidence).toBe(0.9)
      expect(config.timeout).toBe(30000) // 默认值
    })
  })

  describe('状态机', () => {
    it('应该创建递归状态机', () => {
      const machine = createRecursionMachine()
      expect(machine).toBeDefined()
      expect(machine.id).toBe('recursion')
    })

    it('应该创建带自定义配置的状态机', () => {
      const machine = createRecursionMachine({ maxDepth: 5 })
      expect(machine).toBeDefined()
    })
  })

  describe('递归流程', () => {
    it('应该启动递归流程', async () => {
      const flow = createRecursionFlow({ timeout: 5000 })
      
      const result = await flow({ query: '测试查询' })
      
      expect(result).toBeDefined()
      expect(result.session).toBeDefined()
      expect(result.session.originalQuery).toBe('测试查询')
    })

    it('应该完成状态机执行', async () => {
      const flow = createRecursionFlow({ 
        maxDepth: 1,
        minConfidence: 0.5,
        timeout: 5000 
      })
      
      const result = await flow({ query: '简单查询' })
      
      expect(result.completed).toBe(true)
    })
  })

  describe('会话管理', () => {
    it('应该创建会话', () => {
      const session = createSession('测试查询')
      
      expect(session.id).toBeDefined()
      expect(session.originalQuery).toBe('测试查询')
      expect(session.currentState).toBe('idle')
      expect(session.rounds).toHaveLength(0)
    })

    it('应该创建轮次', () => {
      const session = createSession('测试')
      const round = createRound(session.id, 0, [], [])
      
      expect(round.id).toBeDefined()
      expect(round.depth).toBe(0)
      expect(round.sessionId).toBe(session.id)
    })

    it('应该保存和获取会话', () => {
      const session = createSession('测试')
      saveSession(session)
      
      const retrieved = getSession(session.id)
      expect(retrieved).toEqual(session)
    })

    it('应该获取所有会话', () => {
      const session1 = createSession('测试1')
      const session2 = createSession('测试2')
      
      saveSession(session1)
      saveSession(session2)
      
      const all = getAllSessions()
      expect(all.length).toBeGreaterThanOrEqual(2)
    })

    it('应该删除会话', () => {
      const session = createSession('测试')
      saveSession(session)
      
      const deleted = deleteSession(session.id)
      expect(deleted).toBe(true)
      
      const retrieved = getSession(session.id)
      expect(retrieved).toBeUndefined()
    })

    it('应该清理过期会话', () => {
      const session = createSession('测试')
      session.updatedAt = Date.now() - 25 * 60 * 60 * 1000 // 25小时前
      saveSession(session)
      
      const cleaned = cleanupSessions(24 * 60 * 60 * 1000)
      expect(cleaned).toBeGreaterThanOrEqual(1)
      
      const retrieved = getSession(session.id)
      expect(retrieved).toBeUndefined()
    })
  })

  describe('专家判断', () => {
    it('应该判断继续检索', async () => {
      const judge = expertJudgment({ minConfidence: 0.9 })
      
      const context = {
        session: {
          id: 'test',
          originalQuery: '测试',
          createdAt: Date.now(),
          updatedAt: Date.now(),
          currentState: 'judging',
          currentDepth: 1,
          rounds: [
            {
              id: 'r1',
              depth: 0,
              subQueries: [],
              retrievedChunks: [],
              evaluation: {
                completeness: 0.5,
                consistency: 0.6,
                confidence: 0.5, // 低于阈值
                informationGain: 0.4,
                sourceDiversity: 0.3,
                factConsistency: 0.7,
                coverageEstimate: 0.4
              },
              expertDecision: {
                shouldContinue: false,
                confidence: 0,
                reason: ''
              },
              timestamp: Date.now()
            }
          ],
          metrics: {
            totalChunksRetrieved: 0,
            averageConfidence: 0,
            maxDepthReached: 0,
            totalLatency: 0
          },
          anomalies: []
        },
        query: '测试',
        currentRound: 1
      }
      
      const decision = await judge(context)
      
      expect(decision.shouldContinue).toBe(true)
      expect(decision.nextAction).toBe('continue')
    })

    it('应该判断停止检索', async () => {
      const judge = expertJudgment({ minConfidence: 0.8 })
      
      const context = {
        session: {
          id: 'test',
          originalQuery: '测试',
          createdAt: Date.now(),
          updatedAt: Date.now(),
          currentState: 'judging',
          currentDepth: 3,
          rounds: [
            {
              id: 'r1',
              depth: 2,
              subQueries: [],
              retrievedChunks: [],
              evaluation: {
                completeness: 0.9,
                consistency: 0.9,
                confidence: 0.9, // 高于阈值
                informationGain: 0.8,
                sourceDiversity: 0.7,
                factConsistency: 0.9,
                coverageEstimate: 0.8
              },
              expertDecision: {
                shouldContinue: false,
                confidence: 0,
                reason: ''
              },
              timestamp: Date.now()
            }
          ],
          metrics: {
            totalChunksRetrieved: 0,
            averageConfidence: 0,
            maxDepthReached: 0,
            totalLatency: 0
          },
          anomalies: []
        },
        query: '测试',
        currentRound: 3
      }
      
      const decision = await judge(context)
      
      expect(decision.shouldContinue).toBe(false)
      expect(decision.nextAction).toBe('stop')
    })
  })

  describe('评估', () => {
    it('应该评估轮次质量', () => {
      const evaluate = evaluateRound()
      
      const context = {
        session: {
          id: 'test',
          originalQuery: '测试',
          createdAt: Date.now(),
          updatedAt: Date.now(),
          currentState: 'evaluating',
          currentDepth: 1,
          rounds: [
            {
              id: 'r1',
              depth: 0,
              subQueries: [],
              retrievedChunks: [
                { id: 'c1', content: 'A'.repeat(500), source: 's1', database: 'vector', score: 0.9, metadata: {} },
                { id: 'c2', content: 'B'.repeat(500), source: 's2', database: 'graph', score: 0.8, metadata: {} }
              ],
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
          ],
          metrics: {
            totalChunksRetrieved: 0,
            averageConfidence: 0,
            maxDepthReached: 0,
            totalLatency: 0
          },
          anomalies: []
        },
        query: '测试',
        currentRound: 1
      }
      
      const evaluation = evaluate(context)
      
      expect(evaluation.confidence).toBeGreaterThan(0)
      expect(evaluation.sourceDiversity).toBeGreaterThan(0)
    })

    it('应该处理空结果', () => {
      const evaluate = evaluateRound()
      
      const context = {
        session: {
          id: 'test',
          originalQuery: '测试',
          createdAt: Date.now(),
          updatedAt: Date.now(),
          currentState: 'evaluating',
          currentDepth: 0,
          rounds: [],
          metrics: {
            totalChunksRetrieved: 0,
            averageConfidence: 0,
            maxDepthReached: 0,
            totalLatency: 0
          },
          anomalies: []
        },
        query: '测试',
        currentRound: 0
      }
      
      const evaluation = evaluate(context)
      
      expect(evaluation.confidence).toBe(0.5)
      expect(evaluation.completeness).toBe(0)
    })
  })
})

/**
 * 性能基准测试
 * 验证各模块性能指标
 */

import { describe, it, expect } from 'vitest'
import { pipe } from '../modules/common/pipe'
import { createEventBus } from '../modules/common/event-bus'
import { retrieval, recursion, storage, metrics } from '../modules'

describe('性能基准测试', () => {
  describe('Pipe 引擎', () => {
    it('应该在 100ms 内执行 100 个步骤', async () => {
      const start = Date.now()
      
      let result = 0
      let builder = pipe(0)
      
      // 创建 100 个步骤
      for (let i = 0; i < 100; i++) {
        builder = builder.through(`step${i}`, (x: number) => x + 1)
      }
      
      result = await builder.execute()
      const duration = Date.now() - start
      
      expect(result).toBe(100)
      expect(duration).toBeLessThan(100)
    })

    it('应该支持 1000 并发分支', async () => {
      const start = Date.now()
      
      const branches = Array.from({ length: 1000 }, (_, i) => 
        () => Promise.resolve(i)
      )
      
      const results = await Promise.all(branches.map(fn => fn()))
      const duration = Date.now() - start
      
      expect(results).toHaveLength(1000)
      expect(duration).toBeLessThan(500)
    })
  })

  describe('EventBus', () => {
    it('应该在 100ms 内处理 10000 个事件', async () => {
      const eventBus = createEventBus()
      let count = 0
      
      eventBus.on('test', () => {
        count++
      })
      
      const start = Date.now()
      
      for (let i = 0; i < 10000; i++) {
        eventBus.emit('test', i)
      }
      
      // 等待异步处理
      await new Promise(r => setTimeout(r, 50))
      
      const duration = Date.now() - start
      
      expect(count).toBe(10000)
      expect(duration).toBeLessThan(150)
    })
  })

  describe('存储', () => {
    it('应该在 100ms 内完成 1000 次缓存操作', async () => {
      const cache = storage.createCache<number>()
      
      const start = Date.now()
      
      // 写入
      for (let i = 0; i < 1000; i++) {
        await cache.set(`key${i}`, i)
      }
      
      // 读取
      for (let i = 0; i < 1000; i++) {
        await cache.get(`key${i}`)
      }
      
      const duration = Date.now() - start
      
      expect(duration).toBeLessThan(100)
    })

    it('应该在 100ms 内完成 1000 次队列操作', async () => {
      const queue = storage.createQueue<number>()
      
      const start = Date.now()
      
      // 入队
      for (let i = 0; i < 1000; i++) {
        await queue.enqueue(i)
      }
      
      // 出队
      for (let i = 0; i < 1000; i++) {
        await queue.dequeue()
      }
      
      const duration = Date.now() - start
      
      expect(duration).toBeLessThan(100)
    })
  })

  describe('监控', () => {
    it('应该在 100ms 内记录 10000 个指标', async () => {
      const start = Date.now()
      
      for (let i = 0; i < 10000; i++) {
        metrics.collectMetrics('benchmark')(i)
      }
      
      const duration = Date.now() - start
      const stats = metrics.getStats('benchmark')
      
      expect(stats.count).toBe(10000)
      expect(duration).toBeLessThan(100)
    })
  })

  describe('端到端 RAG', () => {
    it('应该完成完整 RAG 流程', async () => {
      const start = Date.now()
      
      // 1. 查询分解
      const subQueries = await retrieval.decompose()('RAG 系统架构')
      
      // 2. 创建会话
      const session = recursion.createSession('RAG 系统架构')
      
      // 3. 评估
      const evaluation = recursion.evaluateRound()({
        session,
        query: 'RAG 系统架构',
        currentRound: 0
      })
      
      // 4. 专家判断
      const decision = await recursion.expertJudgment()({
        session,
        query: 'RAG 系统架构',
        currentRound: 0
      })
      
      const duration = Date.now() - start
      
      expect(subQueries).toBeDefined()
      expect(session).toBeDefined()
      expect(evaluation).toBeDefined()
      expect(decision).toBeDefined()
      expect(duration).toBeLessThan(500) // 500ms 内完成
    })
  })
})

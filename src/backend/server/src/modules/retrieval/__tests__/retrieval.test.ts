/**
 * 检索模块测试 - 基于 LangChain
 */

import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest'
import { Document } from '@langchain/core/documents'
import { 
  decompose,
  vectorSearch,
  graphSearch,
  retrieve,
  rerank,
  fuseScores,
  evaluate,
  healthCheck,
  createRetrievalPipeline,
  createTextSplitter,
  RetrievalConfigSchema,
  SearchOptionsSchema,
  FusionWeightsSchema,
  indexDocuments
} from '../src'

describe('Retrieval 模块', () => {
  describe('Schema 验证', () => {
    it('应该验证 RetrievalConfig', () => {
      const config = RetrievalConfigSchema.parse({
        qdrantUrl: 'http://localhost:6333',
        neo4jUrl: 'bolt://localhost:7687'
      })

      expect(config.qdrantUrl).toBe('http://localhost:6333')
      expect(config.timeout).toBe(30000) // 默认值
    })

    it('应该验证 SearchOptions', () => {
      const options = SearchOptionsSchema.parse({
        topK: 20,
        enableRerank: false
      })

      expect(options.topK).toBe(20)
      expect(options.enableRerank).toBe(false)
      expect(options.vectorWeight).toBe(0.6) // 默认值
    })

    it('应该验证 FusionWeights', () => {
      const weights = FusionWeightsSchema.parse({
        vector: 0.5
      })

      expect(weights.vector).toBe(0.5)
      expect(weights.rerank).toBe(0.4) // 默认值
    })
  })

  describe('查询分解', () => {
    it('应该分解基础查询', async () => {
      const decomposeFn = decompose()
      const subQueries = await decomposeFn('什么是RAG')

      expect(subQueries).toHaveLength(2)
      expect(subQueries[0].targetDB).toBe('vector')
      expect(subQueries[1].targetDB).toBe('vector') // 第二个也是vector
    })

    it('应该为案例类查询添加图谱查询', async () => {
      const decomposeFn = decompose()
      const subQueries = await decomposeFn('如何使用RAG的案例')

      expect(subQueries.length).toBeGreaterThanOrEqual(3)
      expect(subQueries.some(q => q.targetDB === 'graph')).toBe(true)
    })
  })

  describe('分数融合', () => {
    it('应该融合多路召回结果', () => {
      const chunks1 = [
        { id: '1', content: 'A', source: 'src1', database: 'vector' as const, score: 0.9, metadata: {} },
        { id: '2', content: 'B', source: 'src1', database: 'vector' as const, score: 0.8, metadata: {} }
      ]

      const chunks2 = [
        { id: '2', content: 'B', source: 'src2', database: 'graph' as const, score: 0.85, metadata: {} },
        { id: '3', content: 'C', source: 'src2', database: 'graph' as const, score: 0.75, metadata: {} }
      ]

      const merge = fuseScores()
      const result = merge([chunks1, chunks2])

      expect(result.length).toBe(3)
      expect(result[0].id).toBe('2') // B 出现在两个结果中，应该排名最高
      expect(result[0].score).toBeGreaterThan(result[1].score)
    })

    it('应该应用自定义权重', () => {
      const chunks = [
        [{ id: '1', content: 'A', source: 'src1', database: 'vector' as const, score: 0.9, metadata: {} }],
        [{ id: '2', content: 'B', source: 'src2', database: 'graph' as const, score: 0.9, metadata: {} }]
      ]

      const merge = fuseScores({ vector: 0.8, graph: 0.2 })
      const result = merge(chunks)

      // 向量结果的权重更高，所以应该排在前面
      expect(result[0].score).toBeGreaterThan(result[1].score)
    })
  })

  describe('评估', () => {
    it('应该评估检索质量', () => {
      const chunks = [
        { id: '1', content: 'A'.repeat(500), source: 'src1', database: 'vector' as const, score: 0.9, metadata: {} },
        { id: '2', content: 'B'.repeat(500), source: 'src2', database: 'keyword' as const, score: 0.8, metadata: {} }
      ]

      const evalFn = evaluate()
      const result = evalFn('查询', chunks)

      expect(result.completeness).toBeGreaterThan(0)
      expect(result.completeness).toBeLessThanOrEqual(1)
      expect(result.sourceDiversity).toBeGreaterThan(0)
      expect(result.confidence).toBeGreaterThan(0)
    })

    it('应该处理空结果', () => {
      const evalFn = evaluate()
      const result = evalFn('查询', [])

      expect(result.completeness).toBe(0)
      expect(result.confidence).toBe(0)
    })
  })

  describe('重排序', () => {
    it('应该按分数排序', async () => {
      const rerankFn = rerank({ topK: 3 })
      const chunks = [
        { id: '1', content: 'C', source: 'src1', database: 'vector' as const, score: 0.5, metadata: {} },
        { id: '2', content: 'A', source: 'src1', database: 'vector' as const, score: 0.9, metadata: {} },
        { id: '3', content: 'B', source: 'src1', database: 'vector' as const, score: 0.7, metadata: {} }
      ]

      const result = await rerankFn('查询', chunks)

      expect(result).toHaveLength(3)
      expect(result[0].id).toBe('2') // 分数最高
      expect(result[1].id).toBe('3')
      expect(result[2].id).toBe('1')
    })

    it('应该限制返回数量', async () => {
      const rerankFn = rerank({ topK: 2 })
      const chunks = [
        { id: '1', content: 'A', source: 'src1', database: 'vector' as const, score: 0.9, metadata: {} },
        { id: '2', content: 'B', source: 'src1', database: 'vector' as const, score: 0.8, metadata: {} },
        { id: '3', content: 'C', source: 'src1', database: 'vector' as const, score: 0.7, metadata: {} }
      ]

      const result = await rerankFn('查询', chunks)

      expect(result).toHaveLength(2)
    })
  })

  describe('管道工厂', () => {
    it('应该创建完整的检索管道', () => {
      const pipeline = createRetrievalPipeline({
        topK: 20,
        vectorWeight: 0.5
      })

      expect(pipeline.decompose).toBeDefined()
      expect(pipeline.vectorSearch).toBeDefined()
      expect(pipeline.graphSearch).toBeDefined()
      expect(pipeline.retrieve).toBeDefined()
      expect(pipeline.rerank).toBeDefined()
      expect(pipeline.evaluate).toBeDefined()
      expect(pipeline.fuseScores).toBeDefined()
      expect(pipeline.healthCheck).toBeDefined()
      expect(pipeline.indexDocuments).toBeDefined()
    })
  })

  describe('健康检查', () => {
    it('应该返回服务状态', async () => {
      // Mock fetch for Qdrant
      global.fetch = vi.fn().mockImplementation((url: string) => {
        if (url.includes('6333')) {
          return Promise.resolve({ ok: true })
        }
        return Promise.resolve({ ok: false })
      })

      const health = await healthCheck()

      expect(health.healthy).toBeDefined()
      expect(health.services).toHaveProperty('qdrant')
      expect(health.services).toHaveProperty('neo4j')
    })
  })
})

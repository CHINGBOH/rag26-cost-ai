/**
 * 工具封装层测试 - 验证 API 调用和管道联用
 */

import { describe, it, expect, vi, beforeAll } from 'vitest'
import {
  createPipeline,
  pdfOCR,
  imageOCR,
  extractText,
  chunkText,
  createEmbedding,
  batchEmbed,
  storeVectors,
  processDocument,
  tools
} from '../index'

describe('工具封装层', () => {
  describe('管道基础', () => {
    it('应该创建管道并执行', async () => {
      const result = await createPipeline('hello')
        .pipe(async (input) => ({
          data: input.toUpperCase(),
          context: { sessionId: 'test', timestamp: Date.now(), metadata: {} },
          duration: 0
        }))
        .execute()
      
      expect(result.data).toBe('HELLO')
    })

    it('应该串联多个工具', async () => {
      const result = await createPipeline(5)
        .pipe(async (n) => ({ data: n * 2, context: { sessionId: 'test', timestamp: Date.now(), metadata: {} }, duration: 0 }))
        .pipe(async (n) => ({ data: n + 1, context: { sessionId: 'test', timestamp: Date.now(), metadata: {} }, duration: 0 }))
        .pipe(async (n) => ({ data: String(n), context: { sessionId: 'test', timestamp: Date.now(), metadata: {} }, duration: 0 }))
        .execute()
      
      expect(result.data).toBe('11') // (5 * 2) + 1 = 11
    })
  })

  describe('OCR 工具', () => {
    it('pdfOCR 应该返回工具函数', () => {
      const ocr = pdfOCR()
      expect(typeof ocr).toBe('function')
    })

    it('imageOCR 应该返回工具函数', () => {
      const ocr = imageOCR()
      expect(typeof ocr).toBe('function')
    })
  })

  describe('文本处理工具', () => {
    it('应该提取 OCR 文档中的文本', async () => {
      const mockDoc = {
        docId: 'test',
        filename: 'test.pdf',
        totalPages: 2,
        pages: [
          {
            pageNum: 1,
            textBlocks: [
              { text: '第一页第一段', confidence: 0.9, bbox: [0, 0, 100, 50] as [number, number, number, number] },
              { text: '第一页第二段', confidence: 0.85, bbox: [0, 50, 100, 100] as [number, number, number, number] }
            ]
          },
          {
            pageNum: 2,
            textBlocks: [
              { text: '第二页内容', confidence: 0.92, bbox: [0, 0, 100, 50] as [number, number, number, number] }
            ]
          }
        ],
        processingTime: 1000
      }
      
      const result = await extractText()(mockDoc as any)
      
      expect(result.data).toContain('第一页第一段')
      expect(result.data).toContain('第二页内容')
      expect(result.context.metadata.totalPages).toBe(2)
    })

    it('应该将文本分块', async () => {
      const longText = '第一段内容。\n\n第二段内容。\n\n第三段更长一些的内容。'
      
      const result = await chunkText({ chunkSize: 100, minChunkSize: 10 })(longText)
      
      expect(result.data.length).toBeGreaterThan(0)
      expect(result.data[0]).toHaveProperty('id')
      expect(result.data[0]).toHaveProperty('content')
    })
  })

  describe('向量工具', () => {
    it('应该生成嵌入向量', async () => {
      const result = await createEmbedding({ dimensions: 128 })('测试文本')
      
      expect(result.data).toHaveLength(128)
      expect(result.context.metadata.textLength).toBe(4)
      
      // 检查归一化
      const norm = Math.sqrt(result.data.reduce((sum, v) => sum + v * v, 0))
      expect(Math.abs(norm - 1.0)).toBeLessThan(0.01)
    })

    it('应该批量嵌入', async () => {
      const chunks = [
        { id: '1', content: '文本一', pageNum: 1, metadata: {} },
        { id: '2', content: '文本二', pageNum: 1, metadata: {} }
      ]
      
      const result = await batchEmbed({ dimensions: 64 })(chunks)
      
      expect(result.data).toHaveLength(2)
      expect(result.data[0].vector).toHaveLength(64)
    })
  })

  describe('存储工具', () => {
    it('应该存储向量', async () => {
      const docs = [
        { id: '1', vector: [0.1, 0.2, 0.3], metadata: { content: '测试' } }
      ]
      
      const result = await storeVectors()(docs)
      
      expect(result.data).toBe(true)
    })
  })

  describe('工具集合', () => {
    it('应该导出所有工具', () => {
      expect(tools.pdfOCR).toBeDefined()
      expect(tools.imageOCR).toBeDefined()
      expect(tools.extractText).toBeDefined()
      expect(tools.chunkText).toBeDefined()
      expect(tools.createEmbedding).toBeDefined()
      expect(tools.batchEmbed).toBeDefined()
      expect(tools.storeVectors).toBeDefined()
      expect(tools.processDocument).toBeDefined()
      expect(tools.createPipeline).toBeDefined()
    })
  })

  describe('完整工作流模拟', () => {
    it('应该执行完整流程', async () => {
      // 使用模拟数据测试流程
      const mockOCR = () => async () => ({
        data: {
          docId: 'test',
          filename: 'test.pdf',
          totalPages: 1,
          pages: [{
            pageNum: 1,
            textBlocks: [{ text: '测试内容', confidence: 0.95, bbox: [0, 0, 100, 50] as [number, number, number, number] }]
          }],
          processingTime: 1000
        },
        context: { sessionId: 'test', timestamp: Date.now(), metadata: {} },
        duration: 1000
      })
      
      const result = await createPipeline('/path/to/test.pdf')
        .pipe(mockOCR())
        .pipe(extractText())
        .pipe(chunkText())
        .execute()
      
      expect(result.data).toBeDefined()
    })
  })
})

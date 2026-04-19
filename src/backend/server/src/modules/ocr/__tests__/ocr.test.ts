/**
 * OCR 模块测试
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  parsePDF,
  parsePDFFromPath,
  ocrImage,
  ocrPDF,
  extractText,
  extractTextBlocks,
  chunkDocument,
  chunkFromBlocks,
  processDocument,
  createOCRPipeline,
  healthCheck
} from '../src'

describe('OCR 模块', () => {
  describe('文本提取', () => {
    it('应该从解析页面提取文本', () => {
      const pages = [
        { pageNum: 1, width: 612, height: 792, content: '第一页内容', textBlocks: [] },
        { pageNum: 2, width: 612, height: 792, content: '第二页内容', textBlocks: [] }
      ]

      const text = extractText()(pages)

      expect(text).toContain('第一页内容')
      expect(text).toContain('第二页内容')
    })

    it('应该提取文本块', () => {
      const pages = [
        {
          pageNum: 1,
          width: 612,
          height: 792,
          content: '内容',
          textBlocks: [
            { id: '1', text: '块1', confidence: 0.9, bbox: [10, 10, 100, 50] as [number, number, number, number], type: 'text' as const },
            { id: '2', text: '块2', confidence: 0.85, bbox: [10, 60, 100, 100] as [number, number, number, number], type: 'text' as const }
          ]
        }
      ]

      const blocks = extractTextBlocks()(pages)

      expect(blocks).toHaveLength(2)
      expect(blocks[0].text).toBe('块1')
    })
  })

  describe('文档分块', () => {
    it('应该按大小分块文本', () => {
      // 使用带标点的长文本
      const longText = '第一句话的内容。第二句话的内容。第三句话的内容。'.repeat(50)

      const chunkFn = chunkDocument({ chunkSize: 500, minChunkSize: 50 })
      const chunks = chunkFn(longText, 'test.pdf')

      expect(chunks.length).toBeGreaterThan(0)
      // 验证分块逻辑正常工作
      expect(chunks[0].content).toContain('。')
    })

    it('应该从文本块分块', () => {
      const blocks = [
        { id: '1', text: '第一块文本', confidence: 0.9, bbox: [0, 0, 100, 50] as [number, number, number, number], type: 'text' as const },
        { id: '2', text: '第二块文本', confidence: 0.85, bbox: [0, 50, 100, 100] as [number, number, number, number], type: 'text' as const }
      ]

      const chunkFn = chunkFromBlocks({ chunkSize: 500 })
      const chunks = chunkFn(blocks, 'test.pdf')

      expect(chunks).toHaveLength(2)
      expect(chunks[0].content).toBe('第一块文本')
    })
  })

  describe('管道工厂', () => {
    it('应该创建 OCR 管道', () => {
      const pipeline = createOCRPipeline({
        language: 'ch',
        chunkSize: 512
      })

      expect(pipeline.parsePDF).toBeDefined()
      expect(pipeline.ocrImage).toBeDefined()
      expect(pipeline.ocrPDF).toBeDefined()
      expect(pipeline.extractText).toBeDefined()
      expect(pipeline.chunkDocument).toBeDefined()
    })
  })

  describe('健康检查', () => {
    it('应该检查 OCR 服务状态', async () => {
      // Mock fetch with json() method
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: 'healthy', version: '1.0.0' })
      })

      const health = await healthCheck()

      expect(health.healthy).toBe(true)
      expect(health.version).toBe('1.0.0')
    })

    it('应该处理服务不可用', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Connection failed'))

      const health = await healthCheck()

      expect(health.healthy).toBe(false)
    })
  })
})

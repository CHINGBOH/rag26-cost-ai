/**
 * 表格提取器测试 - 使用真实 OCR 数据
 */

import { describe, it, expect } from 'vitest'
import {
  extractTableFromOCR,
  extractTablesFromPages,
  tableToMarkdown,
  tableToHTML,
  tableToJSON,
  OCRTextBlock
} from '../table-extractor'

// 第 10 页真实 OCR 数据（简化版）
const page10Blocks: OCRTextBlock[] = [
  // 标题行
  { text: '政策法规', confidence: 0.99, bbox: { x: 1997, y: 90, width: 187, height: 67 } },
  { text: '深圳建设工程价格信息SZCOST', confidence: 0.98, bbox: { x: 3798, y: 81, width: 629, height: 61 } },
  
  // 表格标题
  { text: '附录B住宅、公寓-模块化建筑工程（±0.00以上部分）工期表', confidence: 0.99, bbox: { x: 2592, y: 607, width: 1638, height: 71 } },
  
  // 表头行
  { text: '编号', confidence: 0.99, bbox: { x: 370, y: 650, width: 144, height: 71 } },
  { text: '层 数/层', confidence: 0.92, bbox: { x: 661, y: 650, width: 205, height: 71 } },
  { text: '建筑面积/m²', confidence: 0.94, bbox: { x: 960, y: 650, width: 269, height: 66 } },
  { text: '模块化建筑等级', confidence: 0.99, bbox: { x: 1267, y: 650, width: 375, height: 66 } },
  { text: '工期 (d)', confidence: 0.96, bbox: { x: 1695, y: 650, width: 230, height: 66 } },
  
  // 数据行1
  { text: 'MiC-A1-025', confidence: 0.99, bbox: { x: 302, y: 740, width: 274, height: 66 } },
  { text: '★', confidence: 0.99, bbox: { x: 661, y: 740, width: 100, height: 66 } },
  { text: '183', confidence: 0.99, bbox: { x: 960, y: 740, width: 100, height: 66 } },
  { text: '★', confidence: 0.99, bbox: { x: 1267, y: 740, width: 100, height: 66 } },
  { text: '146', confidence: 0.99, bbox: { x: 1695, y: 740, width: 100, height: 66 } },
  
  // 数据行2
  { text: 'MiC-A1-026', confidence: 0.99, bbox: { x: 302, y: 830, width: 274, height: 66 } },
  { text: '★★', confidence: 0.99, bbox: { x: 661, y: 830, width: 100, height: 66 } },
  { text: '158', confidence: 0.99, bbox: { x: 960, y: 830, width: 100, height: 66 } },
]

describe('表格提取器', () => {
  describe('extractTableFromOCR', () => {
    it('应该从真实 OCR 数据中识别表格', () => {
      const table = extractTableFromOCR(page10Blocks)
      
      expect(table).not.toBeNull()
      expect(table!.rowCount).toBeGreaterThan(0)
      expect(table!.colCount).toBeGreaterThan(0)
    })

    it('应该识别表头', () => {
      const table = extractTableFromOCR(page10Blocks)
      
      expect(table).not.toBeNull()
      expect(table!.headers).toBeDefined()
      expect(table!.headers!.length).toBeGreaterThan(0)
    })

    it('应该返回 null 当数据不足以构成表格', () => {
      const result = extractTableFromOCR([
        { text: '单行文本', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } }
      ])
      
      expect(result).toBeNull()
    })
  })

  describe('tableToMarkdown', () => {
    it('应该生成 Markdown 表格', () => {
      const table = extractTableFromOCR(page10Blocks)
      expect(table).not.toBeNull()
      
      const md = tableToMarkdown(table!)
      
      expect(md).toContain('|')
      expect(md).toContain('---')
      expect(md.length).toBeGreaterThan(0)
    })
  })

  describe('tableToHTML', () => {
    it('应该生成 HTML 表格', () => {
      const table = extractTableFromOCR(page10Blocks)
      expect(table).not.toBeNull()
      
      const html = tableToHTML(table!)
      
      expect(html).toContain('<table>')
      expect(html).toContain('</table>')
      expect(html).toContain('<tr>')
    })
  })

  describe('tableToJSON', () => {
    it('应该生成结构化 JSON', () => {
      const table = extractTableFromOCR(page10Blocks)
      expect(table).not.toBeNull()
      
      const json = tableToJSON(table!)
      
      expect(json).toHaveProperty('id')
      expect(json).toHaveProperty('rowCount')
      expect(json).toHaveProperty('colCount')
      expect(json).toHaveProperty('headers')
      expect(json).toHaveProperty('data')
    })
  })

  describe('extractTablesFromPages', () => {
    it('应该处理多页数据', () => {
      const pages = [
        {
          pageNumber: 1,
          textBlocks: page10Blocks
        },
        {
          pageNumber: 2,
          textBlocks: [
            { text: 'A', confidence: 0.99, bbox: { x: 100, y: 100, width: 50, height: 30 } },
            { text: 'B', confidence: 0.99, bbox: { x: 160, y: 100, width: 50, height: 30 } },
            { text: 'C', confidence: 0.99, bbox: { x: 100, y: 140, width: 50, height: 30 } },
            { text: 'D', confidence: 0.99, bbox: { x: 160, y: 140, width: 50, height: 30 } },
          ]
        }
      ]
      
      const results = extractTablesFromPages(pages)
      
      expect(results.length).toBeGreaterThan(0)
      expect(results[0]).toHaveProperty('pageNumber')
      expect(results[0]).toHaveProperty('table')
    })
  })
})

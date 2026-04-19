/**
 * 表格检测器测试
 */

import { describe, it, expect } from 'vitest'
import {
  detectTables,
  tableToMarkdown,
  tableToHTML,
  tableToJSON,
  TextBlock,
  Table
} from '../table-detector'

describe('表格检测器', () => {
  // 模拟第10页的文本块数据
  const mockPage10Blocks: TextBlock[] = [
    // 标题行
    { text: '政策法规', confidence: 0.99, bbox: { x: 1997, y: 90, width: 187, height: 67 } },
    { text: '深圳建设工程价格信息SZCOST', confidence: 0.98, bbox: { x: 3798, y: 81, width: 629, height: 61 } },
    { text: '政策法规', confidence: 0.99, bbox: { x: 2353, y: 95, width: 187, height: 66 } },
    
    // 表格标题
    { text: '附录B住宅、公寓-模块化建筑工程（±0.00以上部分）工期表', confidence: 0.99, bbox: { x: 2592, y: 607, width: 1638, height: 71 } },
    
    // 表头行
    { text: '编号', confidence: 0.99, bbox: { x: 370, y: 650, width: 144, height: 71 } },
    { text: '层 数/层', confidence: 0.92, bbox: { x: 661, y: 639, width: 205, height: 83 } },
    { text: '建筑面积/m²', confidence: 0.94, bbox: { x: 960, y: 650, width: 269, height: 66 } },
    { text: '模块化建筑等级', confidence: 0.99, bbox: { x: 1267, y: 655, width: 375, height: 66 } },
    { text: '工期 (d)', confidence: 0.96, bbox: { x: 1695, y: 655, width: 230, height: 66 } },
    
    // 数据行1
    { text: 'MiC-A1-025', confidence: 0.99, bbox: { x: 302, y: 740, width: 274, height: 66 } },
    { text: '000S>', confidence: 0.99, bbox: { x: 302, y: 740, width: 150, height: 66 } }, // 行号列
    { text: '★', confidence: 0.99, bbox: { x: 661, y: 740, width: 205, height: 66 } },
    { text: '146', confidence: 0.99, bbox: { x: 1695, y: 740, width: 230, height: 66 } },
    
    // 数据行2
    { text: 'MiC-A2-001', confidence: 0.99, bbox: { x: 302, y: 830, width: 274, height: 66 } },
    { text: '104', confidence: 0.99, bbox: { x: 1695, y: 830, width: 230, height: 66 } },
  ]

  describe('detectTables', () => {
    it('应该检测页面中的表格', () => {
      const result = detectTables(mockPage10Blocks)
      
      expect(result.tables).toBeDefined()
      expect(result.tables.length).toBeGreaterThan(0)
    })

    it('应该识别表格的行列结构', () => {
      // 使用更清晰的表格数据测试
      const simpleTable: TextBlock[] = [
        // 表头
        { text: '姓名', confidence: 0.99, bbox: { x: 100, y: 100, width: 100, height: 30 } },
        { text: '年龄', confidence: 0.99, bbox: { x: 220, y: 100, width: 100, height: 30 } },
        { text: '城市', confidence: 0.99, bbox: { x: 340, y: 100, width: 100, height: 30 } },
        
        // 数据行1
        { text: '张三', confidence: 0.99, bbox: { x: 100, y: 140, width: 100, height: 30 } },
        { text: '25', confidence: 0.99, bbox: { x: 220, y: 140, width: 100, height: 30 } },
        { text: '北京', confidence: 0.99, bbox: { x: 340, y: 140, width: 100, height: 30 } },
        
        // 数据行2
        { text: '李四', confidence: 0.99, bbox: { x: 100, y: 180, width: 100, height: 30 } },
        { text: '30', confidence: 0.99, bbox: { x: 220, y: 180, width: 100, height: 30 } },
        { text: '上海', confidence: 0.99, bbox: { x: 340, y: 180, width: 100, height: 30 } },
      ]
      
      const result = detectTables(simpleTable)
      
      expect(result.tables.length).toBe(1)
      expect(result.tables[0].rowCount).toBe(3)  // 表头 + 2行数据
      expect(result.tables[0].colCount).toBe(3)  // 3列
      expect(result.tables[0].cells.length).toBe(9)  // 9个单元格
    })

    it('应该识别非表格文本块', () => {
      const mixedBlocks: TextBlock[] = [
        // 非表格文本 (Y坐标与表格差距大，超过阈值100)
        { text: '这是一个标题', confidence: 0.99, bbox: { x: 100, y: 10, width: 200, height: 30 } },
        
        // 表格
        { text: 'A', confidence: 0.99, bbox: { x: 100, y: 150, width: 50, height: 30 } },
        { text: 'B', confidence: 0.99, bbox: { x: 160, y: 150, width: 50, height: 30 } },
        { text: 'C', confidence: 0.99, bbox: { x: 100, y: 190, width: 50, height: 30 } },
        { text: 'D', confidence: 0.99, bbox: { x: 160, y: 190, width: 50, height: 30 } },
      ]
      
      const result = detectTables(mixedBlocks)
      
      expect(result.tables.length).toBe(1)
      expect(result.textBlocks.length).toBe(1)
      expect(result.textBlocks[0].text).toBe('这是一个标题')
    })
  })

  describe('tableToMarkdown', () => {
    it('应该将表格转换为 Markdown 格式', () => {
      const table: Table = {
        id: 'test',
        rowCount: 3,
        colCount: 3,
        cells: [
          { row: 0, col: 0, text: '姓名', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } },
          { row: 0, col: 1, text: '年龄', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } },
          { row: 0, col: 2, text: '城市', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } },
          { row: 1, col: 0, text: '张三', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } },
          { row: 1, col: 1, text: '25', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } },
          { row: 1, col: 2, text: '北京', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } },
          { row: 2, col: 0, text: '李四', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } },
          { row: 2, col: 1, text: '30', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } },
          { row: 2, col: 2, text: '上海', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } },
        ],
        headers: ['姓名', '年龄', '城市'],
        bbox: { x: 0, y: 0, width: 300, height: 90 }
      }
      
      const markdown = tableToMarkdown(table)
      
      expect(markdown).toContain('| 姓名 | 年龄 | 城市 |')
      expect(markdown).toContain('| --- | --- | --- |')
      expect(markdown).toContain('| 张三 | 25 | 北京 |')
      expect(markdown).toContain('| 李四 | 30 | 上海 |')
    })
  })

  describe('tableToHTML', () => {
    it('应该将表格转换为 HTML 格式', () => {
      const table: Table = {
        id: 'test',
        rowCount: 2,
        colCount: 2,
        cells: [
          { row: 0, col: 0, text: 'Header1', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } },
          { row: 0, col: 1, text: 'Header2', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } },
          { row: 1, col: 0, text: 'Data1', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } },
          { row: 1, col: 1, text: 'Data2', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } },
        ],
        bbox: { x: 0, y: 0, width: 200, height: 60 }
      }
      
      const html = tableToHTML(table)
      
      expect(html).toContain('<table>')
      expect(html).toContain('</table>')
      expect(html).toContain('<th>Header1</th>')
      expect(html).toContain('<th>Header2</th>')
      expect(html).toContain('<td>Data1</td>')
      expect(html).toContain('<td>Data2</td>')
    })
  })

  describe('tableToJSON', () => {
    it('应该将表格转换为 JSON 格式', () => {
      const table: Table = {
        id: 'test',
        rowCount: 3,
        colCount: 3,
        cells: [
          { row: 0, col: 0, text: '姓名', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } },
          { row: 0, col: 1, text: '年龄', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } },
          { row: 1, col: 0, text: '张三', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } },
          { row: 1, col: 1, text: '25', confidence: 0.99, bbox: { x: 0, y: 0, width: 100, height: 30 } },
        ],
        headers: ['姓名', '年龄'],
        bbox: { x: 0, y: 0, width: 200, height: 60 }
      }
      
      const json = tableToJSON(table)
      
      expect(json).toHaveProperty('id')
      expect(json).toHaveProperty('headers')
      expect(json).toHaveProperty('rowCount')
      expect(json).toHaveProperty('colCount')
      expect(json).toHaveProperty('rows')
    })
  })
})

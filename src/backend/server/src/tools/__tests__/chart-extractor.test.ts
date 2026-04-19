/**
 * 图表数据提取器测试 - 使用第18页真实数据
 */

import { describe, it, expect } from 'vitest'
import {
  extractChartFromOCR,
  extractChartFromTable,
  generateChartSummary,
  generateEChartsOption
} from '../chart-extractor'

// 模拟第18页部分OCR数据
const mockPage18Blocks = [
  // 标题
  { text: '建安、市政工程造价指数', confidence: 0.99, bbox: { x: 802, y: 413, width: 300, height: 40 } },
  
  // 类别 + 数值
  { text: '多层住宅', confidence: 0.99, bbox: { x: 326, y: 584, width: 100, height: 30 } },
  { text: '194.93', confidence: 0.99, bbox: { x: 720, y: 593, width: 60, height: 25 } },
  { text: '191.81', confidence: 0.99, bbox: { x: 800, y: 593, width: 60, height: 25 } },
  { text: '190.64', confidence: 0.99, bbox: { x: 880, y: 593, width: 60, height: 25 } },
  { text: '189.39', confidence: 0.99, bbox: { x: 960, y: 593, width: 60, height: 25 } },
  
  // 另一类别
  { text: '多层写字楼', confidence: 0.99, bbox: { x: 326, y: 650, width: 100, height: 30 } },
  { text: '172.58', confidence: 0.99, bbox: { x: 720, y: 660, width: 60, height: 25 } },
  { text: '171.05', confidence: 0.99, bbox: { x: 800, y: 660, width: 60, height: 25 } },
  { text: '170.95', confidence: 0.99, bbox: { x: 880, y: 660, width: 60, height: 25 } },
]

// 表格格式数据
const mockTableData = [
  { '月份': '1月', '多层住宅': '194.93', '多层写字楼': '172.58' },
  { '月份': '2月', '多层住宅': '191.81', '多层写字楼': '171.05' },
  { '月份': '3月', '多层住宅': '190.64', '多层写字楼': '170.95' },
  { '月份': '4月', '多层住宅': '189.39', '多层写字楼': '169.84' },
]

describe('图表提取器', () => {
  describe('extractChartFromOCR', () => {
    it('应该从OCR文本块中提取图表数据', () => {
      const chart = extractChartFromOCR(mockPage18Blocks)
      
      expect(chart).not.toBeNull()
      expect(chart!.series.length).toBeGreaterThan(0)
    })

    it('应该识别数据系列名称', () => {
      const chart = extractChartFromOCR(mockPage18Blocks)
      
      expect(chart).not.toBeNull()
      const seriesNames = chart!.series.map(s => s.name)
      // 算法可能识别到标题或类别名作为系列名
      expect(seriesNames.length).toBeGreaterThan(0)
      expect(seriesNames.some(name => 
        name.includes('建安') || name.includes('住宅') || name.includes('写字楼')
      )).toBe(true)
    })

    it('应该计算趋势统计', () => {
      const chart = extractChartFromOCR(mockPage18Blocks)
      
      expect(chart).not.toBeNull()
      const series = chart!.series[0]
      expect(series.statistics).toBeDefined()
      expect(series.statistics.min).toBeDefined()
      expect(series.statistics.max).toBeDefined()
      expect(series.statistics.trend).toBeDefined()
    })
  })

  describe('extractChartFromTable', () => {
    it('应该从表格数据中提取图表', () => {
      const chart = extractChartFromTable(mockTableData)
      
      expect(chart).not.toBeNull()
      expect(chart!.series.length).toBe(2) // 两个数值列
    })

    it('应该识别月份作为X轴', () => {
      const chart = extractChartFromTable(mockTableData)
      
      expect(chart).not.toBeNull()
      const firstSeries = chart!.series[0]
      expect(firstSeries.data[0].label).toBe('1月')
      expect(firstSeries.data.length).toBe(4)
    })
  })

  describe('generateChartSummary', () => {
    it('应该生成图表摘要', () => {
      const chart = extractChartFromTable(mockTableData)
      expect(chart).not.toBeNull()
      
      const summary = generateChartSummary(chart!)
      
      expect(summary).toContain('多层住宅')
      expect(summary).toContain('趋势')
      expect(summary).toContain('数值范围')
    })
  })

  describe('generateEChartsOption', () => {
    it('应该生成ECharts配置', () => {
      const chart = extractChartFromTable(mockTableData)
      expect(chart).not.toBeNull()
      
      const option = generateEChartsOption(chart!)
      
      expect(option).toHaveProperty('title')
      expect(option).toHaveProperty('xAxis')
      expect(option).toHaveProperty('yAxis')
      expect(option).toHaveProperty('series')
      expect(option).toHaveProperty('legend')
    })
  })
})

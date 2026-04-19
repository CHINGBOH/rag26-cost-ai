/**
 * 完整演示测试 - 第10页表格 + 第18页图表提取
 */

import { describe, it, expect } from 'vitest'
import { extractTableFromOCR, tableToMarkdown, tableToHTML, tableToJSON } from '../table-extractor'
import { extractChartFromOCR, generateChartSummary, generateEChartsOption } from '../chart-extractor'

// 第 10 页真实 OCR 数据（模块化建筑工程工期表）
const page10Blocks = [
  { text: '附录B住宅、公寓-模块化建筑工程（±0.00以上部分）工期表', confidence: 0.99, bbox: { x: 2592, y: 607, width: 1638, height: 71 } },
  { text: '编号', confidence: 0.99, bbox: { x: 370, y: 650, width: 144, height: 71 } },
  { text: '层 数/层', confidence: 0.92, bbox: { x: 661, y: 650, width: 205, height: 71 } },
  { text: '建筑面积/m²', confidence: 0.94, bbox: { x: 960, y: 650, width: 269, height: 66 } },
  { text: '模块化建筑等级', confidence: 0.99, bbox: { x: 1267, y: 650, width: 375, height: 66 } },
  { text: '工期 (d)', confidence: 0.96, bbox: { x: 1695, y: 650, width: 230, height: 66 } },
  { text: 'MiC-A1-025', confidence: 0.99, bbox: { x: 302, y: 740, width: 274, height: 66 } },
  { text: '★', confidence: 0.99, bbox: { x: 661, y: 740, width: 100, height: 66 } },
  { text: '183', confidence: 0.99, bbox: { x: 960, y: 740, width: 100, height: 66 } },
  { text: '★', confidence: 0.99, bbox: { x: 1267, y: 740, width: 100, height: 66 } },
  { text: '146', confidence: 0.99, bbox: { x: 1695, y: 740, width: 100, height: 66 } },
  { text: 'MiC-A1-026', confidence: 0.99, bbox: { x: 302, y: 830, width: 274, height: 66 } },
  { text: '★★', confidence: 0.99, bbox: { x: 661, y: 830, width: 100, height: 66 } },
  { text: '158', confidence: 0.99, bbox: { x: 960, y: 830, width: 100, height: 66 } },
  { text: '★★', confidence: 0.99, bbox: { x: 1267, y: 830, width: 100, height: 66 } },
  { text: '125', confidence: 0.99, bbox: { x: 1695, y: 830, width: 100, height: 66 } },
  { text: 'MiC-A1-027', confidence: 0.99, bbox: { x: 302, y: 920, width: 274, height: 66 } },
  { text: '★★★', confidence: 0.99, bbox: { x: 661, y: 920, width: 100, height: 66 } },
  { text: '134', confidence: 0.99, bbox: { x: 960, y: 920, width: 100, height: 66 } },
  { text: '★★★', confidence: 0.99, bbox: { x: 1267, y: 920, width: 100, height: 66 } },
  { text: '107', confidence: 0.99, bbox: { x: 1695, y: 920, width: 100, height: 66 } },
]

// 第 18 页真实 OCR 数据（价格指数走势图）
const page18Blocks = [
  { text: '建安、市政工程造价指数', confidence: 0.99, bbox: { x: 802, y: 413, width: 300, height: 40 } },
  { text: '多层住宅', confidence: 0.99, bbox: { x: 326, y: 584, width: 100, height: 30 } },
  { text: '194.93', confidence: 0.99, bbox: { x: 720, y: 593, width: 60, height: 25 } },
  { text: '191.81', confidence: 0.99, bbox: { x: 800, y: 593, width: 60, height: 25 } },
  { text: '190.64', confidence: 0.99, bbox: { x: 880, y: 593, width: 60, height: 25 } },
  { text: '189.39', confidence: 0.99, bbox: { x: 960, y: 593, width: 60, height: 25 } },
  { text: '187.44', confidence: 0.99, bbox: { x: 1040, y: 593, width: 60, height: 25 } },
  { text: '186.04', confidence: 0.99, bbox: { x: 1120, y: 593, width: 60, height: 25 } },
  { text: '182.37', confidence: 0.99, bbox: { x: 1200, y: 593, width: 60, height: 25 } },
  { text: '多层写字楼', confidence: 0.99, bbox: { x: 326, y: 650, width: 100, height: 30 } },
  { text: '172.58', confidence: 0.99, bbox: { x: 720, y: 660, width: 60, height: 25 } },
  { text: '171.05', confidence: 0.99, bbox: { x: 800, y: 660, width: 60, height: 25 } },
  { text: '170.95', confidence: 0.99, bbox: { x: 880, y: 660, width: 60, height: 25 } },
  { text: '169.84', confidence: 0.99, bbox: { x: 960, y: 660, width: 60, height: 25 } },
  { text: '168.79', confidence: 0.99, bbox: { x: 1040, y: 660, width: 60, height: 25 } },
  { text: '168.21', confidence: 0.99, bbox: { x: 1120, y: 660, width: 60, height: 25 } },
  { text: '167.21', confidence: 0.99, bbox: { x: 1200, y: 660, width: 60, height: 25 } },
  { text: '市政工程材料费', confidence: 0.99, bbox: { x: 326, y: 720, width: 120, height: 30 } },
  { text: '127.43', confidence: 0.99, bbox: { x: 720, y: 730, width: 60, height: 25 } },
  { text: '127.42', confidence: 0.99, bbox: { x: 800, y: 730, width: 60, height: 25 } },
  { text: '125.39', confidence: 0.99, bbox: { x: 880, y: 730, width: 60, height: 25 } },
  { text: '124.37', confidence: 0.99, bbox: { x: 960, y: 730, width: 60, height: 25 } },
  { text: '123.80', confidence: 0.99, bbox: { x: 1040, y: 730, width: 60, height: 25 } },
  { text: '122.00', confidence: 0.99, bbox: { x: 1120, y: 730, width: 60, height: 25 } },
  { text: '119.02', confidence: 0.99, bbox: { x: 1200, y: 730, width: 60, height: 25 } },
]

describe('完整演示 - 第10页表格提取', () => {
  const table = extractTableFromOCR(page10Blocks)

  it('应该成功提取表格', () => {
    console.log('\n' + '='.repeat(80))
    console.log('第 10 页 - 模块化建筑工程工期表')
    console.log('='.repeat(80))
    expect(table).not.toBeNull()
    console.log(`\n✓ 表格提取成功!`)
    console.log(`  行数: ${table!.rowCount}`)
    console.log(`  列数: ${table!.colCount}`)
    console.log(`  表头: ${table!.headers?.join(' | ')}`)
  })

  it('应该生成 Markdown', () => {
    const md = tableToMarkdown(table!)
    console.log('\n' + '-'.repeat(80))
    console.log('Markdown 格式:')
    console.log('-'.repeat(80))
    console.log(md)
    expect(md).toContain('|')
    expect(md).toContain('---')
  })

  it('应该生成 HTML', () => {
    const html = tableToHTML(table!)
    console.log('\n' + '-'.repeat(80))
    console.log('HTML 格式:')
    console.log('-'.repeat(80))
    console.log(html)
    expect(html).toContain('<table>')
    expect(html).toContain('</table>')
  })

  it('应该生成 JSON', () => {
    const json = tableToJSON(table!)
    console.log('\n' + '-'.repeat(80))
    console.log('JSON 结构化数据:')
    console.log('-'.repeat(80))
    console.log(JSON.stringify(json, null, 2))
    expect(json).toHaveProperty('id')
    expect(json).toHaveProperty('rowCount')
    expect(json).toHaveProperty('data')
  })
})

describe('完整演示 - 第18页图表提取', () => {
  const chart = extractChartFromOCR(page18Blocks)

  it('应该成功提取图表', () => {
    console.log('\n\n' + '='.repeat(80))
    console.log('第 18 页 - 价格指数走势图')
    console.log('='.repeat(80))
    expect(chart).not.toBeNull()
    console.log(`\n✓ 图表提取成功!`)
    console.log(`  图表类型: ${chart!.type}`)
    console.log(`  标题: ${chart!.title}`)
    console.log(`  数据系列数: ${chart!.series.length}`)
    
    chart!.series.forEach((s, i) => {
      console.log(`\n  系列 [${i+1}] ${s.name}:`)
      console.log(`    数据点: ${s.data.length}`)
      console.log(`    趋势: ${s.statistics.trend}`)
      console.log(`    变化: ${s.statistics.change > 0 ? '+' : ''}${s.statistics.change.toFixed(2)} (${s.statistics.changePercent > 0 ? '+' : ''}${s.statistics.changePercent.toFixed(1)}%)`)
    })
  })

  it('应该生成趋势摘要', () => {
    const summary = generateChartSummary(chart!)
    console.log('\n' + '-'.repeat(80))
    console.log('趋势分析摘要:')
    console.log('-'.repeat(80))
    console.log(summary)
    expect(summary).toContain('趋势')
    expect(summary).toContain('数值范围')
  })

  it('应该生成 ECharts 配置', () => {
    const option = generateEChartsOption(chart!)
    console.log('\n' + '-'.repeat(80))
    console.log('ECharts 配置:')
    console.log('-'.repeat(80))
    console.log(JSON.stringify(option, null, 2))
    expect(option).toHaveProperty('title')
    expect(option).toHaveProperty('xAxis')
    expect(option).toHaveProperty('series')
  })
})

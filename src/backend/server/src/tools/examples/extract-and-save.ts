/**
 * 示例：使用封装的工具提取表格/图表并保存到文件
 */

import * as fs from 'fs'
import * as path from 'path'
import { extractTableFromOCR, tableToMarkdown, tableToHTML, tableToJSON } from '../table-extractor'
import { extractChartFromOCR, generateChartSummary, generateEChartsOption } from '../chart-extractor'

// 示例 OCR 数据
const sampleOCRBlocks = [
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
]

async function main() {
  const outputDir = path.join(__dirname, '../../../output')
  
  // 确保输出目录存在
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true })
  }

  console.log('='.repeat(80))
  console.log('OCR 数据提取并保存示例')
  console.log('='.repeat(80))
  console.log(`输出目录: ${outputDir}`)
  console.log('')

  // 1. 提取表格
  console.log('1. 提取表格...')
  const table = extractTableFromOCR(sampleOCRBlocks)
  
  if (table) {
    // 保存 Markdown
    const mdPath = path.join(outputDir, 'table-output.md')
    fs.writeFileSync(mdPath, tableToMarkdown(table), 'utf-8')
    console.log(`   ✓ Markdown 已保存: ${mdPath}`)
    
    // 保存 HTML
    const htmlPath = path.join(outputDir, 'table-output.html')
    fs.writeFileSync(htmlPath, tableToHTML(table), 'utf-8')
    console.log(`   ✓ HTML 已保存: ${htmlPath}`)
    
    // 保存 JSON
    const jsonPath = path.join(outputDir, 'table-output.json')
    fs.writeFileSync(jsonPath, JSON.stringify(tableToJSON(table), null, 2), 'utf-8')
    console.log(`   ✓ JSON 已保存: ${jsonPath}`)
  }

  // 2. 提取图表
  console.log('\n2. 提取图表...')
  const chart = extractChartFromOCR(sampleOCRBlocks)
  
  if (chart) {
    // 保存趋势摘要
    const summaryPath = path.join(outputDir, 'chart-summary.md')
    fs.writeFileSync(summaryPath, generateChartSummary(chart), 'utf-8')
    console.log(`   ✓ 趋势摘要已保存: ${summaryPath}`)
    
    // 保存 ECharts 配置
    const echartsPath = path.join(outputDir, 'chart-echarts.json')
    fs.writeFileSync(echartsPath, JSON.stringify(generateEChartsOption(chart), null, 2), 'utf-8')
    console.log(`   ✓ ECharts 配置已保存: ${echartsPath}`)
  }

  console.log('\n' + '='.repeat(80))
  console.log('处理完成！输出文件列表：')
  console.log('='.repeat(80))
  
  const files = fs.readdirSync(outputDir)
  files.forEach(f => {
    const stats = fs.statSync(path.join(outputDir, f))
    console.log(`  - ${f} (${(stats.size / 1024).toFixed(1)} KB)`)
  })
}

main().catch(console.error)

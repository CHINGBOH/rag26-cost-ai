/**
 * 图表数据提取器 - 从 OCR 结果中提取图表/走势图数据
 */

export interface ChartDataPoint {
  label: string
  value: number
}

export interface ChartSeries {
  name: string
  data: ChartDataPoint[]
  statistics: {
    min: number
    max: number
    avg: number
    start: number
    end: number
    change: number
    changePercent: number
    trend: 'up' | 'down' | 'flat'
  }
}

export interface ExtractedChart {
  id: string
  type: 'line' | 'bar' | 'table'
  title?: string
  xAxisLabel?: string
  yAxisLabel?: string
  series: ChartSeries[]
  timeRange?: {
    start: string
    end: string
  }
}

export interface ChartExtractionConfig {
  // 数值提取正则
  numberPattern: RegExp
  // 最小数据点数
  minDataPoints: number
  // 趋势分类阈值 (%)
  trendThreshold: number
}

const defaultConfig: ChartExtractionConfig = {
  numberPattern: /\d+\.?\d*/g,
  minDataPoints: 3,
  trendThreshold: 1.0
}

/**
 * 从表格数据中提取图表/走势数据
 */
export function extractChartFromTable(
  tableData: Array<Record<string, string>>,
  config: Partial<ChartExtractionConfig> = {}
): ExtractedChart | null {
  const cfg = { ...defaultConfig, ...config }
  
  if (tableData.length < cfg.minDataPoints) {
    return null
  }
  
  const series: ChartSeries[] = []
  
  // 获取所有列名
  const columns = Object.keys(tableData[0] || {})
  
  // 识别时间列和数值列
  const timeColumn = columns.find(c => 
    /时间|月份|日期|期|月|年|month|date|time/i.test(c)
  )
  
  const valueColumns = columns.filter(c => c !== timeColumn)
  
  for (const colName of valueColumns) {
    const dataPoints: ChartDataPoint[] = []
    const values: number[] = []
    
    for (const row of tableData) {
      const label = timeColumn ? row[timeColumn] : String(dataPoints.length + 1)
      const valueText = row[colName]
      
      // 提取数字
      const nums = valueText?.match(cfg.numberPattern)
      if (nums && nums.length > 0) {
        const value = parseFloat(nums[0])
        if (!isNaN(value)) {
          dataPoints.push({ label, value })
          values.push(value)
        }
      }
    }
    
    if (values.length >= cfg.minDataPoints) {
      series.push(createSeries(colName, dataPoints, values))
    }
  }
  
  if (series.length === 0) {
    return null
  }
  
  return {
    id: `chart_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
    type: 'line',
    series,
    title: series.length > 0 ? `${series[0].name}走势` : undefined
  }
}

/**
 * 从 OCR 文本块直接提取图表数据
 */
export function extractChartFromOCR(
  textBlocks: Array<{
    text: string
    confidence: number
    bbox: { x: number; y: number; width: number; height: number }
  }>,
  config: Partial<ChartExtractionConfig> = {}
): ExtractedChart | null {
  const cfg = { ...defaultConfig, ...config }
  
  // 按Y坐标排序
  const sorted = [...textBlocks].sort((a, b) => a.bbox.y - b.bbox.y)
  
  // 按行分组
  const rows: Array<Array<typeof textBlocks[0]>> = []
  let currentRow: Array<typeof textBlocks[0]> = []
  let lastY = 0
  const rowThreshold = 50
  
  for (const block of sorted) {
    const centerY = block.bbox.y + block.bbox.height / 2
    
    if (currentRow.length === 0 || Math.abs(centerY - lastY) < rowThreshold) {
      currentRow.push(block)
      lastY = centerY
    } else {
      currentRow.sort((a, b) => a.bbox.x - b.bbox.x)
      rows.push(currentRow)
      currentRow = [block]
      lastY = centerY
    }
  }
  
  if (currentRow.length > 0) {
    currentRow.sort((a, b) => a.bbox.x - b.bbox.x)
    rows.push(currentRow)
  }
  
  // 识别类别行和数值行
  const series: ChartSeries[] = []
  let currentCategory: string | null = null
  
  for (const row of rows) {
    const texts = row.map(b => b.text)
    const fullText = texts.join(' ')
    
    // 检测类别名称
    if (/住宅|写字楼|市政|工程|建筑|材料费/.test(fullText) && !/\d{3,}/.test(fullText)) {
      currentCategory = texts[0]
    }
    
    // 提取数值
    if (currentCategory) {
      const nums = fullText.match(cfg.numberPattern)
      if (nums && nums.length >= cfg.minDataPoints) {
        const values = nums.map(n => parseFloat(n)).filter(n => !isNaN(n))
        
        if (values.length >= cfg.minDataPoints) {
          const dataPoints = values.map((v, i) => ({
            label: `${i + 1}月`,
            value: v
          }))
          
          series.push(createSeries(currentCategory, dataPoints, values))
          currentCategory = null
        }
      }
    }
  }
  
  if (series.length === 0) {
    return null
  }
  
  return {
    id: `chart_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
    type: 'line',
    series,
    title: series.length > 0 ? `${series[0].name}价格指数走势` : undefined,
    xAxisLabel: '月份',
    yAxisLabel: '价格指数'
  }
}

/**
 * 创建数据系列
 */
function createSeries(
  name: string,
  data: ChartDataPoint[],
  values: number[]
): ChartSeries {
  const min = Math.min(...values)
  const max = Math.max(...values)
  const avg = values.reduce((a, b) => a + b, 0) / values.length
  const start = values[0]
  const end = values[values.length - 1]
  const change = end - start
  const changePercent = start !== 0 ? (change / start) * 100 : 0
  
  let trend: 'up' | 'down' | 'flat' = 'flat'
  if (Math.abs(changePercent) > 1) {
    trend = changePercent > 0 ? 'up' : 'down'
  }
  
  return {
    name,
    data,
    statistics: {
      min,
      max,
      avg,
      start,
      end,
      change,
      changePercent,
      trend
    }
  }
}

/**
 * 生成图表数据摘要
 */
export function generateChartSummary(chart: ExtractedChart): string {
  const lines: string[] = []
  
  lines.push(`# ${chart.title || '图表分析'}`)
  lines.push('')
  
  for (const series of chart.series) {
    const s = series.statistics
    const trendIcon = s.trend === 'up' ? '📈' : s.trend === 'down' ? '📉' : '➡️'
    
    lines.push(`## ${series.name}`)
    lines.push(`- ${trendIcon} 趋势: ${s.trend === 'up' ? '上涨' : s.trend === 'down' ? '下跌' : '持平'}`)
    lines.push(`- 📊 数值范围: ${s.min.toFixed(2)} - ${s.max.toFixed(2)}`)
    lines.push(`- 📍 平均值: ${s.avg.toFixed(2)}`)
    lines.push(`- 📉 变化: ${s.change > 0 ? '+' : ''}${s.change.toFixed(2)} (${s.changePercent > 0 ? '+' : ''}${s.changePercent.toFixed(1)}%)`)
    lines.push(`- 📅 从 ${s.start.toFixed(2)} 到 ${s.end.toFixed(2)}`)
    lines.push('')
  }
  
  return lines.join('\n')
}

/**
 * 生成 ECharts 配置
 */
export function generateEChartsOption(chart: ExtractedChart): object {
  const xData = chart.series[0]?.data.map(d => d.label) || []
  
  return {
    title: {
      text: chart.title || '走势图',
      left: 'center'
    },
    tooltip: {
      trigger: 'axis'
    },
    legend: {
      data: chart.series.map(s => s.name),
      bottom: 0
    },
    xAxis: {
      type: 'category',
      data: xData,
      name: chart.xAxisLabel
    },
    yAxis: {
      type: 'value',
      name: chart.yAxisLabel
    },
    series: chart.series.map(s => ({
      name: s.name,
      type: 'line',
      data: s.data.map(d => d.value),
      smooth: true,
      markPoint: {
        data: [
          { type: 'max', name: '最大值' },
          { type: 'min', name: '最小值' }
        ]
      }
    }))
  }
}

export default {
  extractChartFromTable,
  extractChartFromOCR,
  generateChartSummary,
  generateEChartsOption
}

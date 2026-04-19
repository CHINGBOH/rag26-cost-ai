/**
 * 表格结构检测器 - 从OCR文本块中提取表格
 * 基于空间位置分析，识别行列结构
 */

export interface TextBlock {
  text: string
  confidence: number
  bbox: {
    x: number
    y: number
    width: number
    height: number
  }
}

export interface TableCell {
  row: number
  col: number
  text: string
  confidence: number
  bbox: {
    x: number
    y: number
    width: number
    height: number
  }
  merged?: boolean
  rowSpan?: number
  colSpan?: number
}

export interface Table {
  id: string
  rowCount: number
  colCount: number
  cells: TableCell[]
  headers?: string[]
  bbox: {
    x: number
    y: number
    width: number
    height: number
  }
}

export interface TableDetectionResult {
  tables: Table[]
  textBlocks: TextBlock[]  // 非表格文本块
}

// 表格检测配置
interface TableDetectorConfig {
  // 行分组阈值 - Y坐标差异小于此值视为同一行
  rowThreshold: number
  // 列分组阈值 - X坐标差异小于此值视为同一列
  colThreshold: number
  // 最小表格单元格数
  minCellCount: number
  // 表头行检测阈值 - 前N行
  headerRowCount: number
  // 合并单元格检测阈值
  mergeThreshold: number
}

const defaultConfig: TableDetectorConfig = {
  rowThreshold: 100,     // 100像素Y差异视为同一行（放宽）
  colThreshold: 150,   // 150像素X差异视为同一列（放宽）
  minCellCount: 4,     // 最少4个单元格才认为是表格
  headerRowCount: 1,   // 默认第1行是表头
  mergeThreshold: 2.0  // 单元格宽度超过平均宽度2倍视为合并
}

/**
 * 检测页面中的表格结构
 */
export function detectTables(
  textBlocks: TextBlock[],
  config: Partial<TableDetectorConfig> = {}
): TableDetectionResult {
  const cfg = { ...defaultConfig, ...config }
  
  if (textBlocks.length < cfg.minCellCount) {
    return { tables: [], textBlocks }
  }

  // 第1步：按Y坐标分组（识别行）
  const rows = groupByRow(textBlocks, cfg.rowThreshold)
  
  // 第2步：分析每行，识别表格结构
  const tableRegions = identifyTableRegions(rows, cfg.minCellCount)
  
  // 第3步：对每个表格区域进行列对齐
  const tables: Table[] = []
  const nonTableBlocks: TextBlock[] = []
  
  for (const region of tableRegions) {
    const table = buildTableStructure(region, cfg)
    if (table && table.cells.length >= cfg.minCellCount) {
      tables.push(table)
    } else {
      // 不是有效表格，归还文本块
      nonTableBlocks.push(...region.flat())
    }
  }
  
  // 收集非表格文本块
  const usedBlocks = new Set(tables.flatMap(t => t.cells.map(c => c.text)))
  for (const block of textBlocks) {
    if (!usedBlocks.has(block.text)) {
      nonTableBlocks.push(block)
    }
  }
  
  return { tables, textBlocks: nonTableBlocks }
}

/**
 * 按Y坐标分组，识别行
 */
function groupByRow(blocks: TextBlock[], threshold: number): TextBlock[][] {
  // 按Y坐标排序
  const sorted = [...blocks].sort((a, b) => a.bbox.y - b.bbox.y)
  
  const rows: TextBlock[][] = []
  let currentRow: TextBlock[] = []
  let lastY = 0
  
  for (const block of sorted) {
    const centerY = block.bbox.y + block.bbox.height / 2
    
    if (currentRow.length === 0 || Math.abs(centerY - lastY) < threshold) {
      currentRow.push(block)
      lastY = centerY
    } else {
      // 新行开始
      if (currentRow.length > 0) {
        // 按X坐标排序
        currentRow.sort((a, b) => a.bbox.x - b.bbox.x)
        rows.push(currentRow)
      }
      currentRow = [block]
      lastY = centerY
    }
  }
  
  // 添加最后一行
  if (currentRow.length > 0) {
    currentRow.sort((a, b) => a.bbox.x - b.bbox.x)
    rows.push(currentRow)
  }
  
  return rows
}

/**
 * 识别表格区域 - 基于行列对齐模式
 */
function identifyTableRegions(rows: TextBlock[][], minCellCount: number): TextBlock[][][] {
  const regions: TextBlock[][][] = []
  let currentRegion: TextBlock[][] = []
  
  for (const row of rows) {
    // 检查该行是否有多个单元格（可能是表格行）
    if (row.length >= 2) {
      currentRegion.push(row)
    } else {
      // 单行文本，可能是表格结束
      if (currentRegion.length >= 2) {
        // 检查总单元格数
        const totalCells = currentRegion.reduce((sum, r) => sum + r.length, 0)
        if (totalCells >= minCellCount) {
          regions.push(currentRegion)
        }
      }
      currentRegion = []
    }
  }
  
  // 处理最后一个区域
  if (currentRegion.length >= 2) {
    const totalCells = currentRegion.reduce((sum, r) => sum + r.length, 0)
    if (totalCells >= minCellCount) {
      regions.push(currentRegion)
    }
  }
  
  return regions
}

/**
 * 构建表格结构
 */
function buildTableStructure(
  region: TextBlock[][],
  config: TableDetectorConfig
): Table | null {
  if (region.length === 0) return null
  
  // 计算表格边界
  let minX = Infinity, minY = Infinity
  let maxX = 0, maxY = 0
  
  for (const row of region) {
    for (const cell of row) {
      minX = Math.min(minX, cell.bbox.x)
      minY = Math.min(minY, cell.bbox.y)
      maxX = Math.max(maxX, cell.bbox.x + cell.bbox.width)
      maxY = Math.max(maxY, cell.bbox.y + cell.bbox.height)
    }
  }
  
  // 列对齐 - 收集所有X坐标并聚类
  const allXCoords: number[] = []
  for (const row of region) {
    for (const cell of row) {
      allXCoords.push(cell.bbox.x)
    }
  }
  
  // 使用简单的聚类确定列边界
  const colBoundaries = clusterCoordinates(allXCoords, config.colThreshold)
  const colCount = colBoundaries.length
  
  // 构建单元格
  const cells: TableCell[] = []
  const headers: string[] = []
  
  for (let rowIdx = 0; rowIdx < region.length; rowIdx++) {
    const row = region[rowIdx]
    
    for (const block of row) {
      // 确定列索引
      const colIdx = findColumnIndex(block.bbox.x, colBoundaries, config.colThreshold)
      
      const cell: TableCell = {
        row: rowIdx,
        col: colIdx,
        text: block.text,
        confidence: block.confidence,
        bbox: block.bbox,
        merged: false
      }
      
      // 检测合并单元格
      const avgColWidth = colBoundaries.length > 1 
        ? (colBoundaries[1] - colBoundaries[0]) 
        : block.bbox.width
      
      if (block.bbox.width > avgColWidth * config.mergeThreshold) {
        cell.merged = true
        cell.colSpan = Math.round(block.bbox.width / avgColWidth)
      }
      
      cells.push(cell)
      
      // 收集表头
      if (rowIdx < config.headerRowCount && colIdx >= 0) {
        headers[colIdx] = block.text
      }
    }
  }
  
  // 计算实际行列数
  const maxRow = Math.max(...cells.map(c => c.row))
  const maxCol = Math.max(...cells.map(c => c.col))
  
  return {
    id: `table_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
    rowCount: maxRow + 1,
    colCount: maxCol + 1,
    cells,
    headers: headers.length > 0 ? headers : undefined,
    bbox: {
      x: minX,
      y: minY,
      width: maxX - minX,
      height: maxY - minY
    }
  }
}

/**
 * 坐标聚类 - 将相近的X坐标分组
 */
function clusterCoordinates(coords: number[], threshold: number): number[] {
  const sorted = [...coords].sort((a, b) => a - b)
  const clusters: number[] = []
  
  let currentCluster: number[] = []
  
  for (const coord of sorted) {
    if (currentCluster.length === 0) {
      currentCluster.push(coord)
    } else {
      const last = currentCluster[currentCluster.length - 1]
      if (Math.abs(coord - last) < threshold) {
        currentCluster.push(coord)
      } else {
        // 计算聚类中心
        const center = currentCluster.reduce((a, b) => a + b, 0) / currentCluster.length
        clusters.push(center)
        currentCluster = [coord]
      }
    }
  }
  
  // 处理最后一个聚类
  if (currentCluster.length > 0) {
    const center = currentCluster.reduce((a, b) => a + b, 0) / currentCluster.length
    clusters.push(center)
  }
  
  return clusters.sort((a, b) => a - b)
}

/**
 * 根据X坐标确定列索引
 */
function findColumnIndex(x: number, boundaries: number[], threshold: number): number {
  for (let i = 0; i < boundaries.length; i++) {
    if (Math.abs(x - boundaries[i]) < threshold) {
      return i
    }
  }
  // 如果没有匹配的，找到最近的
  let minDist = Infinity
  let closestIdx = 0
  for (let i = 0; i < boundaries.length; i++) {
    const dist = Math.abs(x - boundaries[i])
    if (dist < minDist) {
      minDist = dist
      closestIdx = i
    }
  }
  return closestIdx
}

/**
 * 将表格转换为 Markdown 格式
 */
export function tableToMarkdown(table: Table): string {
  if (table.cells.length === 0) return ''
  
  // 创建单元格矩阵
  const matrix: (TableCell | null)[][] = []
  for (let r = 0; r < table.rowCount; r++) {
    matrix[r] = new Array(table.colCount).fill(null)
  }
  
  // 填充单元格
  for (const cell of table.cells) {
    if (cell.row < table.rowCount && cell.col < table.colCount) {
      matrix[cell.row][cell.col] = cell
    }
  }
  
  // 生成 Markdown
  const lines: string[] = []
  
  for (let r = 0; r < table.rowCount; r++) {
    const rowCells = matrix[r].map(cell => cell?.text || '').map(escapeMarkdown)
    lines.push('| ' + rowCells.join(' | ') + ' |')
    
    // 表头分隔行
    if (r === 0) {
      const separators = matrix[r].map(() => '---')
      lines.push('| ' + separators.join(' | ') + ' |')
    }
  }
  
  return lines.join('\n')
}

/**
 * 转义 Markdown 特殊字符
 */
function escapeMarkdown(text: string): string {
  return text
    .replace(/\|/g, '\\|')
    .replace(/\n/g, ' ')
    .trim()
}

/**
 * 将表格转换为 HTML 格式
 */
export function tableToHTML(table: Table): string {
  const rows: string[] = []
  
  // 按行分组
  const rowMap: Map<number, TableCell[]> = new Map()
  for (const cell of table.cells) {
    if (!rowMap.has(cell.row)) {
      rowMap.set(cell.row, [])
    }
    rowMap.get(cell.row)!.push(cell)
  }
  
  // 生成行
  const sortedRows = Array.from(rowMap.entries()).sort((a, b) => a[0] - b[0])
  
  for (const [rowIdx, cells] of sortedRows) {
    const cellTags = cells
      .sort((a, b) => a.col - b.col)
      .map(cell => {
        const tag = rowIdx === 0 ? 'th' : 'td'
        const attrs: string[] = []
        if (cell.rowSpan && cell.rowSpan > 1) attrs.push(`rowspan="${cell.rowSpan}"`)
        if (cell.colSpan && cell.colSpan > 1) attrs.push(`colspan="${cell.colSpan}"`)
        
        const attrStr = attrs.length > 0 ? ' ' + attrs.join(' ') : ''
        return `<${tag}${attrStr}>${escapeHtml(cell.text)}</${tag}>`
      })
      .join('')
    
    rows.push(`  <tr>${cellTags}</tr>`)
  }
  
  return `<table>\n${rows.join('\n')}\n</table>`
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/**
 * 将表格转换为 JSON 格式
 */
export function tableToJSON(table: Table): object {
  // 按行分组
  const rowMap: Map<number, TableCell[]> = new Map()
  for (const cell of table.cells) {
    if (!rowMap.has(cell.row)) {
      rowMap.set(cell.row, [])
    }
    rowMap.get(cell.row)!.push(cell)
  }
  
  // 构建行数组
  const rows = Array.from(rowMap.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([_, cells]) => {
      const rowData: Record<string, string> = {}
      for (const cell of cells.sort((a, b) => a.col - b.col)) {
        const colName = table.headers?.[cell.col] || `col_${cell.col}`
        rowData[colName] = cell.text
      }
      return rowData
    })
  
  return {
    id: table.id,
    headers: table.headers,
    rowCount: table.rowCount,
    colCount: table.colCount,
    rows
  }
}

export default {
  detectTables,
  tableToMarkdown,
  tableToHTML,
  tableToJSON
}

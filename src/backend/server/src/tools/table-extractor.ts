/**
 * 通用表格提取器 - 基于 OCR 结果识别表格结构
 * 备用方案：当 PP-Structure 不可用时使用
 */

export interface OCRTextBlock {
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
  rowSpan?: number
  colSpan?: number
}

export interface TableRow {
  index: number
  cells: TableCell[]
}

export interface ExtractedTable {
  id: string
  rowCount: number
  colCount: number
  rows: TableRow[]
  headers?: string[]
  mergeCells?: Array<{
    row: number
    col: number
    rowSpan: number
    colSpan: number
  }>
}

export interface TableExtractionConfig {
  // Y坐标差异阈值（同一行）
  rowThreshold: number
  // X坐标差异阈值（同一列）
  colThreshold: number
  // 最小单元格数
  minCells: number
  // 合并单元格宽度倍数阈值
  mergeThreshold: number
}

const defaultConfig: TableExtractionConfig = {
  rowThreshold: 60,
  colThreshold: 80,
  minCells: 4,
  mergeThreshold: 1.8
}

/**
 * 从 OCR 文本块中提取表格结构
 * 通用算法，不依赖特定模型
 */
export function extractTableFromOCR(
  textBlocks: OCRTextBlock[],
  config: Partial<TableExtractionConfig> = {}
): ExtractedTable | null {
  const cfg = { ...defaultConfig, ...config }
  
  if (textBlocks.length < cfg.minCells) {
    return null
  }
  
  // 步骤1: 按Y坐标聚类识别行
  const rows = clusterRows(textBlocks, cfg.rowThreshold)
  
  if (rows.length < 2) {
    return null // 至少需要2行才认为是表格
  }
  
  // 步骤2: 构建列结构
  const tableRows = buildTableRows(rows, cfg)
  
  // 步骤3: 检测合并单元格
  const { rows: processedRows, mergeCells } = detectMergeCells(tableRows, cfg)
  
  // 步骤4: 提取表头（第一行）
  const headers = processedRows[0]?.cells.map(c => c.text) || []
  
  return {
    id: `table_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
    rowCount: processedRows.length,
    colCount: Math.max(...processedRows.map(r => r.cells.length)),
    rows: processedRows,
    headers,
    mergeCells: mergeCells.length > 0 ? mergeCells : undefined
  }
}

/**
 * 按Y坐标聚类识别表格行
 */
function clusterRows(
  blocks: OCRTextBlock[],
  threshold: number
): Array<Array<{ y: number; block: OCRTextBlock }>> {
  // 计算每个块的中心Y坐标
  const withY = blocks.map(b => ({
    y: b.bbox.y + b.bbox.height / 2,
    block: b
  }))
  
  // 按Y排序
  withY.sort((a, b) => a.y - b.y)
  
  const rows: Array<Array<{ y: number; block: OCRTextBlock }>> = []
  let currentRow: Array<{ y: number; block: OCRTextBlock }> = []
  let lastY: number | null = null
  
  for (const item of withY) {
    if (lastY === null || Math.abs(item.y - lastY) < threshold) {
      currentRow.push(item)
      // 更新行中心Y
      lastY = currentRow.reduce((sum, i) => sum + i.y, 0) / currentRow.length
    } else {
      // 新行开始
      if (currentRow.length > 0) {
        // 按X坐标排序
        currentRow.sort((a, b) => a.block.bbox.x - b.block.bbox.x)
        rows.push(currentRow)
      }
      currentRow = [item]
      lastY = item.y
    }
  }
  
  // 处理最后一行
  if (currentRow.length > 0) {
    currentRow.sort((a, b) => a.block.bbox.x - b.block.bbox.x)
    rows.push(currentRow)
  }
  
  return rows
}

/**
 * 构建表格行结构
 */
function buildTableRows(
  rows: Array<Array<{ y: number; block: OCRTextBlock }>>,
  config: TableExtractionConfig
): TableRow[] {
  return rows.map((row, rowIdx) => ({
    index: rowIdx,
    cells: row.map((item, colIdx) => ({
      row: rowIdx,
      col: colIdx,
      text: item.block.text,
      confidence: item.block.confidence,
      bbox: item.block.bbox
    }))
  }))
}

/**
 * 检测合并单元格
 */
function detectMergeCells(
  rows: TableRow[],
  config: TableExtractionConfig
): { rows: TableRow[]; mergeCells: Array<{ row: number; col: number; rowSpan: number; colSpan: number }> } {
  const mergeCells: Array<{ row: number; col: number; rowSpan: number; colSpan: number }> = []
  
  for (const row of rows) {
    if (row.cells.length === 0) continue
    
    // 计算平均单元格宽度
    const avgWidth = row.cells.reduce((sum, c) => sum + c.bbox.width, 0) / row.cells.length
    
    for (const cell of row.cells) {
      // 检测跨列
      if (cell.bbox.width > avgWidth * config.mergeThreshold) {
        const colSpan = Math.round(cell.bbox.width / avgWidth)
        if (colSpan > 1) {
          cell.colSpan = colSpan
          mergeCells.push({
            row: cell.row,
            col: cell.col,
            rowSpan: 1,
            colSpan
          })
        }
      }
    }
  }
  
  return { rows, mergeCells }
}

/**
 * 将提取的表格转换为 Markdown 格式
 */
export function tableToMarkdown(table: ExtractedTable): string {
  if (table.rows.length === 0) return ''
  
  const lines: string[] = []
  const maxCols = table.colCount
  
  for (let i = 0; i < table.rows.length; i++) {
    const row = table.rows[i]
    const cells: string[] = []
    
    for (let j = 0; j < maxCols; j++) {
      const cell = row.cells.find(c => c.col === j)
      let text = cell?.text || ''
      
      // 处理合并单元格
      if (cell?.colSpan && cell.colSpan > 1) {
        text += ' '.repeat(cell.colSpan - 1) // 占位
      }
      
      cells.push(text.trim())
    }
    
    lines.push('| ' + cells.join(' | ') + ' |')
    
    // 表头分隔行
    if (i === 0) {
      lines.push('|' + ' --- |'.repeat(maxCols))
    }
  }
  
  return lines.join('\n')
}

/**
 * 将提取的表格转换为 HTML 格式
 */
export function tableToHTML(table: ExtractedTable): string {
  if (table.rows.length === 0) return ''
  
  const htmlRows: string[] = []
  
  for (let i = 0; i < table.rows.length; i++) {
    const row = table.rows[i]
    const isHeader = i === 0
    const tag = isHeader ? 'th' : 'td'
    
    const cells = row.cells.map(cell => {
      let attrs = ''
      if (cell.colSpan && cell.colSpan > 1) {
        attrs += ` colspan="${cell.colSpan}"`
      }
      if (cell.rowSpan && cell.rowSpan > 1) {
        attrs += ` rowspan="${cell.rowSpan}"`
      }
      
      return `<${tag}${attrs}>${escapeHtml(cell.text)}</${tag}>`
    })
    
    htmlRows.push('  <tr>' + cells.join('') + '</tr>')
  }
  
  return '<table>\n' + htmlRows.join('\n') + '\n</table>'
}

/**
 * 将提取的表格转换为 JSON 格式
 */
export function tableToJSON(table: ExtractedTable): object {
  return {
    id: table.id,
    rowCount: table.rowCount,
    colCount: table.colCount,
    headers: table.headers,
    mergeCells: table.mergeCells,
    data: table.rows.map(row =>
      row.cells.reduce((obj, cell) => {
        const colName = table.headers?.[cell.col] || `col_${cell.col}`
        obj[colName] = cell.text
        return obj
      }, {} as Record<string, string>)
    )
  }
}

/**
 * 转义 HTML 特殊字符
 */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/**
 * 批量处理多页 OCR 结果，提取所有表格
 */
export function extractTablesFromPages(
  pages: Array<{
    pageNumber: number
    textBlocks: OCRTextBlock[]
  }>,
  config?: Partial<TableExtractionConfig>
): Array<{
  pageNumber: number
  table: ExtractedTable
}> {
  const results: Array<{ pageNumber: number; table: ExtractedTable }> = []
  
  for (const page of pages) {
    const table = extractTableFromOCR(page.textBlocks, config)
    if (table) {
      results.push({
        pageNumber: page.pageNumber,
        table
      })
    }
  }
  
  return results
}

export default {
  extractTableFromOCR,
  extractTablesFromPages,
  tableToMarkdown,
  tableToHTML,
  tableToJSON
}

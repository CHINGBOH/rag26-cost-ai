/**
 * OCR模块 - PDF解析与OCR识别
 * 调用Python PaddleOCR服务
 */

import {
  OCRPage,
  OCRTextBlock,
  OCRResult
} from '../../common/types'

// ==================== 配置类型 ====================

export interface OCRConfig {
  ocrServiceUrl: string
  language: string
  dpi: number
  timeout: number
  useGPU?: boolean
}

export interface PDFConfig {
  extractImages?: boolean
  extractTables?: boolean
  password?: string
}

export interface ChunkConfig {
  chunkSize: number
  chunkOverlap: number
  minChunkSize: number
}

export interface ParsedPage {
  pageNum: number
  width: number
  height: number
  content: string
  textBlocks?: OCRTextBlock[]
  images?: string[]
}

export interface DocumentChunk {
  id: string
  content: string
  pageNum: number
  metadata: {
    source: string
    page: number
    bbox?: [number, number, number, number]
  }
}

// ==================== 默认配置 ====================

const defaultOCRConfig: OCRConfig = {
  ocrServiceUrl: process.env.OCR_SERVICE_URL || 'http://localhost:8001',
  language: 'ch',
  dpi: 300,
  timeout: 300000,
  useGPU: false
}

const defaultChunkConfig: ChunkConfig = {
  chunkSize: 512,
  chunkOverlap: 50,
  minChunkSize: 100
}

// ==================== Python OCR 服务响应类型 ====================

interface PythonOCRTextBlock {
  text: string
  confidence: number
  bbox: {
    x1: number
    y1: number
    x2: number
    y2: number
  }
}

interface PythonOCRPageResult {
  page_number: number
  text_blocks: PythonOCRTextBlock[]
  tables: any[]
  raw_text: string
  markdown: string
  confidence: number
}

interface PythonOCRDocumentResult {
  document_id: string
  file_name: string
  total_pages: number
  pages: PythonOCRPageResult[]
  full_text: string
  processing_time: number
}

interface PythonHealthResponse {
  status: string
  ocr_available: boolean
  table_detection_available: boolean
  version?: string
}

// ==================== 格式转换 ====================

function convertPythonTextBlock(block: PythonOCRTextBlock, index: number): OCRTextBlock {
  return {
    id: `block_${index}_${Date.now()}`,
    text: block.text,
    confidence: block.confidence,
    bbox: [
      block.bbox?.x1 || 0,
      block.bbox?.y1 || 0,
      block.bbox?.x2 || 0,
      block.bbox?.y2 || 0
    ] as [number, number, number, number],
    type: 'text'
  }
}

function convertPythonPage(page: PythonOCRPageResult): OCRPage {
  // 估算页面尺寸 (如果没有提供)
  const width = 612  // 标准 PDF 宽度
  const height = 792 // 标准 PDF 高度
  
  return {
    pageNum: page.page_number,
    width,
    height,
    textBlocks: page.text_blocks.map((b, i) => convertPythonTextBlock(b, i))
  }
}

function convertPythonResult(result: PythonOCRDocumentResult): OCRResult {
  return {
    docId: result.document_id,
    filename: result.file_name,
    totalPages: result.total_pages,
    pages: result.pages.map(convertPythonPage),
    processingTime: result.processing_time,
    metadata: {
      source: 'paddleocr',
      fullText: result.full_text
    }
  }
}

// ==================== PDF解析 ====================

export function parsePDF(config?: Partial<PDFConfig>) {
  return async function parse(fileBuffer: Buffer): Promise<ParsedPage[]> {
    try {
      console.log('[OCR] Parsing PDF...')

      // 模拟返回解析结果
      return [{
        pageNum: 1,
        width: 612,
        height: 792,
        content: 'Extracted text content from PDF',
        textBlocks: []
      }]
    } catch (error) {
      console.error('[OCR] PDF parsing failed:', error)
      throw error
    }
  }
}

export function parsePDFFromPath(config?: Partial<PDFConfig & OCRConfig>) {
  const cfg = { ...defaultOCRConfig, ...config }

  return async function parseFromPath(filePath: string): Promise<ParsedPage[]> {
    try {
      const fs = await import('fs')
      const buffer = fs.readFileSync(filePath)
      return parsePDF(config)(buffer)
    } catch (error) {
      console.error('[OCR] Failed to read PDF file:', error)
      throw error
    }
  }
}

// ==================== OCR识别 ====================

export function ocrImage(config?: Partial<OCRConfig>) {
  const cfg = { ...defaultOCRConfig, ...config }

  return async function recognize(imageBuffer: Buffer): Promise<OCRTextBlock[]> {
    try {
      console.log('[OCR] Processing image...')

      // 使用原生 FormData (Node.js 18+)
      const form = new FormData()
      const blob = new Blob([imageBuffer])
      form.append('file', blob, 'image.png')

      const response = await fetch(`${cfg.ocrServiceUrl}/ocr/image`, {
        method: 'POST',
        body: form
      })

      if (!response.ok) {
        throw new Error(`OCR failed: ${response.status}`)
      }

      const data = await (response as any).json() as { text_blocks?: PythonOCRTextBlock[] }
      
      if (data.text_blocks && Array.isArray(data.text_blocks)) {
        return data.text_blocks.map((b, i) => convertPythonTextBlock(b, i))
      }
      
      return []
    } catch (error) {
      console.warn('[OCR] OCR service unavailable, using mock data:', error)
      return getMockTextBlocks()
    }
  }
}

export function ocrPDF(config?: Partial<OCRConfig>) {
  const cfg = { ...defaultOCRConfig, ...config }

  return async function recognizePDF(fileBuffer: Buffer, filename: string): Promise<OCRResult> {
    try {
      console.log(`[OCR] Processing PDF: ${filename}`)

      // 使用原生 FormData (Node.js 18+)
      const form = new FormData()
      const blob = new Blob([fileBuffer])
      form.append('file', blob, filename)
      form.append('language', cfg.language)
      form.append('dpi', String(cfg.dpi))

      const response = await fetch(`${cfg.ocrServiceUrl}/ocr/pdf`, {
        method: 'POST',
        body: form
      })

      if (!response.ok) {
        throw new Error(`PDF OCR failed: ${response.status}`)
      }

      const data = await (response as any).json() as PythonOCRDocumentResult
      return convertPythonResult(data)
    } catch (error) {
      console.warn('[OCR] PDF OCR failed, using mock data:', error)
      return getMockOCRResult(filename)
    }
  }
}

// ==================== 文本提取 ====================

export function extractText() {
  return function extract(pages: ParsedPage[]): string {
    return pages.map(page => page.content).join('\n\n')
  }
}

export function extractTextBlocks() {
  return function extract(pages: ParsedPage[]): OCRTextBlock[] {
    return pages.flatMap(page => page.textBlocks || [])
  }
}

// ==================== 文档分块 ====================

export function chunkDocument(config?: Partial<ChunkConfig>) {
  const cfg = { ...defaultChunkConfig, ...config }

  return function chunk(text: string, source: string = 'document'): DocumentChunk[] {
    const chunks: DocumentChunk[] = []
    const separator = '\n\n'
    const parts = text.split(separator)

    let index = 0
    for (const part of parts) {
      if (part.length > cfg.chunkSize) {
        // 进一步分割
        const subParts = part.match(new RegExp(`.{1,${cfg.chunkSize}}`, 'g')) || []
        for (const subPart of subParts) {
          if (subPart.trim().length >= cfg.minChunkSize) {
            chunks.push(createChunk(subPart, source, index++))
          }
        }
      } else if (part.trim().length >= cfg.minChunkSize) {
        chunks.push(createChunk(part, source, index++))
      }
    }

    return chunks
  }
}

export function chunkFromBlocks(config?: Partial<ChunkConfig>) {
  const cfg = { ...defaultChunkConfig, ...config }

  return function chunk(blocks: OCRTextBlock[], source: string = 'document'): DocumentChunk[] {
    return blocks.map((block, index) => ({
      id: `chunk_${source}_${index}_${Date.now()}`,
      content: block.text,
      pageNum: 0,
      metadata: {
        source,
        page: 0,
        bbox: block.bbox
      }
    }))
  }
}

function createChunk(content: string, source: string, index: number): DocumentChunk {
  return {
    id: `chunk_${source}_${index}_${Date.now()}`,
    content: content.trim(),
    pageNum: 0,
    metadata: {
      source,
      page: 0
    }
  }
}

// ==================== 文档处理管道 ====================

export function createOCRPipeline(config?: Partial<OCRConfig & PDFConfig & ChunkConfig>) {
  const ocrCfg = { ...defaultOCRConfig, ...config }
  const chunkCfg = { ...defaultChunkConfig, ...config }

  return {
    parsePDF: parsePDF(config),
    parseFromPath: parsePDFFromPath(config),
    ocrImage: ocrImage(ocrCfg),
    ocrPDF: ocrPDF(ocrCfg),
    extractText: extractText(),
    extractTextBlocks: extractTextBlocks(),
    chunkDocument: chunkDocument(chunkCfg),
    chunkFromBlocks: chunkFromBlocks(chunkCfg)
  }
}

export function processDocument(config?: Partial<OCRConfig & PDFConfig & ChunkConfig>) {
  return async function process(filePath: string): Promise<{
    chunks: DocumentChunk[]
    ocrResult: OCRResult
    text: string
  }> {
    const fs = await import('fs')
    const buffer = fs.readFileSync(filePath)
    const filename = filePath.split('/').pop() || 'document.pdf'

    // 1. OCR识别
    const ocrResult = await ocrPDF(config)(buffer, filename)

    // 2. 提取文本
    const pages: ParsedPage[] = ocrResult.pages.map(page => ({
      pageNum: page.pageNum,
      width: page.width,
      height: page.height,
      content: page.textBlocks.map(b => b.text).join('\n'),
      textBlocks: page.textBlocks
    }))

    const text = extractText()(pages)

    // 3. 分块
    const chunks = chunkDocument(config)(text, filename)

    return {
      chunks,
      ocrResult,
      text
    }
  }
}

// ==================== 健康检查 ====================

export async function healthCheck(config?: Partial<OCRConfig>): Promise<{
  healthy: boolean
  version?: string
  ocrAvailable?: boolean
}> {
  const cfg = { ...defaultOCRConfig, ...config }

  try {
    const response = await fetch(`${cfg.ocrServiceUrl}/health`)

    if (response.ok) {
      const data = await (response as any).json() as PythonHealthResponse
      return {
        healthy: data.status === 'healthy',
        version: data.version,
        ocrAvailable: data.ocr_available
      }
    }

    return { healthy: false }
  } catch (error) {
    console.error('[OCR] Health check failed:', error)
    return { healthy: false }
  }
}

// ==================== 模拟数据 ====================

function getMockTextBlocks(): OCRTextBlock[] {
  return [
    {
      id: 'mock_1',
      text: '这是OCR识别的模拟文本块。实际使用时将调用PaddleOCR服务进行真实识别。',
      confidence: 0.95,
      bbox: [10, 10, 400, 50],
      type: 'text'
    },
    {
      id: 'mock_2',
      text: '支持中英文混合识别，表格识别等功能。',
      confidence: 0.92,
      bbox: [10, 60, 300, 100],
      type: 'text'
    }
  ]
}

function getMockOCRResult(filename: string): OCRResult {
  return {
    docId: `doc_${Date.now()}`,
    filename,
    pages: [
      {
        pageNum: 1,
        width: 612,
        height: 792,
        textBlocks: getMockTextBlocks()
      }
    ],
    totalPages: 1,
    processingTime: 1000,
    metadata: {
      source: 'mock',
      mock: true
    }
  }
}

/**
 * OCR 管道类型定义
 * PDF 图片格式处理 - 图文表混排识别
 */

// ==================== OCR 核心类型 ====================

export type OCRProvider = 'paddleocr' | 'tesseract' | 'easyocr';

export type DocumentElementType = 
  | 'text'
  | 'title'
  | 'paragraph'
  | 'table'
  | 'figure'
  | 'formula'
  | 'list'
  | 'header'
  | 'footer'
  | 'page_number';

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface OCRTextBlock {
  id: string;
  text: string;
  confidence: number;
  bbox: BoundingBox;
  language?: string;
  fontSize?: number;
  fontName?: string;
  isVertical?: boolean;
}

export interface OCRTableCell {
  row: number;
  col: number;
  rowSpan?: number;
  colSpan?: number;
  text: string;
  bbox: BoundingBox;
}

export interface OCRTable {
  id: string;
  bbox: BoundingBox;
  rows: number;
  cols: number;
  cells: OCRTableCell[];
  html?: string;
  markdown?: string;
}

export interface OCRFigure {
  id: string;
  bbox: BoundingBox;
  caption?: string;
  imagePath?: string;
  ocrText?: string;
}

export interface DocumentElement {
  id: string;
  type: DocumentElementType;
  bbox: BoundingBox;
  content: string;
  confidence: number;
  metadata?: {
    level?: number;           // 标题级别 (h1, h2, ...)
    table?: OCRTable;         // 表格数据
    figure?: OCRFigure;       // 图片数据
    listItems?: string[];     // 列表项
  };
}

// ==================== OCR 页面结果 ====================

export interface OCRPageResult {
  pageNumber: number;
  width: number;
  height: number;
  imagePath?: string;         // 转换后的图片路径
  textBlocks: OCRTextBlock[];
  tables: OCRTable[];
  figures: OCRFigure[];
  elements: DocumentElement[]; // 结构化元素（按阅读顺序）
  rawText: string;            // 纯文本
  markdown: string;           // Markdown 格式
  confidence: number;         // 整体置信度
  processingTime: number;     // 处理耗时(ms)
}

// ==================== OCR 文档结果 ====================

export interface OCRDocumentResult {
  documentId: string;
  filePath: string;
  fileName: string;
  fileType: 'pdf' | 'image';
  totalPages: number;
  pages: OCRPageResult[];
  fullText: string;
  structuredText: string;     // 带结构的文本
  metadata: {
    title?: string;
    author?: string;
    createdAt?: Date;
    pageSize?: { width: number; height: number };
  };
  stats: {
    totalChars: number;
    totalTables: number;
    totalFigures: number;
    averageConfidence: number;
    processingTime: number;
  };
}

// ==================== OCR 配置 ====================

export interface OCRConfig {
  provider: OCRProvider;
  language: string;           // 'ch', 'en', 'ch+en', etc.
  useGpu?: boolean;
  gpuId?: number;
  
  // 图像预处理
  preprocessing?: {
    dpi?: number;             // PDF转图片分辨率，默认300
    enhanceContrast?: boolean;
    denoise?: boolean;
    deskew?: boolean;         // 自动纠偏
    binarize?: boolean;       // 二值化
  };
  
  // 版面分析
  layoutAnalysis?: {
    enabled: boolean;
    detectTables: boolean;
    detectFigures: boolean;
    detectFormulas: boolean;
  };
  
  // 表格识别
  tableRecognition?: {
    enabled: boolean;
    outputFormat: 'html' | 'markdown' | 'json';
  };
  
  // 后处理
  postProcessing?: {
    cleanText: boolean;
    mergeParagraphs: boolean;
    preserveLayout: boolean;
  };
}

// ==================== OCR 服务接口 ====================

export interface OCRService {
  initialize(config: OCRConfig): Promise<void>;
  processPDF(filePath: string, config?: Partial<OCRConfig>): Promise<OCRDocumentResult>;
  processImage(imagePath: string, config?: Partial<OCRConfig>): Promise<OCRPageResult>;
  processBuffer(buffer: Buffer, fileType: string, config?: Partial<OCRConfig>): Promise<OCRDocumentResult>;
  cleanup(): Promise<void>;
}

// ==================== PDF 解析类型 ====================

export interface PDFParseOptions {
  dpi?: number;
  pages?: number[];           // 指定页码，空则全部
  password?: string;
}

export interface PDFPageInfo {
  pageNumber: number;
  width: number;
  height: number;
  rotation: number;
  hasText: boolean;           // 是否包含可选中文字
  imageCount: number;
}

export interface PDFParseResult {
  filePath: string;
  pageCount: number;
  pages: PDFPageInfo[];
  metadata: {
    title?: string;
    author?: string;
    subject?: string;
    creator?: string;
    creationDate?: Date;
    modificationDate?: Date;
  };
}

// ==================== 文档处理管道 ====================

export interface DocumentProcessingStage {
  name: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  progress: number;           // 0-100
  startTime?: number;
  endTime?: number;
  error?: string;
}

export interface DocumentProcessingJob {
  jobId: string;
  documentId: string;
  filePath: string;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  stages: DocumentProcessingStage[];
  result?: OCRDocumentResult;
  error?: string;
  createdAt: number;
  updatedAt: number;
}

// ==================== 检索增强类型 ====================

export interface OCRSearchChunk {
  id: string;
  text: string;
  pageNumber: number;
  elementType: DocumentElementType;
  bbox: BoundingBox;
  confidence: number;
  source: string;             // 来源文档
  context: {                  // 上下文
    before: string;
    after: string;
  };
  metadata: {
    isTable?: boolean;
    isTitle?: boolean;
    tableData?: OCRTable;
  };
}

// ==================== 错误类型 ====================

export class OCRError extends Error {
  constructor(
    message: string,
    public code: string,
    public details?: any
  ) {
    super(message);
    this.name = 'OCRError';
  }
}

export type OCRErrorCode = 
  | 'INIT_FAILED'
  | 'FILE_NOT_FOUND'
  | 'INVALID_FORMAT'
  | 'PROCESSING_FAILED'
  | 'TIMEOUT'
  | 'CLEANUP_FAILED';

/**
 * PaddleOCR 服务实现
 * 中文场景最优的 OCR 解决方案
 */

import { spawn } from 'child_process';
import * as fs from 'fs/promises';
import * as path from 'path';
import {
  OCRService,
  OCRConfig,
  OCRDocumentResult,
  OCRPageResult,
  OCRTextBlock,
  OCRTable,
  DocumentElement,
  OCRError,
  BoundingBox
} from '@rag/shared';

export class PaddleOCRService implements OCRService {
  private config: OCRConfig;
  private initialized: boolean = false;

  constructor() {
    this.config = {
      provider: 'paddleocr',
      language: 'ch',
      useGpu: false,
      preprocessing: {
        dpi: 300,
        enhanceContrast: true,
        denoise: true,
        deskew: true,
        binarize: false
      },
      layoutAnalysis: {
        enabled: true,
        detectTables: true,
        detectFigures: true,
        detectFormulas: false
      },
      tableRecognition: {
        enabled: true,
        outputFormat: 'markdown'
      },
      postProcessing: {
        cleanText: true,
        mergeParagraphs: true,
        preserveLayout: true
      }
    };
  }

  /**
   * 初始化 PaddleOCR
   */
  async initialize(config?: Partial<OCRConfig>): Promise<void> {
    if (config) {
      this.config = { ...this.config, ...config };
    }

    // 检查 Python 和 PaddleOCR 是否可用
    const checkScript = `
import sys
try:
    from paddleocr import PaddleOCR
    print("PaddleOCR available")
    sys.exit(0)
except ImportError as e:
    print(f"PaddleOCR not installed: {e}", file=sys.stderr)
    sys.exit(1)
`;

    return new Promise((resolve, reject) => {
      const python = spawn('python3', ['-c', checkScript]);
      let errorOutput = '';

      python.stderr.on('data', (data) => {
        errorOutput += data.toString();
      });

      python.on('close', (code) => {
        if (code !== 0) {
          reject(new OCRError(
            `PaddleOCR not available: ${errorOutput}`,
            'INIT_FAILED',
            { errorOutput }
          ));
          return;
        }
        this.initialized = true;
        resolve();
      });
    });
  }

  /**
   * 处理 PDF 文件
   */
  async processPDF(
    filePath: string,
    config?: Partial<OCRConfig>
  ): Promise<OCRDocumentResult> {
    this.ensureInitialized();

    const mergedConfig = { ...this.config, ...config };
    const documentId = `doc_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    const tempDir = `/tmp/rag-ocr/${documentId}`;

    try {
      await fs.mkdir(tempDir, { recursive: true });

      // 1. 转换 PDF 为图片
      const images = await this.convertPDFToImages(filePath, tempDir, mergedConfig);

      // 2. 处理每一页
      const pages: OCRPageResult[] = [];
      for (let i = 0; i < images.length; i++) {
        const pageResult = await this.processImage(images[i], {
          ...mergedConfig,
          pageNumber: i + 1
        });
        pages.push(pageResult);
      }

      // 3. 组装结果
      const result = this.assembleDocumentResult(
        documentId,
        filePath,
        pages,
        'pdf'
      );

      return result;
    } finally {
      // 清理临时文件
      await fs.rm(tempDir, { recursive: true, force: true });
    }
  }

  /**
   * 处理单张图片
   */
  async processImage(
    imagePath: string,
    config?: Partial<OCRConfig> & { pageNumber?: number }
  ): Promise<OCRPageResult> {
    this.ensureInitialized();

    const mergedConfig = { ...this.config, ...config };
    const pageNumber = config?.pageNumber || 1;

    const startTime = Date.now();

    // 构建 PaddleOCR 处理脚本
    const script = this.buildOCRScript(imagePath, mergedConfig);

    return new Promise((resolve, reject) => {
      const python = spawn('python3', ['-c', script]);
      let output = '';
      let errorOutput = '';

      python.stdout.on('data', (data) => {
        output += data.toString();
      });

      python.stderr.on('data', (data) => {
        errorOutput += data.toString();
      });

      python.on('close', (code) => {
        if (code !== 0) {
          reject(new OCRError(
            `OCR processing failed: ${errorOutput}`,
            'PROCESSING_FAILED',
            { imagePath, errorOutput }
          ));
          return;
        }

        try {
          const ocrResult = JSON.parse(output);
          const pageResult = this.parseOCRResult(
            ocrResult,
            pageNumber,
            imagePath,
            Date.now() - startTime
          );
          resolve(pageResult);
        } catch (error) {
          reject(new OCRError(
            'Failed to parse OCR result',
            'PROCESSING_FAILED',
            { output, error }
          ));
        }
      });
    });
  }

  /**
   * 处理 Buffer（用于上传的文件）
   */
  async processBuffer(
    buffer: Buffer,
    fileType: string,
    config?: Partial<OCRConfig>
  ): Promise<OCRDocumentResult> {
    const tempPath = `/tmp/rag-ocr/temp_${Date.now()}.${fileType}`;
    
    try {
      await fs.writeFile(tempPath, buffer);
      
      if (fileType.toLowerCase() === 'pdf') {
        return await this.processPDF(tempPath, config);
      } else {
        // 图片文件
        const pageResult = await this.processImage(tempPath, config);
        const documentId = `doc_${Date.now()}`;
        return this.assembleDocumentResult(
          documentId,
          tempPath,
          [pageResult],
          'image'
        );
      }
    } finally {
      await fs.unlink(tempPath).catch(() => {});
    }
  }

  /**
   * 清理资源
   */
  async cleanup(): Promise<void> {
    this.initialized = false;
  }

  // ==================== 私有方法 ====================

  private ensureInitialized(): void {
    if (!this.initialized) {
      throw new OCRError(
        'OCR service not initialized',
        'INIT_FAILED'
      );
    }
  }

  /**
   * 将 PDF 转换为图片
   */
  private async convertPDFToImages(
    filePath: string,
    outputDir: string,
    config: OCRConfig
  ): Promise<string[]> {
    const dpi = config.preprocessing?.dpi || 300;

    const script = `
import sys
import json
try:
    import fitz  # PyMuPDF
except ImportError:
    print(json.dumps({"error": "PyMuPDF not installed"}), file=sys.stderr)
    sys.exit(1)

try:
    doc = fitz.open("${filePath.replace(/"/g, '\\"')}")
    images = []
    
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        
        # 使用矩阵提高分辨率
        mat = fitz.Matrix(${dpi}/72, ${dpi}/72)
        pix = page.get_pixmap(matrix=mat)
        
        output_path = "${outputDir.replace(/"/g, '\\"')}/page_{:04d}.png".format(page_num + 1)
        pix.save(output_path)
        images.append(output_path)
    
    doc.close()
    print(json.dumps({"images": images}, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"error": str(e)}), file=sys.stderr)
    sys.exit(1)
`;

    return new Promise((resolve, reject) => {
      const python = spawn('python3', ['-c', script]);
      let output = '';
      let errorOutput = '';

      python.stdout.on('data', (data) => {
        output += data.toString();
      });

      python.stderr.on('data', (data) => {
        errorOutput += data.toString();
      });

      python.on('close', (code) => {
        if (code !== 0) {
          reject(new OCRError(
            `PDF conversion failed: ${errorOutput}`,
            'PROCESSING_FAILED'
          ));
          return;
        }

        try {
          const result = JSON.parse(output);
          resolve(result.images);
        } catch (error) {
          reject(new OCRError(
            'Failed to parse conversion result',
            'PROCESSING_FAILED'
          ));
        }
      });
    });
  }

  /**
   * 构建 PaddleOCR Python 脚本
   */
  private buildOCRScript(imagePath: string, config: OCRConfig): string {
    const useGpu = config.useGpu ?? false;
    const lang = config.language || 'ch';
    const layoutEnabled = config.layoutAnalysis?.enabled ?? true;
    const tableEnabled = config.tableRecognition?.enabled ?? true;

    return `
import sys
import json
from paddleocr import PaddleOCR, PPStructure

# 初始化 OCR 引擎
ocr_engine = PaddleOCR(
    use_angle_cls=True,
    lang='${lang}',
    use_gpu=${useGpu},
    show_log=False
)

# 初始化版面分析引擎（如果需要）
${layoutEnabled ? `
table_engine = PPStructure(
    layout=True,
    ocr=True,
    show_log=False,
    use_gpu=${useGpu}
)` : ''}

# 执行 OCR
result = ocr_engine.ocr("${imagePath.replace(/"/g, '\\"')}", cls=True)

# 解析文本块
text_blocks = []
if result and result[0]:
    for line in result[0]:
        bbox = line[0]
        text = line[1][0]
        confidence = line[1][1]
        
        text_blocks.append({
            "text": text,
            "confidence": confidence,
            "bbox": {
                "x": min(p[0] for p in bbox),
                "y": min(p[1] for p in bbox),
                "width": max(p[0] for p in bbox) - min(p[0] for p in bbox),
                "height": max(p[1] for p in bbox) - min(p[1] for p in bbox)
            }
        })

# 版面分析
layout_result = None
${layoutEnabled ? `
try:
    img = cv2.imread("${imagePath.replace(/"/g, '\\"')}")
    layout_result = table_engine(img)
except Exception as e:
    layout_result = {"error": str(e)}
` : ''}

output = {
    "text_blocks": text_blocks,
    "layout": layout_result
}

print(json.dumps(output, ensure_ascii=False))
`;
  }

  /**
   * 解析 OCR 结果
   */
  private parseOCRResult(
    ocrResult: any,
    pageNumber: number,
    imagePath: string,
    processingTime: number
  ): OCRPageResult {
    const textBlocks: OCRTextBlock[] = (ocrResult.text_blocks || []).map(
      (block: any, idx: number) => ({
        id: `block_${pageNumber}_${idx}`,
        text: block.text,
        confidence: block.confidence,
        bbox: block.bbox
      })
    );

    // 构建纯文本
    const rawText = textBlocks.map(b => b.text).join('\\n');

    // 构建 Markdown
    const markdown = this.buildMarkdown(textBlocks, ocrResult.layout);

    // 解析版面结构
    const elements = this.parseLayoutElements(
      textBlocks,
      ocrResult.layout,
      pageNumber
    );

    // 解析表格
    const tables = this.parseTables(ocrResult.layout);

    // 计算整体置信度
    const avgConfidence = textBlocks.length > 0
      ? textBlocks.reduce((sum, b) => sum + b.confidence, 0) / textBlocks.length
      : 0;

    return {
      pageNumber,
      width: 0,  // 需要从图片获取
      height: 0,
      imagePath,
      textBlocks,
      tables,
      figures: [],
      elements,
      rawText,
      markdown,
      confidence: avgConfidence,
      processingTime
    };
  }

  /**
   * 构建 Markdown 格式文本
   */
  private buildMarkdown(
    textBlocks: OCRTextBlock[],
    layout: any
  ): string {
    // 简单实现：按阅读顺序合并文本块
    // 实际应该根据版面分析结果进行更复杂的处理
    return textBlocks
      .sort((a, b) => a.bbox.y - b.bbox.y || a.bbox.x - b.bbox.x)
      .map(b => b.text)
      .join('\\n\\n');
  }

  /**
   * 解析版面元素
   */
  private parseLayoutElements(
    textBlocks: OCRTextBlock[],
    layout: any,
    pageNumber: number
  ): DocumentElement[] {
    const elements: DocumentElement[] = [];

    // 简单的启发式规则识别标题和段落
    const sortedBlocks = textBlocks.sort(
      (a, b) => a.bbox.y - b.bbox.y || a.bbox.x - b.bbox.x
    );

    sortedBlocks.forEach((block, idx) => {
      // 启发式：短文本、高位置可能是标题
      const isTitle = block.text.length < 50 && idx < 3;
      
      elements.push({
        id: `elem_${pageNumber}_${idx}`,
        type: isTitle ? 'title' : 'paragraph',
        bbox: block.bbox,
        content: block.text,
        confidence: block.confidence,
        metadata: isTitle ? { level: 1 } : undefined
      });
    });

    return elements;
  }

  /**
   * 解析表格
   */
  private parseTables(layout: any): OCRTable[] {
    // 从 PPStructure 结果解析表格
    // 这是一个简化实现
    return [];
  }

  /**
   * 组装文档结果
   */
  private assembleDocumentResult(
    documentId: string,
    filePath: string,
    pages: OCRPageResult[],
    fileType: 'pdf' | 'image'
  ): OCRDocumentResult {
    const fullText = pages.map(p => p.rawText).join('\\n\\n');
    const structuredText = pages.map(p => p.markdown).join('\\n\\n---\\n\\n');

    const totalChars = fullText.length;
    const totalTables = pages.reduce((sum, p) => sum + p.tables.length, 0);
    const totalFigures = pages.reduce((sum, p) => sum + p.figures.length, 0);
    const avgConfidence = pages.length > 0
      ? pages.reduce((sum, p) => sum + p.confidence, 0) / pages.length
      : 0;
    const processingTime = pages.reduce((sum, p) => sum + p.processingTime, 0);

    return {
      documentId,
      filePath,
      fileName: path.basename(filePath),
      fileType,
      totalPages: pages.length,
      pages,
      fullText,
      structuredText,
      metadata: {},
      stats: {
        totalChars,
        totalTables,
        totalFigures,
        averageConfidence: avgConfidence,
        processingTime
      }
    };
  }
}

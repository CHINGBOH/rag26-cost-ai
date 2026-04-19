/**
 * PDF 解析服务
 * 使用 PyMuPDF 和 pdf2image 进行 PDF 处理
 */

import { spawn } from 'child_process';
import * as path from 'path';
import * as fs from 'fs/promises';
import { PDFParseOptions, PDFParseResult, PDFPageInfo, OCRError } from '@rag/shared';

export class PDFParserService {
  private tempDir: string;

  constructor(tempDir: string = '/tmp/rag-ocr') {
    this.tempDir = tempDir;
  }

  /**
   * 初始化临时目录
   */
  async initialize(): Promise<void> {
    try {
      await fs.mkdir(this.tempDir, { recursive: true });
    } catch (error) {
      throw new OCRError(
        'Failed to create temp directory',
        'INIT_FAILED',
        { tempDir: this.tempDir, error }
      );
    }
  }

  /**
   * 解析 PDF 基本信息
   */
  async parsePDF(filePath: string, options?: PDFParseOptions): Promise<PDFParseResult> {
    // 检查文件是否存在
    try {
      await fs.access(filePath);
    } catch {
      throw new OCRError(
        `File not found: ${filePath}`,
        'FILE_NOT_FOUND',
        { filePath }
      );
    }

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
    
    pages = []
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        pages.append({
            "pageNumber": page_num + 1,
            "width": page.rect.width,
            "height": page.rect.height,
            "rotation": page.rotation,
            "hasText": len(page.get_text()) > 0,
            "imageCount": len(page.get_images())
        })
    
    metadata = doc.metadata
    result = {
        "filePath": "${filePath.replace(/"/g, '\\"')}",
        "pageCount": len(doc),
        "pages": pages,
        "metadata": {
            "title": metadata.get('title'),
            "author": metadata.get('author'),
            "subject": metadata.get('subject'),
            "creator": metadata.get('creator'),
            "creationDate": metadata.get('creationDate'),
            "modificationDate": metadata.get('modificationDate')
        }
    }
    
    print(json.dumps(result, ensure_ascii=False))
    doc.close()
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
            `PDF parsing failed: ${errorOutput}`,
            'PROCESSING_FAILED',
            { filePath, errorOutput }
          ));
          return;
        }

        try {
          const result = JSON.parse(output);
          if (result.error) {
            reject(new OCRError(
              result.error,
              'PROCESSING_FAILED',
              { filePath }
            ));
            return;
          }
          resolve(result as PDFParseResult);
        } catch (error) {
          reject(new OCRError(
            'Failed to parse PDF info output',
            'PROCESSING_FAILED',
            { output, error }
          ));
        }
      });
    });
  }

  /**
   * 将 PDF 页面转换为图片
   */
  async convertToImages(
    filePath: string,
    outputDir: string,
    options?: PDFParseOptions
  ): Promise<string[]> {
    await fs.mkdir(outputDir, { recursive: true });

    const dpi = options?.dpi || 300;
    const pages = options?.pages;

    const script = `
import sys
import json
try:
    import fitz
except ImportError:
    print(json.dumps({"error": "PyMuPDF not installed"}), file=sys.stderr)
    sys.exit(1)

try:
    doc = fitz.open("${filePath.replace(/"/g, '\\"')}")
    image_paths = []
    
    page_numbers = ${pages ? JSON.stringify(pages) : 'list(range(1, len(doc) + 1))'}
    
    for page_num in page_numbers:
        if page_num < 1 or page_num > len(doc):
            continue
        page = doc.load_page(page_num - 1)
        
        # 使用矩阵提高分辨率
        mat = fitz.Matrix(${dpi}/72, ${dpi}/72)
        pix = page.get_pixmap(matrix=mat)
        
        output_path = "${outputDir.replace(/"/g, '\\"')}/page_{:04d}.png".format(page_num)
        pix.save(output_path)
        image_paths.append(output_path)
    
    doc.close()
    print(json.dumps({"images": image_paths}, ensure_ascii=False))
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
            `PDF to image conversion failed: ${errorOutput}`,
            'PROCESSING_FAILED',
            { filePath, errorOutput }
          ));
          return;
        }

        try {
          const result = JSON.parse(output);
          if (result.error) {
            reject(new OCRError(
              result.error,
              'PROCESSING_FAILED',
              { filePath }
            ));
            return;
          }
          resolve(result.images);
        } catch (error) {
          reject(new OCRError(
            'Failed to parse conversion output',
            'PROCESSING_FAILED',
            { output, error }
          ));
        }
      });
    });
  }

  /**
   * 提取 PDF 中的原始文本（用于混合策略）
   */
  async extractText(filePath: string, options?: PDFParseOptions): Promise<{
    pageNumber: number;
    text: string;
    blocks: Array<{
      text: string;
      bbox: { x: number; y: number; width: number; height: number };
    }>;
  }[]> {
    const pages = options?.pages;

    const script = `
import sys
import json
try:
    import fitz
except ImportError:
    print(json.dumps({"error": "PyMuPDF not installed"}), file=sys.stderr)
    sys.exit(1)

try:
    doc = fitz.open("${filePath.replace(/"/g, '\\"')}")
    result = []
    
    page_numbers = ${pages ? JSON.stringify(pages) : 'list(range(1, len(doc) + 1))'}
    
    for page_num in page_numbers:
        if page_num < 1 or page_num > len(doc):
            continue
        page = doc.load_page(page_num - 1)
        
        # 获取文本块
        blocks = page.get_text("dict").get("blocks", [])
        text_blocks = []
        for block in blocks:
            if "lines" in block:
                text = ""
                for line in block["lines"]:
                    for span in line["spans"]:
                        text += span["text"]
                    text += "\\n"
                text_blocks.append({
                    "text": text.strip(),
                    "bbox": {
                        "x": block["bbox"][0],
                        "y": block["bbox"][1],
                        "width": block["bbox"][2] - block["bbox"][0],
                        "height": block["bbox"][3] - block["bbox"][1]
                    }
                })
        
        result.append({
            "pageNumber": page_num,
            "text": page.get_text(),
            "blocks": text_blocks
        })
    
    doc.close()
    print(json.dumps(result, ensure_ascii=False))
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
            `Text extraction failed: ${errorOutput}`,
            'PROCESSING_FAILED',
            { filePath, errorOutput }
          ));
          return;
        }

        try {
          const result = JSON.parse(output);
          if (result.error) {
            reject(new OCRError(
              result.error,
              'PROCESSING_FAILED',
              { filePath }
            ));
            return;
          }
          resolve(result);
        } catch (error) {
          reject(new OCRError(
            'Failed to parse text extraction output',
            'PROCESSING_FAILED',
            { output, error }
          ));
        }
      });
    });
  }

  /**
   * 清理临时文件
   */
  async cleanup(): Promise<void> {
    try {
      await fs.rm(this.tempDir, { recursive: true, force: true });
    } catch (error) {
      console.warn('Failed to cleanup temp directory:', error);
    }
  }
}

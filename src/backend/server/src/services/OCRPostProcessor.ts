/**
 * OCR 后处理器
 * 文本清洗、段落合并、格式优化
 */

import { OCRDocumentResult, OCRPageResult } from '@rag/shared';

export class OCRPostProcessor {
  /**
   * 处理 OCR 结果
   */
  async process(result: OCRDocumentResult): Promise<OCRDocumentResult> {
    // 处理每一页
    const processedPages = result.pages.map(page => this.processPage(page));

    // 重新组装文档
    const fullText = processedPages.map(p => p.rawText).join('\\n\\n');
    const structuredText = processedPages.map(p => p.markdown).join('\\n\\n---\\n\\n');

    return {
      ...result,
      pages: processedPages,
      fullText,
      structuredText
    };
  }

  /**
   * 处理单页
   */
  private processPage(page: OCRPageResult): OCRPageResult {
    // 1. 清洗文本块
    const cleanedBlocks = page.textBlocks.map(block => ({
      ...block,
      text: this.cleanText(block.text)
    }));

    // 2. 合并段落
    const mergedElements = this.mergeParagraphs(page.elements);

    // 3. 优化 Markdown
    const markdown = this.optimizeMarkdown(mergedElements, page.tables);

    return {
      ...page,
      textBlocks: cleanedBlocks,
      elements: mergedElements,
      markdown,
      rawText: cleanedBlocks.map(b => b.text).join('\\n')
    };
  }

  /**
   * 清洗文本
   */
  private cleanText(text: string): string {
    if (!text) return '';

    return text
      // 去除多余空格
      .replace(/\\s+/g, ' ')
      // 修复常见 OCR 错误
      .replace(/「/g, '"')
      .replace(/」/g, '"')
      .replace(/『/g, "'")
      .replace(/』/g, "'")
      .replace(/—/g, '-')
      .replace(/……/g, '...')
      // 去除乱码字符（保留中英文、数字、常见标点）
      .replace(/[^\\u4e00-\\u9fa5a-zA-Z0-9\\s\\n\\.,;:!?"\\'()\\[\\]{}【】《》（）]/g, '')
      // 去除首尾空格
      .trim();
  }

  /**
   * 合并段落
   */
  private mergeParagraphs(elements: any[]): any[] {
    const merged: any[] = [];
    let currentParagraph: any = null;

    for (const element of elements) {
      // 标题不合并
      if (element.type === 'title') {
        if (currentParagraph) {
          merged.push(currentParagraph);
          currentParagraph = null;
        }
        merged.push(element);
        continue;
      }

      // 尝试合并到当前段落
      if (currentParagraph) {
        // 检查是否在同一行或相邻行
        const yGap = element.bbox.y - (currentParagraph.bbox.y + currentParagraph.bbox.height);
        
        if (yGap < 20) {  // 行间距小于20像素则合并
          currentParagraph.content += ' ' + element.content;
          currentParagraph.bbox.height = element.bbox.y + element.bbox.height - currentParagraph.bbox.y;
          currentParagraph.confidence = Math.min(currentParagraph.confidence, element.confidence);
        } else {
          merged.push(currentParagraph);
          currentParagraph = { ...element };
        }
      } else {
        currentParagraph = { ...element };
      }
    }

    if (currentParagraph) {
      merged.push(currentParagraph);
    }

    return merged;
  }

  /**
   * 优化 Markdown 格式
   */
  private optimizeMarkdown(elements: any[], tables: any[]): string {
    const lines: string[] = [];

    for (const element of elements) {
      switch (element.type) {
        case 'title':
          const level = element.metadata?.level || 1;
          lines.push(`${'#'.repeat(level)} ${element.content}`);
          lines.push('');
          break;

        case 'paragraph':
          lines.push(element.content);
          lines.push('');
          break;

        case 'list':
          const items = element.metadata?.listItems || [element.content];
          items.forEach((item: string) => {
            lines.push(`- ${item}`);
          });
          lines.push('');
          break;

        default:
          lines.push(element.content);
          lines.push('');
      }
    }

    // 添加表格
    tables.forEach(table => {
      if (table.markdown) {
        lines.push(table.markdown);
        lines.push('');
      }
    });

    return lines.join('\\n');
  }

  /**
   * 提取关键词
   */
  extractKeywords(text: string, maxKeywords: number = 10): string[] {
    // 简单的关键词提取（基于词频）
    // 实际应用中可以使用更复杂的 NLP 方法
    const words = text
      .toLowerCase()
      .replace(/[^\\u4e00-\\u9fa5a-zA-Z\\s]/g, ' ')
      .split(/\\s+/)
      .filter(w => w.length >= 2);

    const frequency: Map<string, number> = new Map();
    words.forEach(word => {
      frequency.set(word, (frequency.get(word) || 0) + 1);
    });

    return Array.from(frequency.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, maxKeywords)
      .map(([word]) => word);
  }

  /**
   * 生成摘要
   */
  generateSummary(text: string, maxLength: number = 200): string {
    // 简单的摘要生成：取前 N 个字符
    // 实际应用可以使用 TextRank 等算法
    if (text.length <= maxLength) {
      return text;
    }

    // 在句子边界截断
    const truncated = text.slice(0, maxLength);
    const lastPeriod = truncated.lastIndexOf('。');
    const lastNewline = truncated.lastIndexOf('\\n');
    const cutPoint = Math.max(lastPeriod, lastNewline);

    if (cutPoint > maxLength * 0.5) {
      return truncated.slice(0, cutPoint + 1);
    }

    return truncated + '...';
  }
}

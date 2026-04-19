/**
 * OCR 管道管理器
 * 整合 PDF 解析、OCR 识别、后处理的完整流程
 */

import { EventEmitter } from 'events';
import {
  OCRDocumentResult,
  OCRConfig,
  OCRSearchChunk,
  DocumentProcessingJob,
  DocumentProcessingStage,
  OCRError
} from '@rag/shared';
import { PDFParserService } from './PDFParserService';
import { PaddleOCRService } from './PaddleOCRService';
import { OCRPostProcessor } from './OCRPostProcessor';
import { TaskQueueService, OCRTask } from './TaskQueueService';

export class OCRPipelineManager {
  private pdfParser: PDFParserService;
  private ocrService: PaddleOCRService;
  private postProcessor: OCRPostProcessor;
  private eventEmitter: EventEmitter;
  private jobs: Map<string, DocumentProcessingJob> = new Map();
  private jobQueue: string[] = [];
  private isProcessing: boolean = false;
  private taskQueueService: TaskQueueService | null = null;

  constructor(eventEmitter: EventEmitter, taskQueueService?: TaskQueueService) {
    this.pdfParser = new PDFParserService();
    this.ocrService = new PaddleOCRService();
    this.postProcessor = new OCRPostProcessor();
    this.eventEmitter = eventEmitter;
    this.taskQueueService = taskQueueService || null;
    
    if (this.taskQueueService) {
      this.taskQueueService.registerOCRJobHandler(this.handleOCRJob.bind(this));
    }
  }

  /**
   * 处理OCR任务 (供TaskQueueService调用)
   */
  private async handleOCRJob(task: OCRTask): Promise<any> {
    const { jobId, filePath, config } = task;
    let job = this.jobs.get(jobId);
    if (!job) {
      const documentId = `doc_${Date.now()}`;
      job = {
        jobId,
        documentId,
        filePath,
        status: 'processing',
        stages: [
          { name: 'parse', status: 'pending', progress: 0 },
          { name: 'convert', status: 'pending', progress: 0 },
          { name: 'ocr', status: 'pending', progress: 0 },
          { name: 'structure', status: 'pending', progress: 0 },
          { name: 'postprocess', status: 'pending', progress: 0 }
        ],
        createdAt: Date.now(),
        updatedAt: Date.now()
      };
      this.jobs.set(jobId, job);
    }
    try {
      await this.processJob(job);
      return { success: true, jobId };
    } catch (error) {
      // Ensure job status is updated
      job.status = 'failed';
      job.error = error instanceof Error ? error.message : 'Unknown error';
      job.updatedAt = Date.now();
      throw error;
    }
  }

  /**
   * 初始化 OCR 管道
   */
  async initialize(): Promise<void> {
    await this.pdfParser.initialize();
    await this.ocrService.initialize();
  }

  /**
   * 提交文档处理任务
   */
  async submitJob(
    filePath: string,
    config?: Partial<OCRConfig>
  ): Promise<DocumentProcessingJob> {
    const jobId = `job_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    const documentId = `doc_${Date.now()}`;

    const job: DocumentProcessingJob = {
      jobId,
      documentId,
      filePath,
      status: 'queued',
      stages: [
        { name: 'parse', status: 'pending', progress: 0 },
        { name: 'convert', status: 'pending', progress: 0 },
        { name: 'ocr', status: 'pending', progress: 0 },
        { name: 'structure', status: 'pending', progress: 0 },
        { name: 'postprocess', status: 'pending', progress: 0 }
      ],
      createdAt: Date.now(),
      updatedAt: Date.now()
    };

    this.jobs.set(jobId, job);

    // 广播任务创建事件
    this.eventEmitter.emit('ocr:job_created', {
      jobId,
      documentId,
      filePath,
      timestamp: Date.now()
    });

    if (this.taskQueueService) {
      // 使用 BullMQ 队列异步处理
      try {
        await this.taskQueueService.addOCRTask({
          jobId,
          filePath,
          config
        });
        console.log(`[OCRPipeline] OCR job ${jobId} added to BullMQ queue`);
      } catch (error) {
        job.status = 'failed';
        job.error = `Failed to queue job: ${error instanceof Error ? error.message : String(error)}`;
        job.updatedAt = Date.now();
        console.error(`[OCRPipeline] Failed to add OCR task to queue:`, error);
      }
    } else {
      // 使用内部队列（向后兼容）
      this.jobQueue.push(jobId);
      this.processQueue();
    }

    return job;
  }

  /**
   * 获取任务状态
   */
  getJob(jobId: string): DocumentProcessingJob | undefined {
    return this.jobs.get(jobId);
  }

  /**
   * 获取所有任务
   */
  getAllJobs(): DocumentProcessingJob[] {
    return Array.from(this.jobs.values());
  }

  /**
   * 处理队列
   */
  private async processQueue(): Promise<void> {
    if (this.isProcessing || this.jobQueue.length === 0) {
      return;
    }

    this.isProcessing = true;

    while (this.jobQueue.length > 0) {
      const jobId = this.jobQueue.shift()!;
      const job = this.jobs.get(jobId);

      if (!job) continue;

      try {
        await this.processJob(job);
      } catch (error) {
        console.error(`[OCRPipeline] Job ${jobId} failed:`, error);
        
        job.status = 'failed';
        job.error = error instanceof Error ? error.message : 'Unknown error';
        job.updatedAt = Date.now();

        this.eventEmitter.emit('ocr:job_failed', {
          jobId,
          error: job.error,
          timestamp: Date.now()
        });
      }
    }

    this.isProcessing = false;
  }

  /**
   * 处理单个任务
   */
  private async processJob(job: DocumentProcessingJob): Promise<void> {
    job.status = 'processing';
    job.updatedAt = Date.now();

    this.eventEmitter.emit('ocr:job_started', {
      jobId: job.jobId,
      documentId: job.documentId,
      timestamp: Date.now()
    });

    // Stage 1: 解析 PDF
    await this.updateStage(job, 'parse', 'processing', 0);
    const pdfInfo = await this.pdfParser.parsePDF(job.filePath);
    await this.updateStage(job, 'parse', 'completed', 100);

    // Stage 2: 转换为图片
    await this.updateStage(job, 'convert', 'processing', 0);
    const tempDir = `/tmp/rag-ocr/${job.documentId}`;
    const images = await this.pdfParser.convertToImages(
      job.filePath,
      tempDir,
      { dpi: 300 }
    );
    await this.updateStage(job, 'convert', 'completed', 100);

    // Stage 3: OCR 识别
    await this.updateStage(job, 'ocr', 'processing', 0);
    const ocrResult = await this.ocrService.processPDF(job.filePath);
    await this.updateStage(job, 'ocr', 'completed', 100);

    // Stage 4: 结构分析
    await this.updateStage(job, 'structure', 'processing', 0);
    // 结构分析已在 OCR 服务中完成
    await this.updateStage(job, 'structure', 'completed', 100);

    // Stage 5: 后处理
    await this.updateStage(job, 'postprocess', 'processing', 0);
    const processedResult = await this.postProcessor.process(ocrResult);
    await this.updateStage(job, 'postprocess', 'completed', 100);

    // 完成任务
    job.status = 'completed';
    job.result = processedResult;
    job.updatedAt = Date.now();

    this.eventEmitter.emit('ocr:job_completed', {
      jobId: job.jobId,
      documentId: job.documentId,
      result: processedResult,
      timestamp: Date.now()
    });

    // 广播到仪表盘
    this.eventEmitter.emit('dashboard', {
      type: 'ocr_complete',
      sessionId: job.documentId,
      timestamp: Date.now(),
      payload: {
        jobId: job.jobId,
        stats: processedResult.stats
      }
    });
  }

  /**
   * 更新任务阶段状态
   */
  private async updateStage(
    job: DocumentProcessingJob,
    stageName: string,
    status: DocumentProcessingStage['status'],
    progress: number
  ): Promise<void> {
    const stage = job.stages.find(s => s.name === stageName);
    if (stage) {
      stage.status = status;
      stage.progress = progress;
      
      if (status === 'processing') {
        stage.startTime = Date.now();
      } else if (status === 'completed' || status === 'failed') {
        stage.endTime = Date.now();
      }
    }

    job.updatedAt = Date.now();

    this.eventEmitter.emit('ocr:stage_update', {
      jobId: job.jobId,
      stage: stageName,
      status,
      progress,
      timestamp: Date.now()
    });
  }

  /**
   * 将 OCR 结果转换为检索块
   */
  convertToSearchChunks(result: OCRDocumentResult): OCRSearchChunk[] {
    const chunks: OCRSearchChunk[] = [];

    result.pages.forEach(page => {
      // 1. 文本块
      page.elements.forEach((element, idx) => {
        const chunk: OCRSearchChunk = {
          id: `chunk_${result.documentId}_${page.pageNumber}_${idx}`,
          text: element.content,
          pageNumber: page.pageNumber,
          elementType: element.type,
          bbox: element.bbox,
          confidence: element.confidence,
          source: result.fileName,
          context: {
            before: '',
            after: ''
          },
          metadata: {
            isTitle: element.type === 'title',
            isTable: element.type === 'table'
          }
        };

        // 添加上下文
        if (idx > 0) {
          chunk.context.before = page.elements[idx - 1].content.slice(-100);
        }
        if (idx < page.elements.length - 1) {
          chunk.context.after = page.elements[idx + 1].content.slice(0, 100);
        }

        chunks.push(chunk);
      });

      // 2. 表格单独处理
      page.tables.forEach((table, idx) => {
        chunks.push({
          id: `chunk_${result.documentId}_${page.pageNumber}_table_${idx}`,
          text: table.markdown || table.html || '',
          pageNumber: page.pageNumber,
          elementType: 'table',
          bbox: table.bbox,
          confidence: 0.9,
          source: result.fileName,
          context: { before: '', after: '' },
          metadata: {
            isTable: true,
            tableData: table
          }
        });
      });
    });

    return chunks;
  }

  /**
   * 批量处理多个文档
   */
  async batchProcess(
    filePaths: string[],
    config?: Partial<OCRConfig>
  ): Promise<DocumentProcessingJob[]> {
    const jobs: DocumentProcessingJob[] = [];

    for (const filePath of filePaths) {
      const job = await this.submitJob(filePath, config);
      jobs.push(job);
    }

    return jobs;
  }

  /**
   * 清理资源
   */
  async cleanup(): Promise<void> {
    await this.ocrService.cleanup();
    await this.pdfParser.cleanup();
  }
}

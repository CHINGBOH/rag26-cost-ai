/**
 * 任务队列服务
 * 使用BullMQ实现异步任务处理
 */

import { Queue, Worker, Job, QueueEvents } from 'bullmq';
import { EventEmitter } from 'events';
import Redis from 'ioredis';

interface TaskQueueConfig {
  redisUrl: string;
  concurrency: number;
}

interface RetrievalTask {
  type: 'retrieval';
  sessionId: string;
  query: string;
  topK: number;
}

interface GenerationTask {
  type: 'generation';
  sessionId: string;
  query: string;
  chunks: any[];
}

interface EvaluationTask {
  type: 'evaluation';
  sessionId: string;
  query: string;
  chunks: any[];
  answer: string;
  historyRounds: number;
}

export interface OCRTask {
  type: 'ocr';
  jobId: string;
  filePath: string;
  config?: any;
}

type Task = RetrievalTask | GenerationTask | EvaluationTask | OCRTask;

export class TaskQueueService {
  private redis: Redis;
  private queues: Map<string, Queue> = new Map();
  private workers: Map<string, Worker> = new Map();
  private eventEmitter: EventEmitter;
  private config: TaskQueueConfig;
  private ocrJobHandler: ((job: OCRTask) => Promise<any>) | null = null;

  constructor(eventEmitter: EventEmitter, config?: Partial<TaskQueueConfig>) {
    this.eventEmitter = eventEmitter;
    this.config = {
      redisUrl: config?.redisUrl || process.env.REDIS_URL || 'redis://localhost:6379',
      concurrency: config?.concurrency || 3
    };

    this.redis = new Redis(this.config.redisUrl, {
      maxRetriesPerRequest: null,
      enableReadyCheck: false
    });

    this.initializeQueues();
  }

  /**
   * 注册OCR任务处理器
   */
  registerOCRJobHandler(handler: (job: OCRTask) => Promise<any>): void {
    this.ocrJobHandler = handler;
  }

  /**
   * 初始化队列
   */
  private initializeQueues() {
    // 检索队列
    const retrievalQueue = new Queue('retrieval', { connection: this.redis });
    this.queues.set('retrieval', retrievalQueue);

    // 生成队列
    const generationQueue = new Queue('generation', { connection: this.redis });
    this.queues.set('generation', generationQueue);

    // 评估队列
    const evaluationQueue = new Queue('evaluation', { connection: this.redis });
    this.queues.set('evaluation', evaluationQueue);

    // OCR 队列
    const ocrQueue = new Queue('ocr', { connection: this.redis });
    this.queues.set('ocr', ocrQueue);

    // 创建Worker处理器
    this.createWorkers();

    console.log('[TaskQueueService] 队列初始化完成');
  }

  /**
   * 创建Workers
   */
  private createWorkers() {
    // 检索Worker
    const retrievalWorker = new Worker(
      'retrieval',
      async (job: Job<RetrievalTask>) => {
        const { sessionId, query, topK } = job.data;
        console.log(`[Worker:retrieval] 处理任务 ${job.id}, session: ${sessionId}`);
        
        this.eventEmitter.emit('task:started', { type: 'retrieval', sessionId, jobId: job.id });
        
        // 实际检索逻辑由RetrievalService处理
        // 这里只负责队列管理
        return { status: 'processing', sessionId, query };
      },
      { connection: this.redis, concurrency: this.config.concurrency }
    );
    this.workers.set('retrieval', retrievalWorker);

    // 生成Worker
    const generationWorker = new Worker(
      'generation',
      async (job: Job<GenerationTask>) => {
        const { sessionId, query, chunks } = job.data;
        console.log(`[Worker:generation] 处理任务 ${job.id}, session: ${sessionId}`);
        
        this.eventEmitter.emit('task:started', { type: 'generation', sessionId, jobId: job.id });
        
        return { status: 'processing', sessionId, query };
      },
      { connection: this.redis, concurrency: this.config.concurrency }
    );
    this.workers.set('generation', generationWorker);

    // 评估Worker
    const evaluationWorker = new Worker(
      'evaluation',
      async (job: Job<EvaluationTask>) => {
        const { sessionId, query, answer } = job.data;
        console.log(`[Worker:evaluation] 处理任务 ${job.id}, session: ${sessionId}`);
        
        this.eventEmitter.emit('task:started', { type: 'evaluation', sessionId, jobId: job.id });
        
        return { status: 'processing', sessionId, query };
      },
      { connection: this.redis, concurrency: 5 }
    );
    this.workers.set('evaluation', evaluationWorker);

    // OCR Worker
    const ocrWorker = new Worker(
      'ocr',
      async (job: Job<OCRTask>) => {
        const { jobId, filePath, config } = job.data;
        console.log(`[Worker:ocr] 处理任务 ${job.id}, jobId: ${jobId}, file: ${filePath}`);
        
        this.eventEmitter.emit('task:started', { type: 'ocr', ocrJobId: jobId, jobId: job.id });

        if (this.ocrJobHandler) {
          try {
            const result = await this.ocrJobHandler(job.data);
            return { status: 'completed', jobId, result };
          } catch (error) {
            throw new Error(`OCR processing failed: ${error instanceof Error ? error.message : String(error)}`);
          }
        } else {
          console.warn('[Worker:ocr] No OCR job handler registered, returning mock result');
          return { status: 'completed', jobId, mock: true };
        }
      },
      { connection: this.redis, concurrency: 2 }
    );
    this.workers.set('ocr', ocrWorker);

    // 监听完成事件
    this.setupEventListeners();
  }

  /**
   * 设置事件监听
   */
  private setupEventListeners() {
    for (const [name, worker] of this.workers) {
      worker.on('completed', (job, result) => {
        console.log(`[Worker:${name}] 任务完成: ${job.id}`);
        this.eventEmitter.emit('task:completed', {
          type: name,
          jobId: job.id,
          result
        });
      });

      worker.on('failed', (job, err) => {
        console.error(`[Worker:${name}] 任务失败: ${job?.id}, 错误: ${err.message}`);
        this.eventEmitter.emit('task:failed', {
          type: name,
          jobId: job?.id,
          error: err.message
        });
      });
    }
  }

  /**
   * 添加检索任务
   */
  async addRetrievalTask(task: Omit<RetrievalTask, 'type'>): Promise<Job> {
    const queue = this.queues.get('retrieval')!;
    return queue.add('retrieval', { type: 'retrieval', ...task }, {
      attempts: 3,
      backoff: {
        type: 'exponential',
        delay: 1000
      }
    });
  }

  /**
   * 添加生成任务
   */
  async addGenerationTask(task: Omit<GenerationTask, 'type'>): Promise<Job> {
    const queue = this.queues.get('generation')!;
    return queue.add('generation', { type: 'generation', ...task }, {
      attempts: 2,
      backoff: {
        type: 'fixed',
        delay: 2000
      }
    });
  }

  /**
   * 添加评估任务
   */
  async addEvaluationTask(task: Omit<EvaluationTask, 'type'>): Promise<Job> {
    const queue = this.queues.get('evaluation')!;
    return queue.add('evaluation', { type: 'evaluation', ...task }, {
      attempts: 3,
      priority: 5 // 评估任务优先级较高
    });
  }

  /**
   * 添加OCR任务
   */
  async addOCRTask(task: Omit<OCRTask, 'type'>): Promise<Job> {
    const queue = this.queues.get('ocr')!;
    return queue.add('ocr', { type: 'ocr', ...task }, {
      attempts: 3,
      backoff: {
        type: 'exponential',
        delay: 5000
      }
    });
  }

  /**
   * 获取队列状态
   */
  async getQueueStatus(queueName: string): Promise<{
    waiting: number;
    active: number;
    completed: number;
    failed: number;
  }> {
    const queue = this.queues.get(queueName);
    if (!queue) {
      throw new Error(`队列 ${queueName} 不存在`);
    }

    const [waiting, active, completed, failed] = await Promise.all([
      queue.getWaitingCount(),
      queue.getActiveCount(),
      queue.getCompletedCount(),
      queue.getFailedCount()
    ]);

    return { waiting, active, completed, failed };
  }

  /**
   * 获取所有队列状态
   */
  async getAllQueueStatus(): Promise<Record<string, any>> {
    const status: Record<string, any> = {};
    
    for (const name of this.queues.keys()) {
      status[name] = await this.getQueueStatus(name);
    }

    return status;
  }

  /**
   * 清理完成的任务
   */
  async cleanCompletedJobs(queueName: string, keepLast: number = 100): Promise<void> {
    const queue = this.queues.get(queueName);
    if (!queue) return;

    await queue.clean(0, keepLast, 'completed');
    console.log(`[TaskQueueService] 清理 ${queueName} 队列的已完成任务`);
  }

  /**
   * 暂停队列
   */
  async pauseQueue(queueName: string): Promise<void> {
    const queue = this.queues.get(queueName);
    if (queue) {
      await queue.pause();
      console.log(`[TaskQueueService] 队列 ${queueName} 已暂停`);
    }
  }

  /**
   * 恢复队列
   */
  async resumeQueue(queueName: string): Promise<void> {
    const queue = this.queues.get(queueName);
    if (queue) {
      await queue.resume();
      console.log(`[TaskQueueService] 队列 ${queueName} 已恢复`);
    }
  }

  /**
   * 关闭所有队列和Workers
   */
  async close(): Promise<void> {
    console.log('[TaskQueueService] 正在关闭...');

    // 关闭Workers
    for (const [name, worker] of this.workers) {
      await worker.close();
      console.log(`[TaskQueueService] Worker ${name} 已关闭`);
    }

    // 关闭队列
    for (const [name, queue] of this.queues) {
      await queue.close();
      console.log(`[TaskQueueService] 队列 ${name} 已关闭`);
    }

    // 关闭Redis连接
    await this.redis.quit();
    console.log('[TaskQueueService] 已完全关闭');
  }
}

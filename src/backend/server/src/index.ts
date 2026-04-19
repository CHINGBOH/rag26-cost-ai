/**
 * RAG Dashboard Server
 * 入口文件 - 安全强化版
 */

import * as fs from 'fs';
import * as path from 'path';

// 手动加载根目录 .env 文件
function loadEnv() {
  const envPath = path.resolve(process.cwd(), '..', '..', '..', '.env');
  if (fs.existsSync(envPath)) {
    const content = fs.readFileSync(envPath, 'utf-8');
    for (const line of content.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const eqIdx = trimmed.indexOf('=');
      if (eqIdx === -1) continue;
      const key = trimmed.slice(0, eqIdx).trim();
      const val = trimmed.slice(eqIdx + 1).trim();
      if (key && process.env[key] === undefined) {
        process.env[key] = val;
      }
    }
  }
}
loadEnv();

import Fastify from 'fastify';
import cors from '@fastify/cors';
// import websocket from '@fastify/websocket';
import rateLimit from '@fastify/rate-limit';
import { EventEmitter } from 'events';
import { pipeline } from 'stream';
import { promisify } from 'util';
import { RecursionController } from './core/RecursionController';
import { PostgresPersistenceService } from './services/PostgresPersistenceService';
import { WebSocketManager } from './services/WebSocketManager';
import { HeartbeatService } from './services/HeartbeatService';
import { OCRPipelineManager } from './services/OCRPipelineManager';
import { PipelineService } from './services/PipelineService';
import { CacheService } from './services/CacheService';
import { TaskQueueService } from './services/TaskQueueService';
import { AuthService } from './services/AuthService';
import { MetricsService } from './services/MetricsService';
import { logger } from './services/LoggerService';
import { successResponse, errorResponse, ErrorCodes } from './types/response';
import { validate, CreateSessionSchema, RecordActivitySchema, LoginSchema, PaginationSchema } from './types/validation';
import { AgentFactory, createFourDatabaseTools, AgentOptions, StructuredOutput } from './modules/agent/src';

// 全局服务实例（用于进程信号处理）
let cacheService: CacheService | null = null;
let taskQueueService: TaskQueueService | null = null;
let pipelineService: PipelineService | null = null;

const pump = promisify(pipeline);

async function main() {
  logger.info('🚀 启动 RAG Dashboard Server...');

  const app = Fastify({
    logger: false, // 使用自定义logger
    requestTimeout: 30000, // 30秒请求超时
    connectionTimeout: 30000 // 30秒连接超时
  });

  // 注册速率限制
  await app.register(rateLimit, {
    max: 100, // 每分钟最多100请求
    timeWindow: '1 minute',
    errorResponseBuilder: (req, context) => {
      return errorResponse(
        ErrorCodes.RATE_LIMITED,
        `请求过于频繁，请${context.after}后再试`,
        { limit: context.max }
      );
    }
  });

  // 注册插件
  await app.register(cors, {
    origin: process.env.CORS_ORIGIN?.split(',') || ['http://localhost:3000'],
    credentials: true
  });
  // await app.register(websocket);

  // 全局错误处理器
  app.setErrorHandler((error, request, reply) => {
    logger.error('请求处理错误', {
      error: error.message,
      stack: error.stack,
      url: request.url,
      method: request.method,
      requestId: request.id
    });

    // 隐藏内部错误细节
    const isDev = process.env.NODE_ENV === 'development';
    const message = isDev ? error.message : '内部服务器错误';

    reply.status(error.statusCode || 500).send(
      errorResponse(
        ErrorCodes.INTERNAL_ERROR,
        message,
        isDev ? { stack: error.stack } : undefined,
        request.id as string
      )
    );
  });

  // 未找到处理器
  app.setNotFoundHandler((request, reply) => {
    reply.status(404).send(
      errorResponse(
        ErrorCodes.NOT_FOUND,
        `接口 ${request.url} 不存在`,
        undefined,
        request.id as string
      )
    );
  });

  // 创建事件总线
  const eventEmitter = new EventEmitter();

  // 初始化缓存服务
  cacheService = new CacheService();
  logger.info('✅ 缓存服务已初始化');

  // 初始化任务队列服务
  try {
    taskQueueService = new TaskQueueService(eventEmitter);
    logger.info('✅ 任务队列服务已初始化');
  } catch (error) {
    logger.warn('⚠️ 任务队列初始化失败，将使用同步处理: ' + (error instanceof Error ? error.message : String(error)));
  }

  // 初始化认证服务
  const authService = new AuthService();
  logger.info('✅ 认证服务已初始化 (默认账号: admin/admin123)');

  // 初始化监控服务
  const metricsService = new MetricsService(eventEmitter);
  logger.info('✅ 监控服务已初始化');

  // 初始化 PostgreSQL 持久化
  const pgPersistence = new PostgresPersistenceService();
  const pgInitialized = await pgPersistence.initialize();
  if (pgInitialized) {
    logger.info('✅ PostgreSQL 持久化已初始化');
  } else {
    logger.warn('⚠️ PostgreSQL 持久化未启用，将使用内存存储');
  }

  // 创建递归控制器（带持久化）
  const controller = new RecursionController(eventEmitter, pgInitialized ? pgPersistence : undefined);
  const restoredCount = await controller.restoreAllActiveSessions();
  if (restoredCount > 0) {
    logger.info(`✅ 已从 PostgreSQL 恢复 ${restoredCount} 个活跃会话`);
  }
  logger.info('✅ 递归控制器已初始化');

  // 创建 WebSocket 网关广播客户端
  const wsManager = new WebSocketManager();

  // 创建心跳服务（真实时间感知）
  const heartbeatService = new HeartbeatService(
    eventEmitter,
    path.resolve(__dirname, '../../..') // 项目根目录
  );
  heartbeatService.start();

  // 监听YOLO事件并广播
  eventEmitter.on('heartbeat:yolo', (data) => {
    wsManager.broadcast({
      type: 'yolo_started',
      sessionId: data.sessionId,
      timestamp: Date.now(),
      payload: data
    });
  });

  eventEmitter.on('yolo:layer_start', (data) => {
    wsManager.broadcast({
      type: 'yolo:layer_start',
      sessionId: data.sessionId,
      timestamp: Date.now(),
      payload: data
    });
  });

  eventEmitter.on('yolo:layer_complete', (data) => {
    wsManager.broadcast({
      type: 'yolo:layer_complete',
      sessionId: data.sessionId,
      timestamp: Date.now(),
      payload: data
    });
  });

  eventEmitter.on('yolo:completed', (data) => {
    wsManager.broadcast({
      type: 'yolo:completed',
      sessionId: data.sessionId,
      timestamp: Date.now(),
      payload: data
    });
  });

  eventEmitter.on('yolo:failed', (data) => {
    wsManager.broadcast({
      type: 'yolo:failed',
      sessionId: data.sessionId,
      timestamp: Date.now(),
      payload: data
    });
  });

  // 创建 OCR 管道管理器（可选，失败不阻止服务启动）
  let ocrManager: OCRPipelineManager | null = null;
  try {
    ocrManager = new OCRPipelineManager(eventEmitter, taskQueueService || undefined);
    await ocrManager.initialize();
    console.log('[OCR] PaddleOCR initialized successfully');
  } catch (error) {
    console.warn('[OCR] PaddleOCR not available, OCR features will be disabled:',
      error instanceof Error ? error.message : String(error));
    console.warn('[OCR] To enable OCR, install: pip install paddleocr');
  }

  // 初始化数据管道服务
  pipelineService = new PipelineService(eventEmitter);
  logger.info('✅ 数据管道服务已初始化');

  // 监听递归事件并广播
  eventEmitter.on('dashboard', (event) => {
    wsManager.broadcast(event);
  });

  // 定期广播系统生命体征
  setInterval(() => {
    const sessions = controller.getAllSessions();
    const activeSessions = sessions.filter(s =>
      s.currentState !== 'completed' && s.currentState !== 'failed'
    );

    const vitals = {
      healthScore: calculateHealthScore(sessions),
      recursionDepth: Math.max(...sessions.map(s => s.currentDepth), 0),
      maxDepthReached: Math.max(...sessions.map(s => s.metrics.maxDepthReached), 0),
      activeTasks: activeSessions.length,
      pendingTasks: sessions.filter(s => s.currentState === 'idle').length,
      completedTasks: sessions.filter(s => s.currentState === 'completed').length,
      confidenceTrend: calculateConfidenceTrend(sessions),
      latency: {
        retrieval: 800,
        generation: 1000,
        evaluation: 300
      }
    };

    wsManager.broadcastVitals(vitals);
  }, 3000);

  // 认证钩子
  app.addHook('preHandler', async (request, reply) => {
    // 公开接口白名单
    const publicPaths = ['/health', '/api/auth/login', '/api/v1/search', '/api/v1/rerank', '/api/v1/evaluate', '/api/v1/decompose', '/api/pipeline/health', '/api/pipeline/stats', '/api/pipeline/evaluation', '/api/agent/run'];
    if (publicPaths.some(path => request.url.startsWith(path))) {
      return;
    }

    // 验证Token
    const authHeader = request.headers.authorization;
    if (!authHeader?.startsWith('Bearer ')) {
      reply.status(401);
      return reply.send(errorResponse(ErrorCodes.AUTHENTICATION_ERROR, '缺少认证Token'));
    }

    const token = authHeader.slice(7);
    const payload = await authService.verifyToken(token);

    if (!payload) {
      reply.status(401);
      return reply.send(errorResponse(ErrorCodes.AUTHENTICATION_ERROR, '无效的Token'));
    }

    // 将用户信息附加到请求
    (request as any).user = payload;
  });

  // ==================== Agent 接口 ====================

  // 运行 Agent (流式)
  app.post('/api/agent/run', async (request, reply) => {
    const body = request.body as {
      query: string;
      model?: string;
      apiKey?: string;
      baseUrl?: string;
      maxIterations?: number;
    };

    if (!body.query) {
      reply.status(400);
      return errorResponse(ErrorCodes.VALIDATION_ERROR, 'query是必需的');
    }

    try {
      const apiKey = body.apiKey || process.env.DEEPSEEK_API_KEY || process.env.OPENAI_API_KEY || process.env.LLM_API_KEY;
      const baseUrl = body.baseUrl || process.env.LLM_BASE_URL || 'https://api.deepseek.com';
      const model = body.model || process.env.LLM_MODEL || 'deepseek-chat';

      if (!apiKey) {
        throw new Error('LLM API Key 未配置。请设置 DEEPSEEK_API_KEY 或 OPENAI_API_KEY 环境变量');
      }

      reply.raw.setHeader('Content-Type', 'text/event-stream');
      reply.raw.setHeader('Cache-Control', 'no-cache');
      reply.raw.setHeader('Connection', 'keep-alive');

      const events: any[] = [];

      const agent = AgentFactory.create('langchain', {
        model,
        apiKey,
        baseUrl
      }, {
        maxIterations: body.maxIterations || 3
      }, (event) => {
        events.push(event);
        reply.raw.write(`data: ${JSON.stringify(event)}\n\n`);
      });

      const result = await agent.run(body.query);

      reply.raw.write(`data: ${JSON.stringify({ type: 'final', result })}\n\n`);
      reply.raw.end();

    } catch (error) {
      if (!reply.raw.headersSent) {
        reply.status(500);
        return errorResponse(
          ErrorCodes.INTERNAL_ERROR,
          'Agent 运行失败',
          error instanceof Error ? error.message : String(error)
        );
      }
      reply.raw.write(`data: ${JSON.stringify({ type: 'error', message: error instanceof Error ? error.message : String(error) })}\n\n`);
      reply.raw.end();
    }
  });

  // 健康检查接口
  app.get('/health', async () => {
    return successResponse({
      status: 'ok',
      timestamp: Date.now(),
      version: '0.2.0'
    });
  });

  // 获取所有会话（带分页）
  app.get('/api/sessions', async (request) => {
    const pagination = validate(PaginationSchema, {
      page: (request.query as any).page,
      pageSize: (request.query as any).pageSize
    });

    const allSessions = controller.getAllSessions();
    const pageNum = (pagination.success ? pagination.data.page : 1) ?? 1;
    const pageSizeNum = (pagination.success ? pagination.data.pageSize : 10) ?? 10;

    const start = (pageNum - 1) * pageSizeNum;
    const end = start + pageSizeNum;
    const paginatedSessions = allSessions.slice(start, end);

    return successResponse(paginatedSessions, {
      pagination: {
        page: pageNum,
        pageSize: pageSizeNum,
        total: allSessions.length,
        totalPages: Math.ceil(allSessions.length / pageSizeNum)
      }
    });
  });

  // 创建新会话
  app.post('/api/sessions', async (request, reply) => {
    const validation = validate(CreateSessionSchema, request.body);

    if (!validation.success) {
      reply.status(400);
      return errorResponse(ErrorCodes.VALIDATION_ERROR, '请求参数错误', validation.errors);
    }

    const { query } = validation.data;

    try {
      const session = controller.createSession(query);

      // 注册到心跳服务（启用30秒沉默检测）
      heartbeatService.registerSession(session.id, query.slice(0, 20).replace(/\s+/g, '-'));

      // 异步启动递归（不等待完成）
      controller.startRecursion(session.id).catch(err => {
        logger.error('启动递归失败', { sessionId: session.id, error: err.message });
      });

      metricsService.recordSessionStarted();

      return successResponse({
        sessionId: session.id,
        status: 'started'
      }, { requestId: session.id });
    } catch (error) {
      reply.status(500);
      return errorResponse(
        ErrorCodes.INTERNAL_ERROR,
        '创建会话失败',
        error instanceof Error ? error.message : String(error)
      );
    }
  });

  // 接收用户活动信号（重置沉默计时器）
  app.post('/api/activity', async (request, reply) => {
    const validation = validate(RecordActivitySchema, request.body);

    if (!validation.success) {
      reply.status(400);
      return errorResponse(ErrorCodes.VALIDATION_ERROR, '请求参数错误', validation.errors);
    }

    const { sessionId } = validation.data;

    try {
      heartbeatService.recordActivity(sessionId);

      return successResponse({
        sessionId,
        silenceDuration: 0,
        timestamp: Date.now()
      });
    } catch (error) {
      reply.status(500);
      return errorResponse(
        ErrorCodes.INTERNAL_ERROR,
        '记录活动失败',
        error instanceof Error ? error.message : String(error)
      );
    }
  });

  // 获取会话心跳状态（沉默时间）
  app.get('/api/heartbeat/:sessionId', async (request, reply) => {
    const { sessionId } = request.params as { sessionId: string };

    // 验证UUID格式
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(sessionId)) {
      reply.status(400);
      return errorResponse(ErrorCodes.VALIDATION_ERROR, '无效的会话ID格式');
    }

    const silenceDuration = heartbeatService.getSilenceDuration(sessionId);

    return successResponse({
      sessionId,
      silenceDuration,
      threshold: 30000,
      remaining: Math.max(0, 30000 - silenceDuration)
    });
  });

  // ==================== OCR 接口 ====================

  // 提交 OCR 任务
  app.post('/api/ocr/jobs', async (request, reply) => {
    if (!ocrManager) {
      reply.status(503);
      return errorResponse(ErrorCodes.SERVICE_UNAVAILABLE, 'OCR服务不可用，请安装paddleocr');
    }

    // 使用更宽松的验证
    const body = request.body as { filePath?: string; config?: any };

    if (!body.filePath || typeof body.filePath !== 'string') {
      reply.status(400);
      return errorResponse(ErrorCodes.VALIDATION_ERROR, 'filePath是必需的且必须是字符串');
    }

    // 安全检查：防止路径遍历
    if (body.filePath.includes('..')) {
      reply.status(400);
      return errorResponse(ErrorCodes.VALIDATION_ERROR, '非法文件路径');
    }

    try {
      const job = await ocrManager.submitJob(body.filePath, body.config);
      return successResponse({ jobId: job.jobId, status: job.status });
    } catch (error) {
      reply.status(500);
      logger.error('OCR任务提交失败', { error: error instanceof Error ? error.message : String(error) });
      return errorResponse(
        ErrorCodes.INTERNAL_ERROR,
        'OCR任务提交失败',
        process.env.NODE_ENV === 'development' ? (error instanceof Error ? error.message : String(error)) : undefined
      );
    }
  });

  // 获取 OCR 任务状态
  app.get('/api/ocr/jobs/:jobId', async (request, reply) => {
    if (!ocrManager) {
      reply.status(503);
      return errorResponse(ErrorCodes.SERVICE_UNAVAILABLE, 'OCR服务不可用');
    }

    const { jobId } = request.params as { jobId: string };

    if (!jobId || typeof jobId !== 'string') {
      reply.status(400);
      return errorResponse(ErrorCodes.VALIDATION_ERROR, 'jobId是必需的');
    }

    const job = ocrManager.getJob(jobId);

    if (!job) {
      reply.status(404);
      return errorResponse(ErrorCodes.NOT_FOUND, '任务不存在');
    }

    return successResponse(job);
  });

  // 获取所有 OCR 任务
  app.get('/api/ocr/jobs', async (request, reply) => {
    if (!ocrManager) {
      reply.status(503);
      return errorResponse(ErrorCodes.SERVICE_UNAVAILABLE, 'OCR服务不可用');
    }
    return successResponse(ocrManager.getAllJobs());
  });

  // ==================== 数据管道接口 ====================

  // 文件上传（支持多文件、高并发）
  app.post('/api/pipeline/upload', async (request, reply) => {
    if (!pipelineService) {
      reply.status(503);
      return errorResponse(ErrorCodes.SERVICE_UNAVAILABLE, '数据管道服务未初始化');
    }

    const body = request.body as { fileId?: string; filename: string; content: string; mimeType: string };
    if (!body.content || !body.filename) {
      reply.status(400);
      return errorResponse(ErrorCodes.VALIDATION_ERROR, '缺少文件内容或文件名');
    }

    const fileId = body.fileId || `file_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

    try {
      // 解码base64内容
      const buffer = Buffer.from(body.content, 'base64');

      // 创建文件任务
      const fileJob = pipelineService.createFileJob(
        fileId,
        body.filename,
        body.mimeType || 'application/octet-stream',
        buffer.length
      );

      // 保存文件到临时目录
      const filePath = pipelineService.getFilePath(fileId);
      if (filePath) {
        fs.writeFileSync(filePath, buffer);
      }

      // 开始处理
      pipelineService.processFile(fileId).catch(console.error);

      return successResponse({
        fileId: fileJob.id,
        status: fileJob.status,
        message: '文件已上传，开始处理'
      });
    } catch (error) {
      reply.status(500);
      return errorResponse(
        ErrorCodes.INTERNAL_ERROR,
        '文件上传失败',
        error instanceof Error ? error.message : String(error)
      );
    }
  });

  // 获取文件处理状态
  app.get('/api/pipeline/files/:fileId', async (request, reply) => {
    if (!pipelineService) {
      reply.status(503);
      return errorResponse(ErrorCodes.SERVICE_UNAVAILABLE, '数据管道服务未初始化');
    }

    const { fileId } = request.params as { fileId: string };
    const file = pipelineService.getFileStatus(fileId);

    if (!file) {
      reply.status(404);
      return errorResponse(ErrorCodes.NOT_FOUND, '文件不存在');
    }

    return successResponse(file);
  });

  // 获取四库健康状态
  app.get('/api/pipeline/health', async () => {
    if (!pipelineService) {
      return errorResponse(ErrorCodes.SERVICE_UNAVAILABLE, '数据管道服务未初始化');
    }

    const health = await pipelineService.getDatabaseHealth();
    return successResponse(health);
  });

  // 获取评估指标
  app.get('/api/pipeline/evaluation', async () => {
    if (!pipelineService) {
      return errorResponse(ErrorCodes.SERVICE_UNAVAILABLE, '数据管道服务未初始化');
    }

    const metrics = await pipelineService.getEvaluationMetrics();
    return successResponse(metrics);
  });

  // 获取管道统计
  app.get('/api/pipeline/stats', async () => {
    if (!pipelineService) {
      return errorResponse(ErrorCodes.SERVICE_UNAVAILABLE, '数据管道服务未初始化');
    }

    const stats = pipelineService.getStats();
    return successResponse(stats);
  });

  // ==================== 认证接口 ====================

  // 用户登录
  app.post('/api/auth/login', async (request, reply) => {
    const validation = validate(LoginSchema, request.body);

    if (!validation.success) {
      reply.status(400);
      return errorResponse(ErrorCodes.VALIDATION_ERROR, '请求参数错误', validation.errors);
    }

    const { username, password } = validation.data;

    const result = await authService.login(username, password);

    if (!result) {
      reply.status(401);
      return errorResponse(ErrorCodes.AUTHENTICATION_ERROR, '登录失败，请检查用户名和密码');
    }

    return successResponse({
      token: result.token,
      user: {
        id: result.user.id,
        username: result.user.username,
        role: result.user.role
      }
    });
  });

  // ==================== LLM 代理接口 ====================

  // LLM聊天代理（保护API Key不暴露在前端）
  app.post('/api/llm/chat', async (request, reply) => {
    const body = request.body as {
      model?: string;
      messages: Array<{ role: string; content: string }>;
      temperature?: number;
      max_tokens?: number;
      stream?: boolean;
    };

    if (!body.messages || !Array.isArray(body.messages)) {
      reply.status(400);
      return errorResponse(ErrorCodes.VALIDATION_ERROR, 'messages是必需的且必须是数组');
    }

    const apiKey = process.env.DEEPSEEK_API_KEY || process.env.OPENAI_API_KEY;
    const baseURL = process.env.LLM_BASE_URL || 'https://api.deepseek.com';

    if (!apiKey) {
      // 降级：返回明确的配置提示，让前端 UI 正常显示
      const notice = '⚠️ LLM API 未配置。请在服务端设置 DEEPSEEK_API_KEY 或 OPENAI_API_KEY 环境变量后重启服务。';
      console.warn('[LLM] API Key 未配置，返回降级提示');
      if (body.stream) {
        reply.header('Content-Type', 'text/event-stream');
        const fallbackId = 'llm-not-configured';
        const chunk = {
          id: fallbackId,
          object: 'chat.completion.chunk',
          created: Math.floor(Date.now() / 1000),
          model: body.model || 'deepseek-chat',
          choices: [{ index: 0, delta: { role: 'assistant', content: notice }, finish_reason: null }]
        };
        const doneChunk = {
          id: fallbackId,
          object: 'chat.completion.chunk',
          created: Math.floor(Date.now() / 1000),
          model: body.model || 'deepseek-chat',
          choices: [{ index: 0, delta: {}, finish_reason: 'stop' }]
        };
        reply.send(`data: ${JSON.stringify(chunk)}\n\ndata: ${JSON.stringify(doneChunk)}\n\ndata: [DONE]\n\n`);
        return;
      }
      return successResponse({
        id: 'llm-not-configured',
        object: 'chat.completion',
        created: Math.floor(Date.now() / 1000),
        model: body.model || 'deepseek-chat',
        choices: [
          {
            index: 0,
            message: { role: 'assistant', content: notice },
            finish_reason: 'stop'
          }
        ],
        usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 }
      });
    }

    try {
      const response = await fetch(`${baseURL}/v1/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${apiKey}`
        },
        body: JSON.stringify({
          model: body.model || 'deepseek-chat',
          messages: body.messages,
          temperature: body.temperature ?? 0.7,
          max_tokens: body.max_tokens ?? 2000,
          stream: body.stream ?? false
        })
      });

      if (!response.ok) {
        const error = await response.text();
        throw new Error(`LLM API Error: ${response.status} - ${error}`);
      }

      if (body.stream) {
        // 流式响应
        reply.header('Content-Type', 'text/event-stream');
        reply.send(response.body);
      } else {
        const data = await response.json();
        return successResponse(data);
      }
    } catch (error) {
      reply.status(500);
      return errorResponse(
        ErrorCodes.INTERNAL_ERROR,
        'LLM调用失败',
        error instanceof Error ? error.message : String(error)
      );
    }
  });

  // ==================== 缓存接口 ====================

  // 获取缓存统计
  app.get('/api/cache/stats', async () => {
    if (!cacheService) {
      return errorResponse(ErrorCodes.SERVICE_UNAVAILABLE, '缓存服务未初始化');
    }
    const stats = await cacheService.getStats();
    return successResponse(stats);
  });

  // 清空缓存
  app.post('/api/cache/flush', async () => {
    if (!cacheService) {
      return errorResponse(ErrorCodes.SERVICE_UNAVAILABLE, '缓存服务未初始化');
    }
    await cacheService.flushAll();
    return successResponse({ message: '缓存已清空' });
  });

  // ==================== 任务队列接口 ====================

  // 获取队列状态
  app.get('/api/queue/status', async () => {
    if (!taskQueueService) {
      return successResponse({ error: '任务队列服务未启用' });
    }
    const status = await taskQueueService.getAllQueueStatus();
    return successResponse(status);
  });

  // ==================== 监控指标接口 ====================

  // Prometheus格式指标（不需要统一格式）
  app.get('/metrics', async () => {
    return metricsService.generatePrometheusFormat();
  });

  // JSON格式指标
  app.get('/api/metrics', async () => {
    return successResponse(metricsService.getAllMetrics());
  });

  // ==================== 系统信息接口 ====================

  // 获取系统状态
  app.get('/api/system/status', async () => {
    const sessions = controller.getAllSessions();
    const activeSessions = sessions.filter(s =>
      s.currentState !== 'completed' && s.currentState !== 'failed'
    );

    return successResponse({
      version: '0.2.0',
      timestamp: Date.now(),
      services: {
        cache: true,
        taskQueue: !!taskQueueService,
        auth: true,
        metrics: true
      },
      sessions: {
        total: sessions.length,
        active: activeSessions.length,
        completed: sessions.filter(s => s.currentState === 'completed').length,
        failed: sessions.filter(s => s.currentState === 'failed').length
      },
      onlineUsers: authService.getOnlineCount()
    });
  });

  // 启动服务器
  const port = parseInt(process.env.PORT || '3001');
  await app.listen({ port, host: '0.0.0.0' });

  logger.info(`
╔══════════════════════════════════════════════════════════╗
║     🚀 RAG Dashboard Server v0.2.0                       ║
║                                                          ║
║     📡 WebSocket Gateway: ws://localhost:8081/ws          ║
║     🌐 HTTP API:   http://localhost:${port}               ║
║     📊 Metrics:    http://localhost:${port}/metrics       ║
║                                                          ║
║     ✅ 已完成的所有功能:                                  ║
║     • 多路召回检索 (Python API)                          ║
║     • LLM生成服务 (OpenAI/Claude/Kimi)                   ║
║     • BullMQ任务队列                                     ║
║     • Redis缓存层                                        ║
║     • 事件总线                                           ║
║     • 会话持久化                                         ║
║     • 用户认证                                           ║
║     • Prometheus监控                                     ║
║     • 结构化日志                                         ║
║                                                          ║
║     📝 默认账号: admin / admin123                        ║
╚══════════════════════════════════════════════════════════╝
  `);

  // 定期记录系统状态
  setInterval(() => {
    const sessions = controller.getAllSessions();
    const activeSessions = sessions.filter(s =>
      s.currentState !== 'completed' && s.currentState !== 'failed'
    );

    metricsService.updateActiveSessions(activeSessions.length);

    logger.debug('系统状态', {
      activeSessions: activeSessions.length,
      totalSessions: sessions.length,
      onlineUsers: authService.getOnlineCount()
    });
  }, 60000); // 每分钟记录一次
}

function calculateHealthScore(sessions: any[]): number {
  if (sessions.length === 0) return 100;

  const failed = sessions.filter(s => s.currentState === 'failed').length;
  const inReview = sessions.filter(s => s.currentState === 'human_review').length;

  return Math.max(0, 100 - failed * 20 - inReview * 10);
}

function calculateConfidenceTrend(sessions: any[]): 'up' | 'down' | 'stable' {
  const completed = sessions.filter(s => s.currentState === 'completed');
  if (completed.length < 2) return 'stable';

  const recent = completed.slice(-3);
  const avg = recent.reduce((sum, s) => sum + (s.metrics?.averageConfidence || 0), 0) / recent.length;

  if (avg > 0.7) return 'up';
  if (avg < 0.5) return 'down';
  return 'stable';
}

// 优雅关闭处理
process.on('SIGTERM', async () => {
  logger.info('收到 SIGTERM 信号，开始优雅关闭...');

  if (taskQueueService) {
    await taskQueueService.close();
  }
  if (cacheService) {
    await cacheService.close();
  }

  logger.info('所有服务已关闭，退出进程');
  process.exit(0);
});

process.on('SIGINT', async () => {
  logger.info('收到 SIGINT 信号，开始优雅关闭...');

  if (taskQueueService) {
    await taskQueueService.close();
  }
  if (cacheService) {
    await cacheService.close();
  }

  logger.info('所有服务已关闭，退出进程');
  process.exit(0);
});

main().catch((error) => {
  logger.error('服务启动失败', { error: error.message, stack: error.stack });
  console.error('详细错误:', error);
  process.exit(1);
});

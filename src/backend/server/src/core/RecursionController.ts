/**
 * 递归控制器
 * 管理多个递归会话的生命周期
 */

import { EventEmitter } from 'events';
import { v4 as uuidv4 } from 'uuid';
import {
  RecursionSession,
  RecursionRound,
  SubQuery,
  RetrievedChunk,
  RoundEvaluation
} from '@rag/shared';
import { createRecursionMachine, RecursionContext } from './StateMachine';
import { createActor, fromPromise } from 'xstate';
import { ExpertJudgmentService } from '../services/ExpertJudgmentService';
import { RetrievalService } from '../services/RetrievalService';
import { LLMService } from '../services/LLMService';
import { PostgresPersistenceService } from '../services/PostgresPersistenceService';

export class RecursionController {
  private sessions: Map<string, RecursionSession> = new Map();
  private actors: Map<string, any> = new Map();
  private eventEmitter: EventEmitter;
  private expertService: ExpertJudgmentService;
  private retrievalService: RetrievalService;
  private llmService: LLMService;
  private cleanupInterval: NodeJS.Timeout | null = null;
  private gatewayUrl: string;
  private persistence: PostgresPersistenceService | null = null;

  constructor(eventEmitter: EventEmitter, persistence?: PostgresPersistenceService) {
    this.eventEmitter = eventEmitter;
    this.gatewayUrl = process.env.WS_GATEWAY_URL || 'http://localhost:8081/broadcast';
    this.expertService = new ExpertJudgmentService();
    this.retrievalService = new RetrievalService();
    this.llmService = new LLMService();
    this.persistence = persistence || null;

    // 启动定期清理
    this.startCleanupTimer();
  }

  /**
   * 异步广播事件到 Go WebSocket 网关，不阻塞状态机
   */
  private broadcastToGateway(event: { type: string; sessionId: string; timestamp: number; payload: any }): void {
    fetch(this.gatewayUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(event)
    }).catch((err) => {
      console.warn('[RecursionController] 转发到网关失败:', err);
    });
  }

  /**
   * 启动清理定时器
   */
  private startCleanupTimer(): void {
    // 每10分钟清理一次过期会话
    this.cleanupInterval = setInterval(() => {
      this.cleanupExpiredSessions();
    }, 10 * 60 * 1000);
  }

  /**
   * 清理过期会话
   */
  private cleanupExpiredSessions(): void {
    const now = Date.now();
    const maxAge = 24 * 60 * 60 * 1000; // 24小时
    let cleanedCount = 0;

    for (const [sessionId, session] of this.sessions) {
      // 清理已完成/失败的过期会话
      const isCompleted = session.currentState === 'completed' || session.currentState === 'failed';
      const isExpired = now - session.updatedAt > maxAge;

      if ((isCompleted && isExpired) || now - session.updatedAt > maxAge * 7) {
        this.sessions.delete(sessionId);
        this.actors.delete(sessionId);
        this.persistence?.deleteSession(sessionId).catch(() => {});
        cleanedCount++;
      }
    }

    if (cleanedCount > 0) {
      console.log(`[RecursionController] 清理了 ${cleanedCount} 个过期会话`);
    }
  }

  /**
   * 停止清理定时器
   */
  stopCleanupTimer(): void {
    if (this.cleanupInterval) {
      clearInterval(this.cleanupInterval);
      this.cleanupInterval = null;
    }
  }

  /**
   * 创建新的递归会话
   */
  createSession(originalQuery: string): RecursionSession {
    const session: RecursionSession = {
      id: uuidv4(),
      originalQuery,
      createdAt: Date.now(),
      updatedAt: Date.now(),
      currentState: 'idle',
      currentDepth: 0,
      rounds: [],
      metrics: {
        totalChunksRetrieved: 0,
        averageConfidence: 0,
        maxDepthReached: 0,
        totalLatency: 0
      },
      anomalies: []
    };

    this.sessions.set(session.id, session);
    this.persistence?.saveSession(session.id, session).catch(err => {
      console.warn('[RecursionController] 持久化新会话失败:', err);
    });
    return session;
  }

  /**
   * 从 PostgreSQL 恢复会话与 Actor
   */
  async restoreSession(sessionId: string): Promise<boolean> {
    if (!this.persistence) return false;
    const persisted = await this.persistence.loadSession(sessionId);
    if (!persisted) return false;

    const session: RecursionSession = persisted.sessionData;
    this.sessions.set(sessionId, session);

    // 如果会话已结束，无需恢复 actor
    if (session.currentState === 'completed' || session.currentState === 'failed') {
      return true;
    }

    const machine = createRecursionMachine(session, this.eventEmitter);
    const options: any = { input: {} };
    if (persisted.snapshot) {
      options.snapshot = persisted.snapshot;
    }

    const actor = createActor(
      machine.provide({
        actors: {
          decomposeQuery: fromPromise(({ input }: { input: RecursionContext }) => this.decomposeQuery(input)),
          dispatchQueries: fromPromise(({ input }: { input: RecursionContext }) => this.dispatchQueries()),
          retrieveChunks: fromPromise(({ input }: { input: RecursionContext }) => this.retrieveChunks(input)),
          rankChunks: fromPromise(({ input }: { input: RecursionContext }) => this.rankChunks(input)),
          generateAnswer: fromPromise(({ input }: { input: RecursionContext }) => this.generateAnswer(input)),
          evaluateRound: fromPromise(({ input }: { input: RecursionContext }) => this.evaluateRound(input)),
          expertJudgment: fromPromise(({ input }: { input: RecursionContext }) => this.expertJudgment(input)),
          queryExternal: fromPromise(({ input }: { input: RecursionContext }) => this.queryExternal(input))
        }
      }),
      options
    );

    this.actors.set(sessionId, actor);
    actor.subscribe((state: any) => {
      console.log(`[Session ${sessionId}] Restored State: ${state.value}`);
      this.persistState(sessionId, state);
    });
    actor.start();
    return true;
  }

  /**
   * 恢复所有活跃的会话
   */
  async restoreAllActiveSessions(): Promise<number> {
    if (!this.persistence) return 0;
    const active = await this.persistence.getActiveSessions();
    let restored = 0;
    for (const record of active) {
      try {
        const ok = await this.restoreSession(record.sessionId);
        if (ok) restored++;
      } catch (err) {
        console.warn(`[RecursionController] 恢复会话 ${record.sessionId} 失败:`, err);
      }
    }
    console.log(`[RecursionController] 已恢复 ${restored}/${active.length} 个活跃会话`);
    return restored;
  }

  private persistState(sessionId: string, state: any): void {
    const session = this.sessions.get(sessionId);
    if (!session || !this.persistence) return;
    const snapshot = state && typeof state.getPersistedSnapshot === 'function'
      ? state.getPersistedSnapshot()
      : undefined;
    this.persistence.saveSession(sessionId, session, snapshot).catch(err => {
      console.warn('[RecursionController] 持久化状态失败:', err);
    });
  }

  /**
   * 启动递归流程
   */
  async startRecursion(sessionId: string): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`Session ${sessionId} not found`);
    }

    const machine = createRecursionMachine(session, this.eventEmitter);
    
    // 创建 actor，传入真实的服务实现 (XState v5)
    const actor = createActor(
      machine.provide({
        actors: {
          decomposeQuery: fromPromise(({ input }: { input: RecursionContext }) => this.decomposeQuery(input)),
          dispatchQueries: fromPromise(({ input }: { input: RecursionContext }) => this.dispatchQueries()),
          retrieveChunks: fromPromise(({ input }: { input: RecursionContext }) => this.retrieveChunks(input)),
          rankChunks: fromPromise(({ input }: { input: RecursionContext }) => this.rankChunks(input)),
          generateAnswer: fromPromise(({ input }: { input: RecursionContext }) => this.generateAnswer(input)),
          evaluateRound: fromPromise(({ input }: { input: RecursionContext }) => this.evaluateRound(input)),
          expertJudgment: fromPromise(({ input }: { input: RecursionContext }) => this.expertJudgment(input)),
          queryExternal: fromPromise(({ input }: { input: RecursionContext }) => this.queryExternal(input))
        }
      }),
      { input: {} }
    );

    this.actors.set(sessionId, actor);

    // 订阅状态变化并持久化
    actor.subscribe((state: any) => {
      console.log(`[Session ${sessionId}] State: ${state.value}`);
      this.persistState(sessionId, state);
    });

    // 启动
    actor.start();
    actor.send({ type: 'START', query: session.originalQuery });
  }

  /**
   * 人工审核响应
   */
  submitHumanReview(sessionId: string, approved: boolean): void {
    const actor = this.actors.get(sessionId);
    if (!actor) {
      throw new Error(`Session ${sessionId} not found`);
    }

    actor.send({ type: 'HUMAN_REVIEW_COMPLETE', approved });
  }

  /**
   * 获取会话状态
   */
  getSession(sessionId: string): RecursionSession | undefined {
    return this.sessions.get(sessionId);
  }

  /**
   * 获取所有会话
   */
  getAllSessions(): RecursionSession[] {
    return Array.from(this.sessions.values());
  }

  // ==================== 真实服务实现 ====================
  
  private async decomposeQuery(ctx: RecursionContext): Promise<RecursionRound> {
    const { session } = ctx;
    console.log(`[RecursionController] 分解查询: "${session.originalQuery.slice(0, 50)}..."`);
    
    const subQueries = await this.retrievalService.decomposeQuery(session.originalQuery);
    
    return {
      roundId: session.currentDepth + 1,
      timestamp: Date.now(),
      subQueries,
      retrievedChunks: [],
      contradictions: []
    };
  }

  private async dispatchQueries(): Promise<void> {
    // 更新子查询状态为处理中
    console.log('[RecursionController] 分发查询到各数据库');
    await delay(100); // 最小延迟确保状态更新
  }

  private async retrieveChunks(ctx: RecursionContext): Promise<RetrievedChunk[]> {
    const { session, currentRound } = ctx;
    
    if (!currentRound) {
      throw new Error('No current round available');
    }

    console.log(`[RecursionController] 执行多路召回检索`);
    
    // 使用主查询进行检索（也可以使用子查询）
    const chunks = await this.retrievalService.retrieve(session.originalQuery, 10);
    
    // 更新指标
    session.metrics.totalChunksRetrieved += chunks.length;
    
    return chunks;
  }

  private async rankChunks(ctx: RecursionContext): Promise<void> {
    const { session, currentRound } = ctx;
    
    if (!currentRound?.retrievedChunks) {
      return;
    }

    console.log(`[RecursionController] 精排 ${currentRound.retrievedChunks.length} 个文档块`);
    
    const ranked = await this.retrievalService.rerank(
      session.originalQuery,
      currentRound.retrievedChunks
    );
    
    currentRound.retrievedChunks = ranked;
  }

  private async generateAnswer(ctx: RecursionContext): Promise<{ answer: string }> {
    const { session, currentRound } = ctx;
    
    if (!currentRound?.retrievedChunks) {
      throw new Error('No retrieved chunks available');
    }

    console.log(`[RecursionController] 生成答案`);
    
    const result = await this.llmService.generateAnswer(
      session.originalQuery,
      currentRound.retrievedChunks,
      {
        previousAnswers: session.rounds.map(r => r.generatedAnswer || ''),
        contradictions: currentRound.contradictions
      }
    );

    return { answer: result.answer };
  }

  private async evaluateRound(ctx: RecursionContext): Promise<RoundEvaluation> {
    const { session, currentRound } = ctx;
    
    if (!currentRound?.retrievedChunks || !currentRound?.generatedAnswer) {
      throw new Error('Missing chunks or answer for evaluation');
    }

    console.log(`[RecursionController] 评估本轮质量`);
    
    const evaluation = await this.retrievalService.evaluateRound(
      session.originalQuery,
      currentRound.retrievedChunks,
      currentRound.generatedAnswer,
      session.rounds.length
    );
    
    // 更新平均置信度
    const totalRounds = session.rounds.length + 1;
    session.metrics.averageConfidence = 
      ((session.metrics.averageConfidence * (totalRounds - 1)) + evaluation.confidence) / totalRounds;
    
    return evaluation;
  }

  private async expertJudgment(ctx: RecursionContext): Promise<any> {
    const { session, currentRound } = ctx;
    
    if (!currentRound?.generatedAnswer || !currentRound?.evaluation) {
      throw new Error('Missing generated answer or evaluation');
    }

    const request = {
      context: {
        originalQuery: session.originalQuery,
        currentDepth: session.currentDepth,
        recursionHistory: session.rounds
      },
      currentState: {
        generatedAnswer: currentRound.generatedAnswer,
        supportingEvidence: currentRound.retrievedChunks,
        contradictionsFound: currentRound.contradictions,
        confidenceSignals: {
          completeness: currentRound.evaluation.completeness,
          consistency: currentRound.evaluation.consistency,
          confidence: currentRound.evaluation.confidence,
          sourceDiversity: currentRound.evaluation.sourceDiversity,
          factConsistency: currentRound.evaluation.factConsistency,
          coverageEstimate: currentRound.evaluation.coverageEstimate
        }
      },
      question: 'should_stop' as const
    };

    const response = await this.expertService.evaluate(request);
    
    // 广播专家判断事件
    const dashboardEvent = {
      type: 'expert_judgment',
      sessionId: session.id,
      timestamp: Date.now(),
      payload: {
        decision: response.decision,
        reasoning: response.reasoning,
        boundaryAssessment: response.boundaryAssessment
      }
    };
    this.eventEmitter.emit('dashboard', dashboardEvent);
    this.broadcastToGateway(dashboardEvent);

    return response;
  }

  private async queryExternal(ctx: RecursionContext): Promise<any> {
    const { session } = ctx;
    console.log(`[RecursionController] 执行外部查询`);
    
    // 这里可以接入网络搜索或外部API
    // 目前使用LLM生成模拟外部查询结果
    const externalResult = await this.llmService.quickAsk(
      `关于"${session.originalQuery}"的最新外部信息（模拟网络搜索结果）`
    );
    
    return { result: externalResult };
  }
}

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

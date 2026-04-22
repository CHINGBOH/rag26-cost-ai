/**
 * 递归控制器
 * startRecursion 已改为调用 Python LangGraph pipeline (/api/v1/rag)
 * XState 相关代码保留但不再用于主流程
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
import { PostgresPersistenceService } from '../services/PostgresPersistenceService';

export class RecursionController {
  private sessions: Map<string, RecursionSession> = new Map();
  private eventEmitter: EventEmitter;
  private cleanupInterval: NodeJS.Timeout | null = null;
  private gatewayUrl: string;
  private ragUrl: string;
  private persistence: PostgresPersistenceService | null = null;

  constructor(eventEmitter: EventEmitter, persistence?: PostgresPersistenceService) {
    this.eventEmitter = eventEmitter;
    this.gatewayUrl = process.env.WS_GATEWAY_URL || 'http://localhost:8081/broadcast';
    this.ragUrl = process.env.RETRIEVAL_URL || 'http://localhost:8002';
    this.persistence = persistence || null;
    this.startCleanupTimer();
  }

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
   * 从 PostgreSQL 恢复会话（LangGraph 模式：加载数据即可，无需恢复 actor）
   */
  async restoreSession(sessionId: string): Promise<boolean> {
    if (!this.persistence) return false;
    const persisted = await this.persistence.loadSession(sessionId);
    if (!persisted) return false;
    this.sessions.set(sessionId, persisted.sessionData as RecursionSession);
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
    this.persistence.saveSession(sessionId, session).catch(err => {
      console.warn('[RecursionController] 持久化状态失败:', err);
    });
  }

  /**
   * 启动 RAG 流程 —— 调用 Python LangGraph pipeline
   */
  async startRecursion(sessionId: string): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (!session) throw new Error(`Session ${sessionId} not found`);

    this.updateSessionState(sessionId, 'retrieving');
    this.broadcastToGateway({ type: 'state_change', sessionId, timestamp: Date.now(), payload: { to: 'retrieving' } });

    try {
      const resp = await fetch(`${this.ragUrl}/api/v1/agent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: session.originalQuery, session_id: sessionId }),
        signal: AbortSignal.timeout(120_000),
      });

      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`RAG pipeline error ${resp.status}: ${text}`);
      }

      const result = await resp.json() as { query: string; answer: string; chunks: any[]; error?: string };

      // 把结果写回 session
      const round: RecursionRound = {
        roundId: session.rounds.length + 1,
        timestamp: Date.now(),
        subQueries: [] as SubQuery[],
        retrievedChunks: result.chunks as RetrievedChunk[],
        generatedAnswer: result.answer,
        contradictions: [],
      };

      const s = this.sessions.get(sessionId)!;
      s.rounds.push(round);
      s.metrics.totalChunksRetrieved = result.chunks.length;
      s.updatedAt = Date.now();

      this.updateSessionState(sessionId, 'completed');
      this.broadcastToGateway({
        type: 'session_completed',
        sessionId,
        timestamp: Date.now(),
        payload: { answer: result.answer, chunks: result.chunks },
      });
      this.eventEmitter.emit('dashboard', {
        type: 'session_completed',
        sessionId,
        timestamp: Date.now(),
        payload: { answer: result.answer, chunks: result.chunks },
      });
      this.persistState(sessionId, null);
    } catch (err) {
      console.error(`[RecursionController] session ${sessionId} failed:`, err);
      this.updateSessionState(sessionId, 'failed');
      this.broadcastToGateway({
        type: 'session_failed',
        sessionId,
        timestamp: Date.now(),
        payload: { error: err instanceof Error ? err.message : String(err) },
      });
    }
  }

  private updateSessionState(sessionId: string, state: string): void {
    const s = this.sessions.get(sessionId);
    if (s) { (s as any).currentState = state; s.updatedAt = Date.now(); }
  }

  /** 人工审核（保留接口，暂不实现） */
  submitHumanReview(_sessionId: string, _approved: boolean): void {
    console.warn('[RecursionController] submitHumanReview: not implemented in LangGraph mode');
  }

  getSession(sessionId: string): RecursionSession | undefined {
    return this.sessions.get(sessionId);
  }

  getAllSessions(): RecursionSession[] {
    return Array.from(this.sessions.values());
  }
}

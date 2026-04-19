/**
 * PostgreSQL 持久化服务测试
 * 需要在环境变量 DATABASE_URL 中配置测试数据库
 */

import { describe, it, expect, beforeAll, afterAll, beforeEach } from 'vitest';
import { PostgresPersistenceService } from '../services/PostgresPersistenceService';

describe('PostgresPersistenceService', () => {
  let service: PostgresPersistenceService;
  let initialized = false;

  beforeAll(async () => {
    service = new PostgresPersistenceService();
    initialized = await service.initialize();
  });

  afterAll(async () => {
    if (initialized) {
      await service.close();
    }
  });

  beforeEach(async () => {
    if (!initialized) return;
    const sessions = await service.getAllSessions();
    for (const s of sessions) {
      await service.deleteSession(s.sessionId);
    }
  });

  it('should initialize gracefully even without database', () => {
    const badService = new PostgresPersistenceService({ host: 'invalid-host-xyz', port: 5432 });
    expect(badService).toBeDefined();
  });

  it('should save and load a session', async () => {
    if (!initialized) {
      console.warn('Skipping test: PostgreSQL not available');
      return;
    }

    const sessionId = 'test-session-1';
    const session = {
      id: sessionId,
      originalQuery: 'test query',
      currentState: 'idle',
      currentDepth: 0,
      createdAt: Date.now(),
      updatedAt: Date.now(),
      rounds: [],
      metrics: { totalChunksRetrieved: 0, averageConfidence: 0, maxDepthReached: 0, totalLatency: 0 },
      anomalies: []
    };

    await service.saveSession(sessionId, session, { value: 'idle' });
    const loaded = await service.loadSession(sessionId);

    expect(loaded).not.toBeNull();
    expect(loaded!.sessionId).toBe(sessionId);
    expect(loaded!.originalQuery).toBe('test query');
    expect(loaded!.currentState).toBe('idle');
    expect(loaded!.snapshot).toEqual({ value: 'idle' });
  });

  it('should return active sessions only', async () => {
    if (!initialized) {
      console.warn('Skipping test: PostgreSQL not available');
      return;
    }

    const activeSession = {
      id: 'active-1',
      originalQuery: 'active',
      currentState: 'decomposing',
      currentDepth: 1,
      createdAt: Date.now(),
      updatedAt: Date.now(),
      rounds: [],
      metrics: { totalChunksRetrieved: 0, averageConfidence: 0, maxDepthReached: 0, totalLatency: 0 },
      anomalies: []
    };

    const completedSession = {
      id: 'completed-1',
      originalQuery: 'completed',
      currentState: 'completed',
      currentDepth: 2,
      createdAt: Date.now(),
      updatedAt: Date.now(),
      rounds: [],
      metrics: { totalChunksRetrieved: 0, averageConfidence: 0, maxDepthReached: 0, totalLatency: 0 },
      anomalies: []
    };

    await service.saveSession('active-1', activeSession);
    await service.saveSession('completed-1', completedSession);

    const active = await service.getActiveSessions();
    expect(active.length).toBe(1);
    expect(active[0].sessionId).toBe('active-1');
  });

  it('should delete a session', async () => {
    if (!initialized) {
      console.warn('Skipping test: PostgreSQL not available');
      return;
    }

    const sessionId = 'to-delete';
    const session = {
      id: sessionId,
      originalQuery: 'delete me',
      currentState: 'idle',
      currentDepth: 0,
      createdAt: Date.now(),
      updatedAt: Date.now(),
      rounds: [],
      metrics: { totalChunksRetrieved: 0, averageConfidence: 0, maxDepthReached: 0, totalLatency: 0 },
      anomalies: []
    };

    await service.saveSession(sessionId, session);
    let loaded = await service.loadSession(sessionId);
    expect(loaded).not.toBeNull();

    await service.deleteSession(sessionId);
    loaded = await service.loadSession(sessionId);
    expect(loaded).toBeNull();
  });
});

/**
 * 会话持久化服务
 * 将会话状态保存到Redis和文件系统
 */

import { CacheService } from './CacheService';
import * as fs from 'fs/promises';
import * as path from 'path';

interface SessionPersistenceConfig {
  cacheDir: string;
  autoSaveInterval: number;
  maxHistorySessions: number;
}

interface SessionSummary {
  sessionId: string;
  query: string;
  state: string;
  depth: number;
  createdAt: number;
  updatedAt: number;
  completed: boolean;
}

export class SessionPersistenceService {
  private cacheService: CacheService;
  private config: SessionPersistenceConfig;
  private autoSaveTimers: Map<string, NodeJS.Timeout> = new Map();

  constructor(cacheService: CacheService, config?: Partial<SessionPersistenceConfig>) {
    this.cacheService = cacheService;
    this.config = {
      cacheDir: config?.cacheDir || './data/sessions',
      autoSaveInterval: config?.autoSaveInterval || 30000, // 30秒
      maxHistorySessions: config?.maxHistorySessions || 100
    };

    this.ensureCacheDir();
  }

  /**
   * 确保缓存目录存在
   */
  private async ensureCacheDir(): Promise<void> {
    try {
      await fs.mkdir(this.config.cacheDir, { recursive: true });
    } catch (error) {
      console.error('[SessionPersistence] 创建缓存目录失败:', error);
    }
  }

  /**
   * 保存会话（立即）
   */
  async saveSession(sessionId: string, session: any): Promise<void> {
    // 保存到Redis
    await this.cacheService.cacheSession(sessionId, session);
    
    // 保存到文件
    await this.saveToFile(sessionId, session);
    
    // 更新会话索引
    await this.updateSessionIndex(sessionId, session);
  }

  /**
   * 加载会话
   */
  async loadSession(sessionId: string): Promise<any | null> {
    // 先尝试从Redis加载
    let session = await this.cacheService.getCachedSession(sessionId);
    
    if (session) {
      console.log(`[SessionPersistence] 从Redis加载会话: ${sessionId}`);
      return session;
    }
    
    // 从文件加载
    session = await this.loadFromFile(sessionId);
    
    if (session) {
      console.log(`[SessionPersistence] 从文件加载会话: ${sessionId}`);
      // 重新缓存到Redis
      await this.cacheService.cacheSession(sessionId, session);
      return session;
    }
    
    return null;
  }

  /**
   * 删除会话
   */
  async deleteSession(sessionId: string): Promise<void> {
    // 删除Redis缓存
    await this.cacheService.deleteSession(sessionId);
    
    // 删除文件
    const filePath = this.getSessionFilePath(sessionId);
    try {
      await fs.unlink(filePath);
    } catch (error) {
      // 文件可能不存在，忽略错误
    }
    
    // 从索引中移除
    await this.removeFromIndex(sessionId);
    
    // 清除自动保存定时器
    this.stopAutoSave(sessionId);
  }

  /**
   * 获取所有会话摘要
   */
  async getAllSessions(): Promise<SessionSummary[]> {
    try {
      const indexPath = path.join(this.config.cacheDir, 'index.json');
      const data = await fs.readFile(indexPath, 'utf-8');
      const index = JSON.parse(data);
      return Object.values(index.sessions || {});
    } catch (error) {
      return [];
    }
  }

  /**
   * 获取活跃会话（未完成的）
   */
  async getActiveSessions(): Promise<SessionSummary[]> {
    const all = await this.getAllSessions();
    return all.filter(s => !s.completed);
  }

  /**
   * 获取会话历史
   */
  async getSessionHistory(limit: number = 10): Promise<SessionSummary[]> {
    const all = await this.getAllSessions();
    return all
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .slice(0, limit);
  }

  /**
   * 开始自动保存
   */
  startAutoSave(sessionId: string, getSessionFn: () => any): void {
    // 清除现有的定时器
    this.stopAutoSave(sessionId);
    
    const timer = setInterval(async () => {
      try {
        const session = getSessionFn();
        if (session) {
          await this.saveSession(sessionId, session);
          console.log(`[SessionPersistence] 自动保存会话: ${sessionId}`);
        }
      } catch (error) {
        console.error(`[SessionPersistence] 自动保存失败 (${sessionId}):`, error);
      }
    }, this.config.autoSaveInterval);
    
    this.autoSaveTimers.set(sessionId, timer);
  }

  /**
   * 停止自动保存
   */
  stopAutoSave(sessionId: string): void {
    const timer = this.autoSaveTimers.get(sessionId);
    if (timer) {
      clearInterval(timer);
      this.autoSaveTimers.delete(sessionId);
    }
  }

  /**
   * 保存到文件
   */
  private async saveToFile(sessionId: string, session: any): Promise<void> {
    const filePath = this.getSessionFilePath(sessionId);
    await fs.writeFile(filePath, JSON.stringify(session, null, 2), 'utf-8');
  }

  /**
   * 从文件加载
   */
  private async loadFromFile(sessionId: string): Promise<any | null> {
    try {
      const filePath = this.getSessionFilePath(sessionId);
      const data = await fs.readFile(filePath, 'utf-8');
      return JSON.parse(data);
    } catch (error) {
      return null;
    }
  }

  /**
   * 获取会话文件路径
   */
  private getSessionFilePath(sessionId: string): string {
    return path.join(this.config.cacheDir, `${sessionId}.json`);
  }

  /**
   * 更新会话索引
   */
  private async updateSessionIndex(sessionId: string, session: any): Promise<void> {
    const indexPath = path.join(this.config.cacheDir, 'index.json');
    
    let index: { sessions: Record<string, SessionSummary> } = { sessions: {} };
    
    try {
      const data = await fs.readFile(indexPath, 'utf-8');
      index = JSON.parse(data);
    } catch (error) {
      // 索引文件不存在，创建新的
    }
    
    index.sessions[sessionId] = {
      sessionId,
      query: session.originalQuery,
      state: session.currentState,
      depth: session.currentDepth,
      createdAt: session.createdAt,
      updatedAt: Date.now(),
      completed: session.currentState === 'completed' || session.currentState === 'failed'
    };
    
    await fs.writeFile(indexPath, JSON.stringify(index, null, 2), 'utf-8');
  }

  /**
   * 从索引中移除
   */
  private async removeFromIndex(sessionId: string): Promise<void> {
    const indexPath = path.join(this.config.cacheDir, 'index.json');
    
    try {
      const data = await fs.readFile(indexPath, 'utf-8');
      const index = JSON.parse(data);
      delete index.sessions[sessionId];
      await fs.writeFile(indexPath, JSON.stringify(index, null, 2), 'utf-8');
    } catch (error) {
      // 忽略错误
    }
  }

  /**
   * 清理旧会话
   */
  async cleanupOldSessions(keepDays: number = 7): Promise<void> {
    const all = await this.getAllSessions();
    const cutoff = Date.now() - (keepDays * 24 * 60 * 60 * 1000);
    
    for (const session of all) {
      if (session.updatedAt < cutoff) {
        console.log(`[SessionPersistence] 清理旧会话: ${session.sessionId}`);
        await this.deleteSession(session.sessionId);
      }
    }
  }

  /**
   * 导出会话
   */
  async exportSession(sessionId: string): Promise<string> {
    const session = await this.loadSession(sessionId);
    if (!session) {
      throw new Error(`会话不存在: ${sessionId}`);
    }
    return JSON.stringify(session, null, 2);
  }

  /**
   * 导入会话
   */
  async importSession(sessionData: string): Promise<string> {
    const session = JSON.parse(sessionData);
    const newSessionId = `imported_${Date.now()}`;
    session.id = newSessionId;
    session.createdAt = Date.now();
    session.updatedAt = Date.now();
    
    await this.saveSession(newSessionId, session);
    return newSessionId;
  }

  /**
   * 关闭服务
   */
  async close(): Promise<void> {
    // 停止所有自动保存
    for (const [sessionId, timer] of this.autoSaveTimers) {
      clearInterval(timer);
      console.log(`[SessionPersistence] 停止自动保存: ${sessionId}`);
    }
    this.autoSaveTimers.clear();
  }
}

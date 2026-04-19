/**
 * PostgreSQL 持久化服务
 * 为 XState 递归会话提供持久化存储与恢复能力
 */

import { Pool, PoolClient } from 'pg';

export interface PersistedSession {
  sessionId: string;
  originalQuery: string;
  currentState: string;
  currentDepth: number;
  sessionData: any;
  snapshot: any | null;
  createdAt: number;
  updatedAt: number;
}

export interface PostgresConfig {
  connectionString?: string;
  host?: string;
  port?: number;
  database?: string;
  user?: string;
  password?: string;
  ssl?: boolean;
}

export class PostgresPersistenceService {
  private pool: Pool | null = null;
  private isConnected = false;

  constructor(config?: PostgresConfig) {
    const connectionString = config?.connectionString || process.env.DATABASE_URL;
    if (connectionString) {
      this.pool = new Pool({ connectionString, ssl: config?.ssl ?? false });
    } else if (config?.host) {
      this.pool = new Pool({
        host: config.host,
        port: config.port || 5432,
        database: config.database || 'rag_dashboard',
        user: config.user || 'postgres',
        password: config.password || '',
        ssl: config?.ssl ?? false,
      });
    } else {
      console.warn('[PostgresPersistence] No PostgreSQL configuration provided; persistence disabled.');
    }
  }

  /**
   * 初始化数据库表
   */
  async initialize(): Promise<boolean> {
    if (!this.pool) return false;
    try {
      const client = await this.pool.connect();
      try {
        await client.query(`
          CREATE TABLE IF NOT EXISTS recursion_sessions (
            session_id UUID PRIMARY KEY,
            original_query TEXT NOT NULL,
            current_state VARCHAR(50) NOT NULL,
            current_depth INTEGER DEFAULT 0,
            session_data JSONB NOT NULL,
            snapshot JSONB,
            created_at BIGINT NOT NULL,
            updated_at BIGINT NOT NULL
          );
        `);
        await client.query(`
          CREATE INDEX IF NOT EXISTS idx_recursion_sessions_state
          ON recursion_sessions(current_state);
        `);
        await client.query(`
          CREATE INDEX IF NOT EXISTS idx_recursion_sessions_updated_at
          ON recursion_sessions(updated_at DESC);
        `);
        this.isConnected = true;
        console.log('[PostgresPersistence] Database initialized successfully');
        return true;
      } finally {
        client.release();
      }
    } catch (error) {
      console.warn('[PostgresPersistence] Failed to initialize database:', (error as Error).message);
      this.isConnected = false;
      return false;
    }
  }

  /**
   * 保存会话（包含 XState snapshot）
   */
  async saveSession(sessionId: string, session: any, snapshot?: any): Promise<void> {
    if (!this.pool || !this.isConnected) return;
    const query = `
      INSERT INTO recursion_sessions (
        session_id, original_query, current_state, current_depth,
        session_data, snapshot, created_at, updated_at
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
      ON CONFLICT (session_id) DO UPDATE SET
        original_query = EXCLUDED.original_query,
        current_state = EXCLUDED.current_state,
        current_depth = EXCLUDED.current_depth,
        session_data = EXCLUDED.session_data,
        snapshot = EXCLUDED.snapshot,
        updated_at = EXCLUDED.updated_at;
    `;
    await this.pool.query(query, [
      sessionId,
      session.originalQuery || '',
      session.currentState || 'idle',
      session.currentDepth || 0,
      JSON.stringify(session),
      snapshot ? JSON.stringify(snapshot) : null,
      session.createdAt || Date.now(),
      Date.now(),
    ]);
  }

  /**
   * 加载会话
   */
  async loadSession(sessionId: string): Promise<PersistedSession | null> {
    if (!this.pool || !this.isConnected) return null;
    const result = await this.pool.query(
      `SELECT * FROM recursion_sessions WHERE session_id = $1`,
      [sessionId]
    );
    if (result.rows.length === 0) return null;
    return this.rowToSession(result.rows[0]);
  }

  /**
   * 获取所有会话摘要
   */
  async getAllSessions(): Promise<PersistedSession[]> {
    if (!this.pool || !this.isConnected) return [];
    const result = await this.pool.query(
      `SELECT * FROM recursion_sessions ORDER BY updated_at DESC`
    );
    return result.rows.map(r => this.rowToSession(r));
  }

  /**
   * 获取活跃会话（未完成的）
   */
  async getActiveSessions(): Promise<PersistedSession[]> {
    if (!this.pool || !this.isConnected) return [];
    const result = await this.pool.query(
      `SELECT * FROM recursion_sessions WHERE current_state NOT IN ('completed', 'failed') ORDER BY updated_at DESC`
    );
    return result.rows.map(r => this.rowToSession(r));
  }

  /**
   * 删除会话
   */
  async deleteSession(sessionId: string): Promise<void> {
    if (!this.pool || !this.isConnected) return;
    await this.pool.query(
      `DELETE FROM recursion_sessions WHERE session_id = $1`,
      [sessionId]
    );
  }

  /**
   * 清理旧会话
   */
  async cleanupOldSessions(keepDays: number = 7): Promise<void> {
    if (!this.pool || !this.isConnected) return;
    const cutoff = Date.now() - keepDays * 24 * 60 * 60 * 1000;
    const result = await this.pool.query(
      `DELETE FROM recursion_sessions WHERE updated_at < $1`,
      [cutoff]
    );
    if ((result.rowCount || 0) > 0) {
      console.log(`[PostgresPersistence] Cleaned up ${result.rowCount} old sessions`);
    }
  }

  /**
   * 关闭连接池
   */
  async close(): Promise<void> {
    if (this.pool) {
      await this.pool.end();
      this.pool = null;
      this.isConnected = false;
    }
  }

  get healthy(): boolean {
    return this.isConnected;
  }

  private rowToSession(row: any): PersistedSession {
    return {
      sessionId: row.session_id,
      originalQuery: row.original_query,
      currentState: row.current_state,
      currentDepth: row.current_depth,
      sessionData: typeof row.session_data === 'string' ? JSON.parse(row.session_data) : row.session_data,
      snapshot: row.snapshot ? (typeof row.snapshot === 'string' ? JSON.parse(row.snapshot) : row.snapshot) : null,
      createdAt: Number(row.created_at),
      updatedAt: Number(row.updated_at),
    };
  }
}

/**
 * Redis缓存服务
 * 实现多级缓存策略
 */

import Redis from 'ioredis';

interface CacheConfig {
  redisUrl: string;
  defaultTTL: number; // 默认过期时间（秒）
  keyPrefix: string;
}

interface CacheEntry<T> {
  data: T;
  timestamp: number;
  ttl: number;
}

export class CacheService {
  private redis: Redis;
  private config: CacheConfig;

  constructor(config?: Partial<CacheConfig>) {
    this.config = {
      redisUrl: config?.redisUrl || process.env.REDIS_URL || 'redis://localhost:6379',
      defaultTTL: config?.defaultTTL || 3600, // 1小时
      keyPrefix: config?.keyPrefix || 'rag:'
    };

    this.redis = new Redis(this.config.redisUrl, {
      retryStrategy: (times) => Math.min(times * 50, 2000),
      maxRetriesPerRequest: 3
    });

    this.redis.on('connect', () => {
      console.log('[CacheService] Redis连接成功');
    });

    this.redis.on('error', (err) => {
      console.error('[CacheService] Redis错误:', err.message);
    });
  }

  /**
   * 生成缓存键
   */
  private key(key: string): string {
    return `${this.config.keyPrefix}${key}`;
  }

  /**
   * 获取缓存
   */
  async get<T>(key: string): Promise<T | null> {
    try {
      const data = await this.redis.get(this.key(key));
      if (!data) return null;
      
      const entry: CacheEntry<T> = JSON.parse(data);
      
      // 检查是否过期
      if (Date.now() - entry.timestamp > entry.ttl * 1000) {
        await this.delete(key);
        return null;
      }
      
      return entry.data;
    } catch (error) {
      console.error('[CacheService] 获取缓存失败:', error);
      return null;
    }
  }

  /**
   * 设置缓存
   */
  async set<T>(key: string, data: T, ttl?: number): Promise<void> {
    try {
      const entry: CacheEntry<T> = {
        data,
        timestamp: Date.now(),
        ttl: ttl || this.config.defaultTTL
      };

      await this.redis.setex(
        this.key(key),
        ttl || this.config.defaultTTL,
        JSON.stringify(entry)
      );
    } catch (error) {
      console.error('[CacheService] 设置缓存失败:', error);
    }
  }

  /**
   * 删除缓存
   */
  async delete(key: string): Promise<void> {
    try {
      await this.redis.del(this.key(key));
    } catch (error) {
      console.error('[CacheService] 删除缓存失败:', error);
    }
  }

  /**
   * 删除多个缓存（支持通配符）
   */
  async deletePattern(pattern: string): Promise<void> {
    try {
      const keys = await this.redis.keys(this.key(pattern));
      if (keys.length > 0) {
        await this.redis.del(...keys);
      }
    } catch (error) {
      console.error('[CacheService] 删除缓存模式失败:', error);
    }
  }

  /**
   * 检查缓存是否存在
   */
  async exists(key: string): Promise<boolean> {
    try {
      const result = await this.redis.exists(this.key(key));
      return result === 1;
    } catch (error) {
      console.error('[CacheService] 检查缓存失败:', error);
      return false;
    }
  }

  /**
   * 获取或设置缓存
   */
  async getOrSet<T>(
    key: string,
    factory: () => Promise<T>,
    ttl?: number
  ): Promise<T> {
    // 先尝试获取缓存
    const cached = await this.get<T>(key);
    if (cached !== null) {
      console.log(`[CacheService] 缓存命中: ${key}`);
      return cached;
    }

    // 执行工厂函数获取数据
    console.log(`[CacheService] 缓存未命中: ${key}`);
    const data = await factory();
    
    // 写入缓存
    await this.set(key, data, ttl);
    
    return data;
  }

  /**
   * 缓存检索结果
   */
  async cacheRetrieval(query: string, results: any[]): Promise<void> {
    const key = `retrieval:${this.hashQuery(query)}`;
    await this.set(key, results, 1800); // 30分钟
  }

  /**
   * 获取缓存的检索结果
   */
  async getCachedRetrieval(query: string): Promise<any[] | null> {
    const key = `retrieval:${this.hashQuery(query)}`;
    return this.get<any[]>(key);
  }

  /**
   * 缓存Embedding
   */
  async cacheEmbedding(text: string, embedding: number[]): Promise<void> {
    const key = `embedding:${this.hashQuery(text)}`;
    await this.set(key, embedding, 86400); // 24小时
  }

  /**
   * 获取缓存的Embedding
   */
  async getCachedEmbedding(text: string): Promise<number[] | null> {
    const key = `embedding:${this.hashQuery(text)}`;
    return this.get<number[]>(key);
  }

  /**
   * 缓存LLM生成结果
   */
  async cacheGeneration(prompt: string, result: string): Promise<void> {
    const key = `llm:${this.hashQuery(prompt)}`;
    await this.set(key, result, 600); // 10分钟
  }

  /**
   * 获取缓存的LLM生成结果
   */
  async getCachedGeneration(prompt: string): Promise<string | null> {
    const key = `llm:${this.hashQuery(prompt)}`;
    return this.get<string>(key);
  }

  /**
   * 缓存会话状态
   */
  async cacheSession(sessionId: string, session: any): Promise<void> {
    const key = `session:${sessionId}`;
    await this.set(key, session, 3600); // 1小时
  }

  /**
   * 获取缓存的会话
   */
  async getCachedSession(sessionId: string): Promise<any | null> {
    const key = `session:${sessionId}`;
    return this.get<any>(key);
  }

  /**
   * 删除会话缓存
   */
  async deleteSession(sessionId: string): Promise<void> {
    await this.delete(`session:${sessionId}`);
  }

  /**
   * 清空所有缓存
   */
  async flushAll(): Promise<void> {
    try {
      await this.redis.flushdb();
      console.log('[CacheService] 所有缓存已清空');
    } catch (error) {
      console.error('[CacheService] 清空缓存失败:', error);
    }
  }

  /**
   * 获取缓存统计
   */
  async getStats(): Promise<{
    keys: number;
    memory: string;
    hitRate?: number;
  }> {
    try {
      const info = await this.redis.info('memory');
      const keys = await this.redis.dbsize();
      
      // 解析内存使用
      const usedMemory = info.match(/used_memory_human:(.+)/)?.[1]?.trim() || '0B';

      return {
        keys,
        memory: usedMemory,
        hitRate: undefined // 需要配合应用层统计
      };
    } catch (error) {
      console.error('[CacheService] 获取统计失败:', error);
      return { keys: 0, memory: '0B' };
    }
  }

  /**
   * 计算查询哈希
   */
  private hashQuery(query: string): string {
    // 简单哈希，生产环境可使用crypto
    let hash = 0;
    for (let i = 0; i < query.length; i++) {
      const char = query.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash;
    }
    return Math.abs(hash).toString(16);
  }

  /**
   * 关闭连接
   */
  async close(): Promise<void> {
    await this.redis.quit();
    console.log('[CacheService] 已关闭');
  }
}

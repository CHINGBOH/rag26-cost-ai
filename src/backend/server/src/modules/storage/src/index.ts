/**
 * 存储模块 - 缓存、队列、持久化统一抽象
 * 提供管道式存储操作
 * 支持内存和Redis两种后端
 */

import { CacheAdapter, QueueAdapter, StoreAdapter } from '../../common/types'
import Redis from 'ioredis'

// ==================== 内存缓存实现 ====================

class MemoryCache<T> implements CacheAdapter<T> {
  private cache: Map<string, { value: T; expires?: number }> = new Map()

  async get(key: string): Promise<T | undefined> {
    const entry = this.cache.get(key)
    if (!entry) return undefined

    if (entry.expires && Date.now() > entry.expires) {
      this.cache.delete(key)
      return undefined
    }

    return entry.value
  }

  async set(key: string, value: T, ttl?: number): Promise<void> {
    this.cache.set(key, {
      value,
      expires: ttl ? Date.now() + ttl * 1000 : undefined
    })
  }

  async delete(key: string): Promise<void> {
    this.cache.delete(key)
  }

  async has(key: string): Promise<boolean> {
    const entry = this.cache.get(key)
    if (!entry) return false

    if (entry.expires && Date.now() > entry.expires) {
      this.cache.delete(key)
      return false
    }

    return true
  }

  async clear(): Promise<void> {
    this.cache.clear()
  }
}

// ==================== 内存队列实现 ====================

class MemoryQueue<T> implements QueueAdapter<T> {
  private queue: T[] = []

  async enqueue(item: T): Promise<void> {
    this.queue.push(item)
  }

  async dequeue(): Promise<T | undefined> {
    return this.queue.shift()
  }

  async peek(): Promise<T | undefined> {
    return this.queue[0]
  }

  async size(): Promise<number> {
    return this.queue.length
  }

  async isEmpty(): Promise<boolean> {
    return this.queue.length === 0
  }
}

// ==================== 内存存储实现 ====================

class MemoryStore<T> implements StoreAdapter<T> {
  private store: Map<string, T> = new Map()

  async save(key: string, value: T): Promise<void> {
    this.store.set(key, value)
  }

  async load(key: string): Promise<T | undefined> {
    return this.store.get(key)
  }

  async delete(key: string): Promise<void> {
    this.store.delete(key)
  }

  async list(): Promise<string[]> {
    return Array.from(this.store.keys())
  }
}

// ==================== Redis 缓存实现 ====================

class RedisCache<T> implements CacheAdapter<T> {
  private client: Redis
  private keyPrefix: string

  constructor(client: Redis, keyPrefix = 'cache:') {
    this.client = client
    this.keyPrefix = keyPrefix
  }

  private toKey(key: string): string {
    return `${this.keyPrefix}${key}`
  }

  async get(key: string): Promise<T | undefined> {
    try {
      const value = await this.client.get(this.toKey(key))
      if (!value) return undefined

      const parsed = JSON.parse(value) as { data: T; expires?: number }
      if (parsed.expires && Date.now() > parsed.expires) {
        await this.client.del(this.toKey(key))
        return undefined
      }

      return parsed.data
    } catch (error) {
      console.error('[RedisCache] get error:', error)
      return undefined
    }
  }

  async set(key: string, value: T, ttl?: number): Promise<void> {
    try {
      const data = {
        data: value,
        expires: ttl ? Date.now() + ttl * 1000 : undefined
      }
      if (ttl) {
        await this.client.setex(this.toKey(key), ttl, JSON.stringify(data))
      } else {
        await this.client.set(this.toKey(key), JSON.stringify(data))
      }
    } catch (error) {
      console.error('[RedisCache] set error:', error)
    }
  }

  async delete(key: string): Promise<void> {
    try {
      await this.client.del(this.toKey(key))
    } catch (error) {
      console.error('[RedisCache] delete error:', error)
    }
  }

  async has(key: string): Promise<boolean> {
    try {
      const exists = await this.client.exists(this.toKey(key))
      return exists === 1
    } catch (error) {
      console.error('[RedisCache] has error:', error)
      return false
    }
  }

  async clear(): Promise<void> {
    try {
      const keys = await this.client.keys(`${this.keyPrefix}*`)
      if (keys.length > 0) {
        await this.client.del(...keys)
      }
    } catch (error) {
      console.error('[RedisCache] clear error:', error)
    }
  }
}

// ==================== Redis 队列实现 ====================

class RedisQueue<T> implements QueueAdapter<T> {
  private client: Redis
  private queueName: string

  constructor(client: Redis, queueName = 'queue:default') {
    this.client = client
    this.queueName = queueName
  }

  async enqueue(item: T): Promise<void> {
    try {
      await this.client.rpush(this.queueName, JSON.stringify(item))
    } catch (error) {
      console.error('[RedisQueue] enqueue error:', error)
    }
  }

  async dequeue(): Promise<T | undefined> {
    try {
      const item = await this.client.lpop(this.queueName)
      if (!item) return undefined
      return JSON.parse(item) as T
    } catch (error) {
      console.error('[RedisQueue] dequeue error:', error)
      return undefined
    }
  }

  async peek(): Promise<T | undefined> {
    try {
      const item = await this.client.lindex(this.queueName, 0)
      if (!item) return undefined
      return JSON.parse(item) as T
    } catch (error) {
      console.error('[RedisQueue] peek error:', error)
      return undefined
    }
  }

  async size(): Promise<number> {
    try {
      return await this.client.llen(this.queueName)
    } catch (error) {
      console.error('[RedisQueue] size error:', error)
      return 0
    }
  }

  async isEmpty(): Promise<boolean> {
    return (await this.size()) === 0
  }
}

// ==================== Redis 存储实现 ====================

class RedisStore<T> implements StoreAdapter<T> {
  private client: Redis
  private keyPrefix: string

  constructor(client: Redis, keyPrefix = 'store:') {
    this.client = client
    this.keyPrefix = keyPrefix
  }

  private toKey(key: string): string {
    return `${this.keyPrefix}${key}`
  }

  async save(key: string, value: T): Promise<void> {
    try {
      await this.client.set(this.toKey(key), JSON.stringify(value))
    } catch (error) {
      console.error('[RedisStore] save error:', error)
    }
  }

  async load(key: string): Promise<T | undefined> {
    try {
      const value = await this.client.get(this.toKey(key))
      if (!value) return undefined
      return JSON.parse(value) as T
    } catch (error) {
      console.error('[RedisStore] load error:', error)
      return undefined
    }
  }

  async delete(key: string): Promise<void> {
    try {
      await this.client.del(this.toKey(key))
    } catch (error) {
      console.error('[RedisStore] delete error:', error)
    }
  }

  async list(): Promise<string[]> {
    try {
      const keys = await this.client.keys(`${this.keyPrefix}*`)
      return keys.map(k => k.slice(this.keyPrefix.length))
    } catch (error) {
      console.error('[RedisStore] list error:', error)
      return []
    }
  }
}

// ==================== Redis 客户端工厂 ====================

let redisClient: Redis | null = null

/**
 * 获取 Redis 客户端单例
 */
export function getRedisClient(): Redis | null {
  if (redisClient) return redisClient

  const redisUrl = process.env.REDIS_URL || 'redis://localhost:6379'

  try {
    redisClient = new Redis(redisUrl, {
      maxRetriesPerRequest: 3,
      retryStrategy: (times) => {
        if (times > 3) {
          console.warn('[Redis] Connection failed after 3 retries')
          return null
        }
        return Math.min(times * 100, 3000)
      }
    })

    redisClient.on('error', (err) => {
      console.error('[Redis] Client error:', err)
    })

    redisClient.on('connect', () => {
      console.log('[Redis] Connected successfully')
    })

    return redisClient
  } catch (error) {
    console.error('[Redis] Failed to create client:', error)
    return null
  }
}

/**
 * 关闭 Redis 客户端
 */
export async function closeRedisClient(): Promise<void> {
  if (redisClient) {
    await redisClient.quit()
    redisClient = null
    console.log('[Redis] Client closed')
  }
}

// ==================== 工厂函数 ====================

export function createCache<T>(type: 'memory' | 'redis' = 'memory'): CacheAdapter<T> {
  if (type === 'memory') {
    return new MemoryCache<T>()
  }

  const client = getRedisClient()
  if (client) {
    return new RedisCache<T>(client)
  }

  // 如果 Redis 连接失败，降级到内存
  console.warn('[Storage] Redis unavailable, falling back to memory cache')
  return new MemoryCache<T>()
}

export function createQueue<T>(type: 'memory' | 'redis' = 'memory'): QueueAdapter<T> {
  if (type === 'memory') {
    return new MemoryQueue<T>()
  }

  const client = getRedisClient()
  if (client) {
    return new RedisQueue<T>(client)
  }

  console.warn('[Storage] Redis unavailable, falling back to memory queue')
  return new MemoryQueue<T>()
}

export function createStore<T>(type: 'memory' | 'redis' | 'file' = 'memory'): StoreAdapter<T> {
  if (type === 'memory') {
    return new MemoryStore<T>()
  }

  const client = getRedisClient()
  if (client) {
    return new RedisStore<T>(client)
  }

  console.warn('[Storage] Redis unavailable, falling back to memory store')
  return new MemoryStore<T>()
}

// ==================== 管道操作 ====================

/**
 * 缓存读取
 */
export function cacheGet<T>(cache: CacheAdapter<T>, key: string) {
  return async function get(): Promise<T | undefined> {
    return cache.get(key)
  }
}

/**
 * 缓存写入
 */
export function cacheSet<T>(cache: CacheAdapter<T>, key: string, ttl?: number) {
  return async function set(value: T): Promise<T> {
    await cache.set(key, value, ttl)
    return value
  }
}

/**
 * 队列入队
 */
export function enqueue<T>(queue: QueueAdapter<T>) {
  return async function add(item: T): Promise<T> {
    await queue.enqueue(item)
    return item
  }
}

/**
 * 队列出队
 */
export function dequeue<T>(queue: QueueAdapter<T>) {
  return async function remove(): Promise<T | undefined> {
    return queue.dequeue()
  }
}

/**
 * 存储保存
 */
export function storeSave<T>(store: StoreAdapter<T>, key: string) {
  return async function save(value: T): Promise<T> {
    await store.save(key, value)
    return value
  }
}

/**
 * 存储加载
 */
export function storeLoad<T>(store: StoreAdapter<T>, key: string) {
  return async function load(): Promise<T | undefined> {
    return store.load(key)
  }
}

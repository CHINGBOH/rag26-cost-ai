/**
 * 存储模块测试
 */

import { describe, it, expect, beforeEach } from 'vitest'
import {
  createCache,
  createQueue,
  createStore,
  cacheGet,
  cacheSet,
  enqueue,
  dequeue,
  storeSave,
  storeLoad
} from '../src'

describe('Storage 模块', () => {
  describe('内存缓存', () => {
    it('应该创建缓存', () => {
      const cache = createCache<string>()
      expect(cache).toBeDefined()
    })

    it('应该设置和获取缓存值', async () => {
      const cache = createCache<string>()
      
      await cache.set('key1', 'value1')
      const value = await cache.get('key1')
      
      expect(value).toBe('value1')
    })

    it('应该检查缓存是否存在', async () => {
      const cache = createCache<string>()
      
      await cache.set('key1', 'value1')
      const exists = await cache.has('key1')
      const notExists = await cache.has('key2')
      
      expect(exists).toBe(true)
      expect(notExists).toBe(false)
    })

    it('应该删除缓存值', async () => {
      const cache = createCache<string>()
      
      await cache.set('key1', 'value1')
      await cache.delete('key1')
      const value = await cache.get('key1')
      
      expect(value).toBeUndefined()
    })

    it('应该清空缓存', async () => {
      const cache = createCache<string>()
      
      await cache.set('key1', 'value1')
      await cache.set('key2', 'value2')
      await cache.clear()
      
      expect(await cache.has('key1')).toBe(false)
      expect(await cache.has('key2')).toBe(false)
    })
  })

  describe('内存队列', () => {
    it('应该创建队列', () => {
      const queue = createQueue<string>()
      expect(queue).toBeDefined()
    })

    it('应该入队和出队', async () => {
      const queue = createQueue<string>()
      
      await queue.enqueue('item1')
      await queue.enqueue('item2')
      
      const item1 = await queue.dequeue()
      const item2 = await queue.dequeue()
      
      expect(item1).toBe('item1')
      expect(item2).toBe('item2')
    })

    it('应该在空队列出队时返回 undefined', async () => {
      const queue = createQueue<string>()
      
      const item = await queue.dequeue()
      
      expect(item).toBeUndefined()
    })

    it('应该获取队列大小', async () => {
      const queue = createQueue<string>()
      
      await queue.enqueue('item1')
      await queue.enqueue('item2')
      
      const size = await queue.size()
      
      expect(size).toBe(2)
    })

    it('应该检查队列是否为空', async () => {
      const queue = createQueue<string>()
      
      const empty1 = await queue.isEmpty()
      await queue.enqueue('item1')
      const empty2 = await queue.isEmpty()
      
      expect(empty1).toBe(true)
      expect(empty2).toBe(false)
    })

    it('应该查看队首元素', async () => {
      const queue = createQueue<string>()
      
      await queue.enqueue('item1')
      await queue.enqueue('item2')
      
      const peeked = await queue.peek()
      const size = await queue.size()
      
      expect(peeked).toBe('item1')
      expect(size).toBe(2) // 队列大小不变
    })
  })

  describe('内存存储', () => {
    it('应该创建存储', () => {
      const store = createStore<string>()
      expect(store).toBeDefined()
    })

    it('应该保存和加载数据', async () => {
      const store = createStore<string>()
      
      await store.save('key1', 'value1')
      const value = await store.load('key1')
      
      expect(value).toBe('value1')
    })

    it('应该删除数据', async () => {
      const store = createStore<string>()
      
      await store.save('key1', 'value1')
      await store.delete('key1')
      const value = await store.load('key1')
      
      expect(value).toBeUndefined()
    })

    it('应该列出所有键', async () => {
      const store = createStore<string>()
      
      await store.save('key1', 'value1')
      await store.save('key2', 'value2')
      
      const keys = await store.list()
      
      expect(keys).toContain('key1')
      expect(keys).toContain('key2')
      expect(keys).toHaveLength(2)
    })
  })

  describe('管道函数', () => {
    it('应该通过管道设置缓存', async () => {
      const cache = createCache<string>()
      
      const setCache = cacheSet(cache, 'key1', 3600)
      const result = await setCache('value1')
      
      expect(result).toBe('value1')
      expect(await cache.get('key1')).toBe('value1')
    })

    it('应该通过管道获取缓存', async () => {
      const cache = createCache<string>()
      await cache.set('key1', 'value1')
      
      const getCache = cacheGet(cache, 'key1')
      const result = await getCache()
      
      expect(result).toBe('value1')
    })

    it('应该通过管道入队', async () => {
      const queue = createQueue<string>()
      
      const enqueueFn = enqueue(queue)
      await enqueueFn('item1')
      
      expect(await queue.size()).toBe(1)
    })

    it('应该通过管道出队', async () => {
      const queue = createQueue<string>()
      await queue.enqueue('item1')
      
      const dequeueFn = dequeue(queue)
      const result = await dequeueFn()
      
      expect(result).toBe('item1')
    })

    it('应该通过管道保存存储', async () => {
      const store = createStore<string>()
      
      const saveStore = storeSave(store, 'key1')
      const result = await saveStore('value1')
      
      expect(result).toBe('value1')
      expect(await store.load('key1')).toBe('value1')
    })

    it('应该通过管道加载存储', async () => {
      const store = createStore<string>()
      await store.save('key1', 'value1')
      
      const loadStore = storeLoad(store, 'key1')
      const result = await loadStore()
      
      expect(result).toBe('value1')
    })
  })
})

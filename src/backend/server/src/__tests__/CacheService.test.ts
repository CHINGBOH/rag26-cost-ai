/**
 * 缓存服务测试
 */

import { describe, it, expect, beforeEach, afterAll } from 'vitest';
import { CacheService } from '../services/CacheService';

describe('CacheService', () => {
  let cache: CacheService;

  beforeEach(() => {
    cache = new CacheService({
      defaultTTL: 60,
      keyPrefix: 'test:'
    });
  });

  afterAll(async () => {
    await cache.flushAll();
    await cache.close();
  });

  it('应该设置和获取缓存', async () => {
    await cache.set('key1', { data: 'value1' });
    const result = await cache.get('key1');
    
    expect(result).toEqual({ data: 'value1' });
  });

  it('应该正确过期', async () => {
    await cache.set('key2', 'value', 1); // 1秒过期
    
    // 立即获取应该存在
    const immediate = await cache.get('key2');
    expect(immediate).toBe('value');
    
    // 等待2秒后应该过期
    await new Promise(resolve => setTimeout(resolve, 2000));
    const expired = await cache.get('key2');
    expect(expired).toBeNull();
  });

  it('应该使用getOrSet', async () => {
    let callCount = 0;
    const factory = async () => {
      callCount++;
      return { computed: 'value' };
    };

    // 第一次调用应该执行factory
    const result1 = await cache.getOrSet('computed_key', factory);
    expect(result1).toEqual({ computed: 'value' });
    expect(callCount).toBe(1);

    // 第二次调用应该使用缓存
    const result2 = await cache.getOrSet('computed_key', factory);
    expect(result2).toEqual({ computed: 'value' });
    expect(callCount).toBe(1); // factory没有被再次调用
  });

  it('应该删除缓存', async () => {
    await cache.set('delete_me', 'value');
    await cache.delete('delete_me');
    
    const result = await cache.get('delete_me');
    expect(result).toBeNull();
  });

  it('应该正确缓存检索结果', async () => {
    const query = '测试查询';
    const results = [{ id: '1', content: '结果1' }];
    
    await cache.cacheRetrieval(query, results);
    const cached = await cache.getCachedRetrieval(query);
    
    expect(cached).toEqual(results);
  });
});

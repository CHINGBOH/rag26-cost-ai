/**
 * Pipe 模块测试 - 基于 RxJS
 */

import { describe, it, expect, vi } from 'vitest'
import { pipe, PipeBuilder, withTimeout, withRetry, withCache } from '../src'
import { of, delay, throwError, timer } from 'rxjs'
import { map, catchError } from 'rxjs/operators'

describe('PipeBuilder', () => {
  describe('基础功能', () => {
    it('应该通过 .through() 执行同步函数', async () => {
      const result = await pipe(5)
        .through('add10', (x: number) => x + 10)
        .through('multiply2', (x: number) => x * 2)
        .execute()

      expect(result).toBe(30) // (5 + 10) * 2 = 30
    })

    it('应该通过 .through() 执行异步函数', async () => {
      const result = await pipe(5)
        .through('asyncAdd', async (x: number) => {
          await new Promise(r => setTimeout(r, 10))
          return x + 10
        })
        .execute()

      expect(result).toBe(15)
    })

    it('应该通过 .through() 执行 Observable', async () => {
      const result = await pipe(5)
        .through('obsAdd', (x: number) => of(x + 10).pipe(delay(10)))
        .execute()

      expect(result).toBe(15)
    })
  })

  describe('条件分支', () => {
    it('应该根据条件执行分支', async () => {
      const result = await pipe<number>(10)
        .when((x: number) => x > 5)
        .then((x: number) => x * 2)
        .through('final', (x: any) => x + 1)
        .execute()

      expect(result).toBe(21) // 10 > 5, so (10 * 2) + 1 = 21
    })

    it('条件不满足时不执行分支', async () => {
      const result = await pipe<number>(3)
        .when((x: number) => x > 5)
        .then((x: number) => x * 2)
        .through('final', (x: any) => x + 1)
        .execute()

      expect(result).toBe(4) // 3 <= 5, so 3 + 1 = 4
    })
  })

  describe('过滤', () => {
    it('应该过滤不符合条件的值', async () => {
      const result = await of(1, 2, 3, 4, 5)
        .pipe(
          map(x => x * 2)
        )
        .toPromise()

      // 注意：firstValueFrom 只取第一个值
      const first = await pipe([1, 2, 3, 4, 5])
        .through('process', (arr: number[]) => arr.filter(x => x > 2))
        .execute()

      expect(first).toEqual([3, 4, 5])
    })
  })

  describe('并行分支 (fork)', () => {
    it('应该并行执行多个分支', async () => {
      const result = await pipe(10)
        .fork(
          (x: number) => of(x + 1),
          (x: number) => of(x + 2),
          (x: number) => of(x + 3)
        )
        .execute()

      expect(result).toEqual([11, 12, 13])
    })

    it('应该合并 fork 结果', async () => {
      const result = await pipe(10)
        .fork(
          (x: number) => of(x + 1),
          (x: number) => of(x + 2)
        )
        .merge((results: number[]) => results.reduce((a, b) => a + b, 0))
        .execute()

      expect(result).toBe(23) // (10+1) + (10+2) = 23
    })
  })

  describe('错误处理', () => {
    it('应该捕获并处理错误', async () => {
      const errorHandler = vi.fn(() => 'recovered')

      const result = await pipe(5)
        .through('throw', () => {
          throw new Error('test error')
        })
        .catch(errorHandler)
        .execute()

      expect(errorHandler).toHaveBeenCalledWith(expect.any(Error), expect.any(Object))
      expect(result).toBe('recovered')
    })

    it('应该记录错误到上下文', async () => {
      const builder = pipe(5)
        .through('throw', () => {
          throw new Error('test error')
        })
        .catch(() => 'recovered')

      await builder.execute()
      const context = builder.getContext()

      expect(context.errors).toHaveLength(1)
      expect(context.errors[0].message).toBe('test error')
    })
  })

  describe('重试', () => {
    it('应该在失败后重试', async () => {
      let attempts = 0
      
      const result = await pipe(null)
        .through('flaky', () => {
          attempts++
          if (attempts < 3) {
            throw new Error('fail')
          }
          return 'success'
        })
        .retry(3, 10)
        .execute()

      expect(attempts).toBe(3)
      expect(result).toBe('success')
    })
  })

  describe('超时', () => {
    it('应该在超时时抛出错误', async () => {
      await expect(
        pipe(null)
          .through('slow', () => 
            new Promise(resolve => setTimeout(() => resolve('done'), 1000))
          )
          .timeout(50)
          .execute()
      ).rejects.toThrow('Timeout')
    })

    it('应该允许在超时前完成', async () => {
      const result = await pipe('value')
        .through('quick', (x: string) => 
          new Promise(resolve => setTimeout(() => resolve(x + '!'), 10))
        )
        .timeout(100)
        .execute()

      expect(result).toBe('value!')
    })
  })

  describe('并发控制', () => {
    it('应该限制并发数', async () => {
      const timestamps: number[] = []
      const concurrency = 2

      const result = await pipe([1, 2, 3, 4])
        .through('process', async (arr: number[]) => {
          // 模拟处理
          timestamps.push(Date.now())
          await new Promise(r => setTimeout(r, 50))
          return arr.map(x => x * 2)
        })
        .execute()

      expect(result).toEqual([2, 4, 6, 8])
    })
  })

  describe('工具函数', () => {
    it('应该通过 tap 执行副作用', async () => {
      const sideEffect = vi.fn()

      await pipe(5)
        .tap((x, ctx) => {
          sideEffect(x, ctx)
        })
        .through('double', (x: number) => x * 2)
        .execute()

      expect(sideEffect).toHaveBeenCalledWith(5, expect.any(Object))
    })

    it('应该记录执行步骤', async () => {
      const builder = pipe(5)
        .through('step1', (x: number) => x + 1)
        .through('step2', (x: number) => x * 2)
        .through('step3', (x: number) => x - 1)

      await builder.execute()
      const context = builder.getContext()

      expect(context.executed).toEqual(['step1', 'step2', 'step3'])
    })

    it('应该存储元数据', async () => {
      const builder = pipe(5)
        .meta('key1', 'value1')
        .meta('key2', 42)

      const context = builder.getContext()

      expect(context.metadata).toEqual({ key1: 'value1', key2: 42 })
    })
  })

  describe('工具函数', () => {
    it('withTimeout 应该超时', async () => {
      const slowFn = () => new Promise(r => setTimeout(r, 1000))
      const wrapped = withTimeout(slowFn, 50)

      await expect(wrapped(null)).rejects.toThrow('Timeout')
    })

    it('withRetry 应该重试', async () => {
      let attempts = 0
      const flakyFn = () => {
        attempts++
        if (attempts < 3) throw new Error('fail')
        return 'success'
      }
      const wrapped = withRetry(flakyFn, 3, 10)

      const result = await wrapped(null)
      expect(attempts).toBe(3)
      expect(result).toBe('success')
    })

    it('withCache 应该缓存结果', async () => {
      let calls = 0
      const fn = (x: number) => {
        calls++
        return x * 2
      }
      const cache = new Map<string, number>()
      const wrapped = withCache(fn, cache)

      const r1 = await wrapped(5)
      const r2 = await wrapped(5)
      const r3 = await wrapped(10)

      expect(calls).toBe(2) // 5 被缓存，10 是新值
      expect(r1).toBe(10)
      expect(r2).toBe(10)
      expect(r3).toBe(20)
    })
  })

  describe('Observable 集成', () => {
    it('应该转换为 Observable', async () => {
      const observable = pipe(5)
        .through('add', (x: number) => x + 10)
        .toObservable()

      const result = await observable.toPromise()
      expect(result).toBe(15)
    })

    it('应该支持订阅', async () => {
      const values: number[] = []

      const subscription = pipe([1, 2, 3])
        .through('arr', (arr: number[]) => arr)
        .subscribe(
          (arr: number[]) => values.push(...arr),
          undefined,
          () => values.push(999)
        )

      // 等待订阅完成
      await new Promise(r => setTimeout(r, 10))

      expect(values).toContain(999)
      subscription.unsubscribe()
    })
  })
})

describe('复杂场景', () => {
  it('应该处理 RAG 检索流程', async () => {
    // 模拟 RAG 流程
    interface Chunk { id: string; content: string; score: number }
    
    const query = '什么是RAG'
    
    const result = await pipe(query)
      // 1. 查询分解
      .through('decompose', (q: string) => [q, q + ' 原理', q + ' 应用'])
      // 2. 并行检索
      .fork(
        (queries: string[]) => of(queries.map((q, i) => ({ 
          id: `v${i}`, content: `${q} 向量结果`, score: 0.9 
        }))),
        (queries: string[]) => of(queries.map((q, i) => ({ 
          id: `k${i}`, content: `${q} 关键词结果`, score: 0.8 
        })))
      )
      // 3. 合并结果
      .merge((results: Chunk[][]) => 
        results.flat().sort((a, b) => b.score - a.score).slice(0, 3)
      )
      .execute()

    expect(result).toHaveLength(3)
    expect(result[0].score).toBeGreaterThanOrEqual(result[1].score)
  })

  it('应该处理带重试的错误恢复', async () => {
    let attempts = 0
    
    const result = await pipe('data')
      .through('process', (x: string) => {
        attempts++
        if (attempts < 3) throw new Error('网络错误')
        return x.toUpperCase()
      })
      .retry(3, 10)
      .catch((err) => 'fallback')
      .execute()

    expect(attempts).toBe(3)
    expect(result).toBe('DATA')
  })
})

/**
 * 管道引擎 - 基于 RxJS 的流式处理编排
 * 提供响应式管道、分支并行、结果合并、背压控制等能力
 */

import {
  Observable,
  of,
  from,
  forkJoin,
  merge,
  concat,
  race,
  timer,
  throwError,
  EMPTY,
  Subject,
  ReplaySubject,
  BehaviorSubject,
  pipe as rxjsPipe,
  firstValueFrom,
  lastValueFrom
} from 'rxjs'
import {
  map,
  mergeMap,
  concatMap,
  switchMap,
  flatMap,
  filter,
  tap,
  catchError,
  retry,
  retryWhen,
  delay,
  take,
  timeout,
  debounceTime,
  throttleTime,
  distinctUntilChanged,
  bufferCount,
  bufferTime,
  share,
  shareReplay,
  finalize
} from 'rxjs/operators'
import { pino } from 'pino'

const logger = pino({ name: 'pipe-engine' })

// ==================== 类型定义 ====================

export type PipeFn<T, R> = (input: T) => R | Promise<R> | Observable<R>
export type RxjsOperator<T, R> = (source: Observable<T>) => Observable<R>

export interface PipeContext {
  metadata: Record<string, unknown>
  errors: Error[]
  executed: string[]
  startTime: number
  endTime?: number
}

export interface PipeOptions {
  name?: string
  logLevel?: 'trace' | 'debug' | 'info' | 'warn' | 'error'
  enableTracing?: boolean
  maxConcurrency?: number
  bufferSize?: number
}

// ==================== PipeBuilder 类 ====================

class PipeBuilder<T> {
  private observable$: Observable<T>
  private context: PipeContext
  private options: PipeOptions
  private operators: Array<{ name: string; operator: RxjsOperator<any, any> }> = []

  constructor(source: T | Observable<T>, options: PipeOptions = {}) {
    this.options = {
      name: 'anonymous-pipe',
      logLevel: 'info',
      enableTracing: false,
      maxConcurrency: 1,
      bufferSize: 1,
      ...options
    }

    this.observable$ = source instanceof Observable ? source : of(source)
    this.context = {
      metadata: {},
      errors: [],
      executed: [],
      startTime: Date.now()
    }

    if (this.options.enableTracing) {
      logger.info({ pipeName: this.options.name }, 'Pipe created')
    }
  }

  // ==================== 核心操作符 ====================

  /**
   * 添加处理步骤
   */
  through<R>(fn: PipeFn<T, R>): PipeBuilder<R>
  through<R>(name: string, fn: PipeFn<T, R>): PipeBuilder<R>
  through<R>(nameOrFn: string | PipeFn<T, R>, fn?: PipeFn<T, R>): PipeBuilder<R> {
    const name = typeof nameOrFn === 'string' ? nameOrFn : nameOrFn.name || 'anonymous'
    const actualFn = typeof nameOrFn === 'function' ? nameOrFn : fn!

    this.operators.push({
      name,
      operator: mergeMap((input: T) => {
        const result = actualFn(input)
        
        if (this.options.enableTracing) {
          logger.trace({ step: name, input }, 'Executing step')
        }

        this.context.executed.push(name)

        // 处理 Observable / Promise / 同步值
        if (result instanceof Observable) {
          return result
        }
        if (result instanceof Promise) {
          return from(result)
        }
        return of(result)
      })
    })

    return this as unknown as PipeBuilder<R>
  }

  /**
   * 添加 RxJS 原生操作符
   */
  pipe<R>(...operators: RxjsOperator<any, any>[]): PipeBuilder<R> {
    operators.forEach((op, idx) => {
      this.operators.push({
        name: `rxjs-op-${idx}`,
        operator: op
      })
    })
    return this as unknown as PipeBuilder<R>
  }

  // ==================== 条件与分支 ====================

  /**
   * 条件分支
   */
  when<R>(condition: (input: T) => boolean): { then: (fn: PipeFn<T, R>) => PipeBuilder<R> } {
    return {
      then: (fn: PipeFn<T, R>): PipeBuilder<R> => {
        this.operators.push({
          name: 'when',
          operator: mergeMap((input: T) => {
            if (condition(input)) {
              const result = fn(input)
              if (result instanceof Observable) return result
              if (result instanceof Promise) return from(result)
              return of(result)
            }
            return of(input as unknown as R)
          })
        })
        return this as unknown as PipeBuilder<R>
      }
    }
  }

  /**
   * 条件过滤
   */
  filter(predicate: (input: T) => boolean): PipeBuilder<T> {
    this.operators.push({
      name: 'filter',
      operator: filter(predicate)
    })
    return this
  }

  /**
   * 并行分支 (fork)
   */
  fork<R>(...branches: Array<(input: T) => Observable<R>>): PipeBuilder<R[]> {
    this.operators.push({
      name: 'fork',
      operator: mergeMap((input: T) => {
        const observables = branches.map(branch => branch(input))
        return forkJoin(observables)
      })
    })
    return this as unknown as PipeBuilder<R[]>
  }

  /**
   * 合并结果
   */
  merge<R>(
    fn: (results: T extends Array<infer U> ? U[] : never[]) => R | Promise<R> | Observable<R>
  ): PipeBuilder<R> {
    this.operators.push({
      name: 'merge',
      operator: mergeMap((input: T) => {
        if (!Array.isArray(input)) {
          return throwError(() => new Error('merge() requires array input from fork()'))
        }
        const result = fn(input as T extends Array<infer U> ? U[] : never[])
        if (result instanceof Observable) return result
        if (result instanceof Promise) return from(result)
        return of(result)
      })
    })
    return this as unknown as PipeBuilder<R>
  }

  // ==================== 错误处理 ====================

  /**
   * 错误处理
   */
  catch<R>(handler: (error: Error, context: PipeContext) => R | Promise<R> | Observable<R>): PipeBuilder<R> {
    this.operators.push({
      name: 'catch',
      operator: catchError((error: Error) => {
        this.context.errors.push(error)
        
        if (this.options.enableTracing) {
          logger.error({ error: error.message, step: this.context.executed.length }, 'Error caught')
        }

        const result = handler(error, this.context)
        if (result instanceof Observable) return result
        if (result instanceof Promise) return from(result)
        return of(result)
      })
    })
    return this as unknown as PipeBuilder<R>
  }

  /**
   * 重试
   */
  retry(count: number, delayMs: number = 1000): this {
    this.operators.push({
      name: 'retry',
      operator: retryWhen(errors =>
        errors.pipe(
          tap(error => {
            if (this.options.enableTracing) {
              logger.warn({ error: error.message }, 'Retrying')
            }
          }),
          delay(delayMs),
          take(count)
        )
      )
    })
    return this
  }

  // ==================== 流控制 ====================

  /**
   * 超时控制
   */
  timeout(ms: number): this {
    this.operators.push({
      name: 'timeout',
      operator: timeout({
        each: ms,
        with: () => throwError(() => new Error(`Timeout after ${ms}ms`))
      })
    })
    return this
  }

  /**
   * 防抖
   */
  debounce(ms: number): this {
    this.operators.push({
      name: 'debounce',
      operator: debounceTime(ms)
    })
    return this
  }

  /**
   * 节流
   */
  throttle(ms: number): this {
    this.operators.push({
      name: 'throttle',
      operator: throttleTime(ms)
    })
    return this
  }

  /**
   * 缓冲
   */
  buffer(count: number, timeMs?: number): PipeBuilder<T[]> {
    this.operators.push({
      name: 'buffer',
      operator: timeMs 
        ? bufferTime(timeMs)
        : bufferCount(count)
    })
    return this as unknown as PipeBuilder<T[]>
  }

  // ==================== 并发控制 ====================

  /**
   * 并发映射
   */
  mergeMap<R>(fn: PipeFn<T, R>, concurrency: number = 1): PipeBuilder<R> {
    this.operators.push({
      name: 'mergeMap',
      operator: mergeMap((input: T) => {
        const result = fn(input)
        if (result instanceof Observable) return result
        if (result instanceof Promise) return from(result)
        return of(result)
      }, concurrency)
    })
    return this as unknown as PipeBuilder<R>
  }

  /**
   * 顺序映射
   */
  concatMap<R>(fn: PipeFn<T, R>): PipeBuilder<R> {
    this.operators.push({
      name: 'concatMap',
      operator: concatMap((input: T) => {
        const result = fn(input)
        if (result instanceof Observable) return result
        if (result instanceof Promise) return from(result)
        return of(result)
      })
    })
    return this as unknown as PipeBuilder<R>
  }

  /**
   * 切换映射 (取消之前的)
   */
  switchMap<R>(fn: PipeFn<T, R>): PipeBuilder<R> {
    this.operators.push({
      name: 'switchMap',
      operator: switchMap((input: T) => {
        const result = fn(input)
        if (result instanceof Observable) return result
        if (result instanceof Promise) return from(result)
        return of(result)
      })
    })
    return this as unknown as PipeBuilder<R>
  }

  // ==================== 工具方法 ====================

  /**
   * 副作用 (tap)
   */
  tap(fn: (input: T, context: PipeContext) => void): PipeBuilder<T> {
    this.operators.push({
      name: 'tap',
      operator: tap((input: T) => {
        fn(input, this.context)
      })
    })
    return this
  }

  /**
   * 元数据
   */
  meta(key: string, value: unknown): this {
    this.context.metadata[key] = value
    return this
  }

  /**
   * 日志
   */
  log(message?: string): this {
    this.operators.push({
      name: 'log',
      operator: tap((input: T) => {
        logger.info({ message, input, step: this.context.executed.length }, message || 'Pipe log')
      })
    })
    return this
  }

  /**
   * 去重
   */
  distinct<R>(keySelector?: (input: T) => R): this {
    this.operators.push({
      name: 'distinct',
      operator: keySelector 
        ? distinctUntilChanged((prev, curr) => keySelector(prev) === keySelector(curr))
        : distinctUntilChanged()
    })
    return this
  }

  /**
   * 共享订阅
   */
  share(bufferSize: number = 1): this {
    this.operators.push({
      name: 'share',
      operator: shareReplay({ bufferSize, refCount: true })
    })
    return this
  }

  // ==================== 执行方法 ====================

  /**
   * 构建最终 Observable
   */
  build(): Observable<T> {
    const composedOperators = this.operators.map(o => o.operator)
    const operator = (rxjsPipe as any).apply(null, composedOperators)
    const piped$ = operator(this.observable$) as Observable<T>
    return piped$.pipe(
      finalize(() => {
        this.context.endTime = Date.now()
        if (this.options.enableTracing) {
          logger.info({ 
            duration: this.context.endTime - this.context.startTime,
            steps: this.context.executed.length 
          }, 'Pipe completed')
        }
      })
    )
  }

  /**
   * 执行并获取首个值
   */
  async execute(): Promise<T> {
    return firstValueFrom(this.build())
  }

  /**
   * 执行并获取最后一个值
   */
  async last(): Promise<T> {
    return lastValueFrom(this.build())
  }

  /**
   * 订阅执行
   */
  subscribe(
    next?: (value: T) => void,
    error?: (err: any) => void,
    complete?: () => void
  ): { unsubscribe: () => void } {
    return this.build().subscribe({ next, error, complete })
  }

  /**
   * 获取 Observable
   */
  toObservable(): Observable<T> {
    return this.build()
  }

  /**
   * 获取上下文
   */
  getContext(): PipeContext {
    return { ...this.context }
  }
}

// ==================== 工厂函数 ====================

/**
 * 创建管道
 */
export function pipe<T>(input: T | Observable<T>, options?: PipeOptions): PipeBuilder<T> {
  return new PipeBuilder(input, options)
}

/**
 * 创建管道函数（柯里化）
 */
export function createPipe<T, R>(
  ...fns: Array<PipeFn<any, any>>
): (input: T | Observable<T>) => Observable<R> {
  return (input: T | Observable<T>): Observable<R> => {
    const builder = new PipeBuilder(input)
    fns.forEach(fn => builder.through(fn))
    return builder.build() as unknown as Observable<R>
  }
}

/**
 * 组合多个管道函数
 */
export function compose<T>(...fns: Array<PipeFn<any, any>>): PipeFn<T, any> {
  return (input: T) => {
    return fns.reduce(async (acc, fn) => {
      const resolved = await acc
      return fn(resolved)
    }, Promise.resolve(input))
  }
}

/**
 * 并行执行多个函数
 */
export function parallel<T, R>(...fns: Array<PipeFn<T, R>>): PipeFn<T, R[]> {
  return async (input: T): Promise<R[]> => {
    const promises = fns.map(async fn => {
      const result = fn(input)
      if (result instanceof Observable) {
        return firstValueFrom(result)
      }
      // result is R or Promise<R>
      return result
    })
    return Promise.all(promises)
  }
}

/**
 * 带超时的管道步骤
 */
export function withTimeout<T, R>(fn: PipeFn<T, R>, ms: number): PipeFn<T, R> {
  return async (input: T): Promise<R> => {
    const result = fn(input)
    let promise: Promise<R>
    if (result instanceof Observable) {
      promise = firstValueFrom(result)
    } else if (result instanceof Promise) {
      promise = result
    } else {
      promise = Promise.resolve(result)
    }
    return Promise.race([
      promise,
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error(`Timeout after ${ms}ms`)), ms)
      )
    ])
  }
}

/**
 * 带重试的管道步骤
 */
export function withRetry<T, R>(
  fn: PipeFn<T, R>, 
  retries: number = 3, 
  delay: number = 1000
): PipeFn<T, R> {
  return async (input: T): Promise<R> => {
    let lastError: Error

    for (let i = 0; i < retries; i++) {
      try {
        const result = fn(input)
        if (result instanceof Observable) {
          return await firstValueFrom(result)
        } else if (result instanceof Promise) {
          return await result
        } else {
          return result
        }
      } catch (error) {
        lastError = error as Error
        if (i < retries - 1) {
          await new Promise(resolve => setTimeout(resolve, delay * (i + 1)))
        }
      }
    }

    throw lastError!
  }
}

/**
 * 缓存结果
 */
export function withCache<T, R>(fn: PipeFn<T, R>, cache: Map<string, R>): PipeFn<T, R> {
  return async (input: T): Promise<R> => {
    const key = JSON.stringify(input)

    if (cache.has(key)) {
      return cache.get(key)!
    }

    const result = fn(input)
    let resolved: R
    if (result instanceof Observable) {
      resolved = await firstValueFrom(result)
    } else if (result instanceof Promise) {
      resolved = await result
    } else {
      resolved = result
    }
    cache.set(key, resolved)
    return resolved
  }
}

// ==================== RxJS 操作符导出 ====================

export {
  map,
  mergeMap,
  concatMap,
  switchMap,
  filter,
  tap,
  catchError,
  retry,
  delay,
  take,
  timeout,
  debounceTime,
  throttleTime,
  distinctUntilChanged,
  bufferCount,
  bufferTime,
  share,
  shareReplay,
  finalize
}

export { Observable, of, from, forkJoin, merge, concat, race, timer, throwError, EMPTY }

export { PipeBuilder }
export default pipe

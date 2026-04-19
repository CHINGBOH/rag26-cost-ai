/**
 * 事件总线 - 基于 EventEmitter3 + Zod 的模块间通信
 * 提供类型安全、验证、审计追踪和内存泄漏检测
 */

import EventEmitter3 from 'eventemitter3'
import { z, ZodSchema, ZodType } from 'zod'
import { pino } from 'pino'

const logger = pino({ name: 'event-bus' })

// ==================== Zod Schema 定义 ====================

export const EventSchema = z.object({
  name: z.string(),
  payload: z.unknown(),
  timestamp: z.number().default(() => Date.now()),
  metadata: z.record(z.unknown()).optional()
})

export const EventBusConfigSchema = z.object({
  async: z.boolean().default(false),
  queueSize: z.number().default(1000),
  enableValidation: z.boolean().default(true),
  enableAudit: z.boolean().default(false),
  maxListeners: z.number().default(100)
})

export type EventSchema = z.infer<typeof EventSchema>
export type EventBusConfig = z.infer<typeof EventBusConfigSchema>

// ==================== 类型定义 ====================

export type EventHandler<T = any> = (data: T, event: EventSchema) => void | Promise<void>

export interface TypedEventHandler<TSchema extends ZodType> {
  schema: TSchema
  handler: (data: z.infer<TSchema>, event: EventSchema) => void | Promise<void>
}

export interface EventSubscription {
  unsubscribe(): void
  getEventName(): string
}

export interface EventAudit {
  eventName: string
  payload: unknown
  timestamp: number
  handlerCount: number
  executionTime?: number
  error?: string
}

// ==================== EventBus 类 ====================

class EventBus {
  private emitter: EventEmitter3
  private schemas: Map<string, ZodSchema> = new Map()
  private auditLog: EventAudit[] = []
  private config: EventBusConfig
  private handlerCounts: Map<string, number> = new Map()

  constructor(config: Partial<EventBusConfig> = {}) {
    this.config = EventBusConfigSchema.parse({
      async: false,
      queueSize: 1000,
      enableValidation: true,
      enableAudit: false,
      maxListeners: 100,
      ...config
    })

    this.emitter = new EventEmitter3()

    if (this.config.enableAudit) {
      logger.info('EventBus audit enabled')
    }
  }

  /**
   * 注册事件 Schema（用于验证）
   */
  registerSchema<T extends ZodSchema>(event: string, schema: T): this {
    this.schemas.set(event, schema)
    return this
  }

  /**
   * 订阅事件（带类型安全）
   */
  on<T>(event: string, handler: EventHandler<T>): EventSubscription {
    const wrappedHandler = (payload: unknown, meta: EventSchema) => {
      return handler(payload as T, meta)
    }

    this.emitter.on(event, wrappedHandler)
    this.incrementHandlerCount(event)

    if (this.config.enableAudit) {
      logger.trace({ event, action: 'subscribe' }, 'Event subscribed')
    }

    return {
      unsubscribe: () => {
        this.emitter.off(event, wrappedHandler)
        this.decrementHandlerCount(event)
        
        if (this.config.enableAudit) {
          logger.trace({ event, action: 'unsubscribe' }, 'Event unsubscribed')
        }
      },
      getEventName: () => event
    }
  }

  /**
   * 订阅事件（带 Zod 验证）
   */
  onValidated<T extends ZodSchema>(
    event: string, 
    schema: T,
    handler: (data: z.infer<T>, meta: EventSchema) => void | Promise<void>
  ): EventSubscription {
    // 注册 schema
    this.registerSchema(event, schema)

    const wrappedHandler = (payload: unknown, meta: EventSchema) => {
      try {
        // 验证数据
        const validated = schema.parse(payload)
        return handler(validated, meta)
      } catch (error) {
        logger.error({ 
          event, 
          error: error instanceof Error ? error.message : String(error),
          payload 
        }, 'Event validation failed')
        throw error
      }
    }

    this.emitter.on(event, wrappedHandler)
    this.incrementHandlerCount(event)

    return {
      unsubscribe: () => {
        this.emitter.off(event, wrappedHandler)
        this.decrementHandlerCount(event)
      },
      getEventName: () => event
    }
  }

  /**
   * 订阅一次性事件
   */
  once<T>(event: string, handler: EventHandler<T>): void {
    const wrappedHandler = (payload: unknown, meta: EventSchema) => {
      handler(payload as T, meta)
    }

    this.emitter.once(event, wrappedHandler)
  }

  /**
   * 触发事件（同步）
   */
  emit<T>(event: string, payload: T, metadata?: Record<string, unknown>): void {
    const eventSchema: EventSchema = {
      name: event,
      payload,
      timestamp: Date.now(),
      metadata
    }

    // 验证（如果注册了 schema）
    if (this.config.enableValidation && this.schemas.has(event)) {
      const schema = this.schemas.get(event)!
      try {
        schema.parse(payload)
      } catch (error) {
        logger.error({ 
          event, 
          error: error instanceof Error ? error.message : String(error) 
        }, 'Event emission validation failed')
        return
      }
    }

    // 审计日志
    if (this.config.enableAudit) {
      this.auditLog.push({
        eventName: event,
        payload,
        timestamp: Date.now(),
        handlerCount: this.getHandlerCount(event)
      })
    }

    // 触发事件
    this.emitter.emit(event, payload, eventSchema)
  }

  /**
   * 触发事件（异步，等待所有 handler 完成）
   */
  async emitAsync<T>(event: string, payload: T, metadata?: Record<string, unknown>): Promise<void> {
    const eventSchema: EventSchema = {
      name: event,
      payload,
      timestamp: Date.now(),
      metadata
    }

    const startTime = Date.now()
    const listeners = this.emitter.listeners(event)

    if (this.config.enableAudit) {
      this.auditLog.push({
        eventName: event,
        payload,
        timestamp: startTime,
        handlerCount: listeners.length
      })
    }

    try {
      await Promise.all(
        listeners.map(async (listener) => {
          try {
            await listener(payload, eventSchema)
          } catch (error) {
            logger.error({ 
              event, 
              error: error instanceof Error ? error.message : String(error) 
            }, 'Async event handler error')
            throw error
          }
        })
      )
    } catch (error) {
      if (this.config.enableAudit) {
        const auditEntry = this.auditLog.find(
          a => a.eventName === event && a.timestamp === startTime
        )
        if (auditEntry) {
          auditEntry.error = error instanceof Error ? error.message : String(error)
        }
      }
      throw error
    }
  }

  /**
   * 取消订阅
   */
  off<T>(event: string, handler: EventHandler<T>): void {
    this.emitter.off(event, handler as any)
    this.decrementHandlerCount(event)
  }

  /**
   * 获取事件处理器数量
   */
  getHandlerCount(event: string): number {
    return this.emitter.listenerCount(event)
  }

  /**
   * 获取所有事件名称
   */
  getEvents(): string[] {
    return this.emitter.eventNames() as string[]
  }

  /**
   * 清空所有处理器
   */
  clear(): void {
    this.emitter.removeAllListeners()
    this.handlerCounts.clear()
    this.auditLog = []
  }

  /**
   * 清空指定事件的所有处理器
   */
  clearEvent(event: string): void {
    this.emitter.removeAllListeners(event)
    this.handlerCounts.delete(event)
  }

  /**
   * 获取审计日志
   */
  getAuditLog(since?: number): EventAudit[] {
    if (!since) return [...this.auditLog]
    return this.auditLog.filter(a => a.timestamp >= since)
  }

  /**
   * 检查内存泄漏
   */
  checkMemoryLeak(threshold: number = 50): { event: string; count: number }[] {
    const leaks: { event: string; count: number }[] = []
    
    for (const [event, count] of this.handlerCounts) {
      if (count > threshold) {
        leaks.push({ event, count })
        logger.warn({ event, count }, 'Potential memory leak detected')
      }
    }

    return leaks
  }

  // ==================== 私有方法 ====================

  private incrementHandlerCount(event: string): void {
    const current = this.handlerCounts.get(event) || 0
    this.handlerCounts.set(event, current + 1)
  }

  private decrementHandlerCount(event: string): void {
    const current = this.handlerCounts.get(event) || 0
    if (current > 0) {
      this.handlerCounts.set(event, current - 1)
    }
  }

  /**
   * 创建带命名空间的事件总线
   */
  withNamespace(namespace: string): NamespacedEventBus {
    return new NamespacedEventBus(this, namespace)
  }
}

// ==================== 命名空间事件总线 ====================

class NamespacedEventBus {
  constructor(
    private bus: EventBus,
    private namespace: string
  ) {}

  private namespaced(event: string): string {
    return `${this.namespace}:${event}`
  }

  on<T>(event: string, handler: EventHandler<T>): EventSubscription {
    return this.bus.on(this.namespaced(event), handler)
  }

  onValidated<T extends ZodSchema>(
    event: string,
    schema: T,
    handler: (data: z.infer<T>, meta: EventSchema) => void | Promise<void>
  ): EventSubscription {
    return this.bus.onValidated(this.namespaced(event), schema, handler)
  }

  once<T>(event: string, handler: EventHandler<T>): void {
    this.bus.once(this.namespaced(event), handler)
  }

  emit<T>(event: string, payload: T, metadata?: Record<string, unknown>): void {
    this.bus.emit(this.namespaced(event), payload, metadata)
  }

  emitAsync<T>(event: string, payload: T, metadata?: Record<string, unknown>): Promise<void> {
    return this.bus.emitAsync(this.namespaced(event), payload, metadata)
  }

  off<T>(event: string, handler: EventHandler<T>): void {
    this.bus.off(this.namespaced(event), handler)
  }

  getHandlerCount(event: string): number {
    return this.bus.getHandlerCount(this.namespaced(event))
  }
}

// ==================== 工厂函数 ====================

export function createEventBus(config?: Partial<EventBusConfig>): EventBus {
  return new EventBus(config)
}

// ==================== 全局实例 ====================

export const globalEventBus = new EventBus({ 
  async: true,
  enableValidation: true,
  enableAudit: true 
})

// ==================== 装饰器 ====================

export function OnEvent<T extends ZodSchema>(event: string, schema?: T) {
  return function (target: any, propertyKey: string, descriptor: PropertyDescriptor) {
    const originalMethod = descriptor.value

    if (schema) {
      globalEventBus.onValidated(event, schema, originalMethod.bind(target))
    } else {
      globalEventBus.on(event, originalMethod.bind(target))
    }

    return descriptor
  }
}

// ==================== RxJS 集成 ====================

export function emitEvent<T>(
  event: string, 
  bus: EventBus = globalEventBus,
  metadata?: Record<string, unknown>
) {
  return (input: T): T => {
    bus.emit(event, input, metadata)
    return input
  }
}

export function waitForEvent<T>(
  event: string, 
  bus: EventBus = globalEventBus,
  timeout?: number
): Promise<T> {
  return new Promise((resolve, reject) => {
    let timer: NodeJS.Timeout | null = null

    const subscription = bus.on<T>(event, (data) => {
      if (timer) clearTimeout(timer)
      subscription.unsubscribe()
      resolve(data)
    })

    if (timeout) {
      timer = setTimeout(() => {
        subscription.unsubscribe()
        reject(new Error(`Timeout waiting for event: ${event}`))
      }, timeout)
    }
  })
}

export { EventBus, NamespacedEventBus, EventEmitter3 }
export default EventBus

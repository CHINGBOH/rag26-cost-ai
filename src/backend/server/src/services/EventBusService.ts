/**
 * 事件总线服务
 * 实现发布/订阅模式的跨服务通信
 */

import { EventEmitter } from 'events';

interface EventBusConfig {
  maxListeners: number;
}

type EventHandler<T = any> = (data: T) => void | Promise<void>;

interface EventSubscription {
  unsubscribe: () => void;
}

export class EventBusService {
  private emitter: EventEmitter;
  private config: EventBusConfig;
  private handlerCount: Map<string, number> = new Map();

  constructor(config?: Partial<EventBusConfig>) {
    this.config = {
      maxListeners: config?.maxListeners || 100
    };
    
    this.emitter = new EventEmitter();
    this.emitter.setMaxListeners(this.config.maxListeners);
  }

  /**
   * 发布事件
   */
  emit<T>(event: string, data: T): void {
    console.log(`[EventBus] 发布事件: ${event}`);
    this.emitter.emit(event, {
      ...data,
      _meta: {
        timestamp: Date.now(),
        event
      }
    });
  }

  /**
   * 订阅事件
   */
  on<T>(event: string, handler: EventHandler<T>): EventSubscription {
    const wrappedHandler = async (data: T) => {
      try {
        await handler(data);
      } catch (error) {
        console.error(`[EventBus] 事件处理错误 (${event}):`, error);
      }
    };

    this.emitter.on(event, wrappedHandler);
    
    const count = this.handlerCount.get(event) || 0;
    this.handlerCount.set(event, count + 1);

    return {
      unsubscribe: () => {
        this.emitter.off(event, wrappedHandler);
        const current = this.handlerCount.get(event) || 0;
        if (current > 0) {
          this.handlerCount.set(event, current - 1);
        }
      }
    };
  }

  /**
   * 订阅一次性事件
   */
  once<T>(event: string, handler: EventHandler<T>): void {
    this.emitter.once(event, handler);
  }

  /**
   * 取消订阅所有指定事件的处理函数
   */
  off(event: string): void {
    this.emitter.removeAllListeners(event);
    this.handlerCount.delete(event);
  }

  /**
   * 获取事件处理器数量
   */
  getHandlerCount(event: string): number {
    return this.handlerCount.get(event) || 0;
  }

  /**
   * 获取所有活跃事件
   */
  getActiveEvents(): string[] {
    return this.emitter.eventNames() as string[];
  }

  /**
   * 清空所有事件
   */
  clear(): void {
    this.emitter.removeAllListeners();
    this.handlerCount.clear();
  }

  // ==================== 预定义事件类型 ====================

  /**
   * 发布会话创建事件
   */
  emitSessionCreated(sessionId: string, data: any): void {
    this.emit('session:created', { sessionId, ...data });
  }

  /**
   * 发布会话状态变更事件
   */
  emitSessionStateChanged(sessionId: string, state: string, data?: any): void {
    this.emit('session:state_changed', { sessionId, state, ...data });
  }

  /**
   * 发布检索完成事件
   */
  emitRetrievalCompleted(sessionId: string, results: any[]): void {
    this.emit('retrieval:completed', { sessionId, results });
  }

  /**
   * 发布生成完成事件
   */
  emitGenerationCompleted(sessionId: string, answer: string): void {
    this.emit('generation:completed', { sessionId, answer });
  }

  /**
   * 发布评估完成事件
   */
  emitEvaluationCompleted(sessionId: string, evaluation: any): void {
    this.emit('evaluation:completed', { sessionId, evaluation });
  }

  /**
   * 发布专家判断事件
   */
  emitExpertJudgment(sessionId: string, decision: any): void {
    this.emit('expert:judgment', { sessionId, decision });
  }

  /**
   * 发布错误事件
   */
  emitError(sessionId: string, error: Error, context?: string): void {
    this.emit('system:error', {
      sessionId,
      error: error.message,
      stack: error.stack,
      context
    });
  }

  /**
   * 订阅会话事件
   */
  subscribeToSession(sessionId: string, handler: EventHandler): EventSubscription {
    return this.on(`session:${sessionId}`, handler);
  }

  /**
   * 发布到特定会话
   */
  emitToSession(sessionId: string, type: string, data: any): void {
    this.emit(`session:${sessionId}`, { type, data });
  }
}

// 创建全局事件总线实例
export const globalEventBus = new EventBusService();

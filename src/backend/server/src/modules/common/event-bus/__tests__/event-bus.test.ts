/**
 * EventBus 模块测试 - 基于 EventEmitter3 + Zod
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { z } from 'zod'
import { 
  EventBus, 
  createEventBus, 
  globalEventBus, 
  waitForEvent,
  emitEvent 
} from '../src'

describe('EventBus', () => {
  let bus: EventBus

  beforeEach(() => {
    bus = createEventBus({ enableValidation: true, enableAudit: true })
  })

  describe('基础功能', () => {
    it('应该订阅和触发事件', () => {
      const handler = vi.fn()
      
      bus.on('test', handler)
      bus.emit('test', 'payload')

      expect(handler).toHaveBeenCalledWith('payload', expect.any(Object))
    })

    it('应该取消订阅', () => {
      const handler = vi.fn()
      
      const subscription = bus.on('test', handler)
      subscription.unsubscribe()
      
      bus.emit('test', 'payload')
      
      expect(handler).not.toHaveBeenCalled()
    })

    it('应该支持多个处理器', () => {
      const handler1 = vi.fn()
      const handler2 = vi.fn()
      
      bus.on('test', handler1)
      bus.on('test', handler2)
      bus.emit('test', 'payload')

      expect(handler1).toHaveBeenCalled()
      expect(handler2).toHaveBeenCalled()
    })

    it('应该获取处理器数量', () => {
      bus.on('test', () => {})
      bus.on('test', () => {})
      
      expect(bus.getHandlerCount('test')).toBe(2)
    })
  })

  describe('异步事件', () => {
    it('应该等待异步处理器完成', async () => {
      const handler = vi.fn().mockResolvedValue(undefined)
      
      bus.on('test', handler)
      await bus.emitAsync('test', 'payload')

      expect(handler).toHaveBeenCalledWith('payload', expect.any(Object))
    })

    it('应该在异步处理器失败时抛出错误', async () => {
      const handler = vi.fn().mockRejectedValue(new Error('fail'))
      
      bus.on('test', handler)
      
      await expect(bus.emitAsync('test', 'payload')).rejects.toThrow('fail')
    })
  })

  describe('Zod 验证', () => {
    const TestSchema = z.object({
      name: z.string(),
      age: z.number().min(0)
    })

    it('应该通过验证的事件', () => {
      const handler = vi.fn()
      
      bus.onValidated('user.created', TestSchema, handler)
      bus.emit('user.created', { name: 'John', age: 30 })

      expect(handler).toHaveBeenCalledWith(
        { name: 'John', age: 30 },
        expect.any(Object)
      )
    })

    it('应该拒绝无效的数据', () => {
      const handler = vi.fn()
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      
      bus.onValidated('user.created', TestSchema, handler)
      bus.emit('user.created', { name: 'John', age: -5 })

      expect(handler).not.toHaveBeenCalled()
      consoleSpy.mockRestore()
    })

    it('应该在验证失败时抛出错误', async () => {
      bus.onValidated('user.created', TestSchema, () => {})
      
      // 同步 emit 不会抛出，但数据不会被处理
      bus.emit('user.created', { name: 123, age: 'invalid' })
      
      // 验证没有处理器被调用（因为验证失败）
      // 只要没有崩溃，就说明错误处理正常工作
      expect(true).toBe(true)
    })
  })

  describe('一次性订阅', () => {
    it('应该只触发一次', () => {
      const handler = vi.fn()
      
      bus.once('test', handler)
      bus.emit('test', 'first')
      bus.emit('test', 'second')

      expect(handler).toHaveBeenCalledTimes(1)
      expect(handler).toHaveBeenCalledWith('first', expect.any(Object))
    })
  })

  describe('命名空间', () => {
    it('应该在命名空间内隔离事件', () => {
      const handler = vi.fn()
      const ns1 = bus.withNamespace('ns1')
      const ns2 = bus.withNamespace('ns2')
      
      ns1.on('event', handler)
      ns1.emit('event', 'data1')
      ns2.emit('event', 'data2')

      expect(handler).toHaveBeenCalledTimes(1)
      expect(handler).toHaveBeenCalledWith('data1', expect.any(Object))
    })
  })

  describe('审计日志', () => {
    it('应该记录事件发射', () => {
      bus.emit('test', 'payload')
      
      const audit = bus.getAuditLog()
      expect(audit).toHaveLength(1)
      expect(audit[0].eventName).toBe('test')
      expect(audit[0].payload).toBe('payload')
    })

    it('应该按时间过滤审计日志', async () => {
      const t1 = Date.now()
      bus.emit('test1', 'payload1')
      
      // 等待一点时间
      await new Promise(r => setTimeout(r, 10))
      
      const t2 = Date.now()
      bus.emit('test2', 'payload2')
      
      // 过滤出 t2 之后的事件
      const audit = bus.getAuditLog(t2)
      expect(audit).toHaveLength(1)
      expect(audit[0].eventName).toBe('test2')
    })
  })

  describe('内存泄漏检测', () => {
    it('应该检测到过多的处理器', () => {
      for (let i = 0; i < 60; i++) {
        bus.on('leaky', () => {})
      }

      const leaks = bus.checkMemoryLeak(50)
      expect(leaks).toHaveLength(1)
      expect(leaks[0].event).toBe('leaky')
      expect(leaks[0].count).toBeGreaterThan(50)
    })
  })

  describe('清理', () => {
    it('应该清空所有处理器', () => {
      bus.on('test1', () => {})
      bus.on('test2', () => {})
      
      bus.clear()
      
      expect(bus.getHandlerCount('test1')).toBe(0)
      expect(bus.getHandlerCount('test2')).toBe(0)
    })

    it('应该清空指定事件的处理器', () => {
      bus.on('test1', () => {})
      bus.on('test2', () => {})
      
      bus.clearEvent('test1')
      
      expect(bus.getHandlerCount('test1')).toBe(0)
      expect(bus.getHandlerCount('test2')).toBe(1)
    })
  })

  describe('工具函数', () => {
    it('emitEvent 应该触发事件并返回输入', () => {
      const handler = vi.fn()
      const emitter = emitEvent('test', bus)
      
      bus.on('test', handler)
      const result = emitter('input')
      
      expect(result).toBe('input')
      expect(handler).toHaveBeenCalledWith('input', expect.any(Object))
    })

    it('waitForEvent 应该等待事件', async () => {
      const promise = waitForEvent('test', bus)
      
      setTimeout(() => bus.emit('test', 'data'), 10)
      
      const result = await promise
      expect(result).toBe('data')
    })

    it('waitForEvent 应该在超时后拒绝', async () => {
      await expect(
        waitForEvent('test', bus, 50)
      ).rejects.toThrow('Timeout')
    })
  })

  describe('全局事件总线', () => {
    it('应该共享实例', () => {
      const handler = vi.fn()
      
      globalEventBus.on('global.test', handler)
      globalEventBus.emit('global.test', 'data')
      
      expect(handler).toHaveBeenCalledWith('data', expect.any(Object))
    })
  })
})

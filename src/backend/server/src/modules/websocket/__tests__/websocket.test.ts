/**
 * WebSocket 模块测试
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  createWebSocketServer,
  broadcast,
  subscribe,
  unsubscribe,
  formatEvent,
  createConnection,
  disconnect,
  getConnectionCount,
  getConnection,
  sendTo,
  createWebSocketPipeline
} from '../src'
import { WebSocketConfig } from '../../common/types'

describe('WebSocket 模块', () => {
  let mockSocket: any

  beforeEach(() => {
    mockSocket = {
      readyState: 1, // WebSocket.OPEN
      send: vi.fn(),
      close: vi.fn()
    }
  })

  describe('WebSocket 服务器', () => {
    it('应该创建 WebSocket 服务器', () => {
      const config: WebSocketConfig = {
        port: 3002,
        heartbeatInterval: 30000,
        maxConnections: 100
      }
      
      const server = createWebSocketServer(config)
      
      expect(server).toBeDefined()
      expect(server.connections).toBeDefined()
      expect(server.broadcast).toBeDefined()
      expect(server.subscribe).toBeDefined()
      expect(server.unsubscribe).toBeDefined()
    })
  })

  describe('连接管理', () => {
    it('应该创建连接', () => {
      const conn = createConnection(mockSocket)
      
      expect(conn.id).toBeDefined()
      expect(conn.socket).toBe(mockSocket)
      expect(conn.subscriptions).toBeInstanceOf(Set)
    })

    it('应该断开连接', () => {
      const conn = createConnection(mockSocket)
      const result = disconnect(conn.id)
      
      expect(result).toBe(true)
      expect(getConnection(conn.id)).toBeUndefined()
    })

    it('应该获取连接数', () => {
      const conn1 = createConnection({ ...mockSocket })
      const conn2 = createConnection({ ...mockSocket })
      
      const count = getConnectionCount()
      
      expect(count).toBeGreaterThanOrEqual(2)
      
      // 清理
      disconnect(conn1.id)
      disconnect(conn2.id)
    })

    it('应该获取连接信息', () => {
      const conn = createConnection(mockSocket)
      const retrieved = getConnection(conn.id)
      
      expect(retrieved).toBeDefined()
      expect(retrieved?.id).toBe(conn.id)
      
      disconnect(conn.id)
    })
  })

  describe('广播', () => {
    it('应该向所有连接广播', () => {
      const server = createWebSocketServer({ port: 3002 })
      const conn1 = createConnection(mockSocket)
      const conn2 = createConnection(mockSocket)
      
      const broadcastFn = broadcast(server)
      const event = { type: 'test', payload: 'data' }
      broadcastFn(event)
      
      expect(mockSocket.send).toHaveBeenCalled()
      
      disconnect(conn1.id)
      disconnect(conn2.id)
    })

    it('应该向指定频道广播', () => {
      const server = createWebSocketServer({ port: 3002 })
      const conn = createConnection(mockSocket)
      
      // 订阅频道
      server.subscribe(conn.id, 'metrics')
      
      const broadcastFn = broadcast(server, 'metrics')
      const event = { type: 'metrics', payload: { cpu: 80 } }
      broadcastFn(event)
      
      expect(mockSocket.send).toHaveBeenCalled()
      
      disconnect(conn.id)
    })
  })

  describe('订阅管理', () => {
    it('应该订阅频道', () => {
      const server = createWebSocketServer({ port: 3002 })
      const conn = createConnection(mockSocket)
      
      const subscribeFn = subscribe(server, conn.id)
      subscribeFn('metrics')
      
      expect(conn.subscriptions.has('metrics')).toBe(true)
      
      disconnect(conn.id)
    })

    it('应该取消订阅', () => {
      const server = createWebSocketServer({ port: 3002 })
      const conn = createConnection(mockSocket)
      
      // 先订阅
      server.subscribe(conn.id, 'metrics')
      
      const unsubscribeFn = unsubscribe(server, conn.id)
      unsubscribeFn('metrics')
      
      expect(conn.subscriptions.has('metrics')).toBe(false)
      
      disconnect(conn.id)
    })
  })

  describe('发送消息', () => {
    it('应该向特定连接发送消息', () => {
      const conn = createConnection(mockSocket)
      
      const result = sendTo(conn.id, {
        type: 'message',
        payload: 'hello',
        timestamp: Date.now()
      })
      
      expect(result).toBe(true)
      expect(mockSocket.send).toHaveBeenCalled()
      
      disconnect(conn.id)
    })

    it('不应该向已断开连接发送消息', () => {
      const conn = createConnection(mockSocket)
      disconnect(conn.id)
      
      const result = sendTo(conn.id, {
        type: 'message',
        payload: 'hello',
        timestamp: Date.now()
      })
      
      expect(result).toBe(false)
    })
  })

  describe('事件格式化', () => {
    it('应该格式化事件', () => {
      const formatFn = formatEvent<string>('chat.message')
      const event = formatFn('Hello world', 'session-123')
      
      expect(event.type).toBe('chat.message')
      expect(event.payload).toBe('Hello world')
      expect(event.sessionId).toBe('session-123')
      expect(event.timestamp).toBeGreaterThan(0)
    })

    it('应该使用格式化器', () => {
      const formatFn = formatEvent<{ message: string }>('chat.message', (data) => ({
        ...data,
        formatted: true
      }))
      
      const event = formatFn({ message: 'Hello' })
      
      expect(event.payload).toEqual({
        message: 'Hello',
        formatted: true
      })
    })

    it('应该格式化事件不带 sessionId', () => {
      const formatFn = formatEvent<number>('metrics.update')
      const event = formatFn(42)
      
      expect(event.type).toBe('metrics.update')
      expect(event.payload).toBe(42)
      expect(event.sessionId).toBeUndefined()
    })
  })

  describe('管道工厂', () => {
    it('应该创建 WebSocket 管道', () => {
      const pipeline = createWebSocketPipeline({ port: 3002 })
      
      expect(pipeline.server).toBeDefined()
      expect(pipeline.broadcast).toBeDefined()
      expect(pipeline.subscribe).toBeDefined()
      expect(pipeline.unsubscribe).toBeDefined()
      expect(pipeline.formatEvent).toBeDefined()
      expect(pipeline.createConnection).toBeDefined()
      expect(pipeline.disconnect).toBeDefined()
      expect(pipeline.getConnectionCount).toBeDefined()
      expect(pipeline.sendTo).toBeDefined()
    })

    it('应该通过管道创建连接', () => {
      const pipeline = createWebSocketPipeline({ port: 3002 })
      
      const conn = pipeline.createConnection(mockSocket)
      expect(conn.id).toBeDefined()
      
      pipeline.disconnect(conn.id)
    })
  })
})

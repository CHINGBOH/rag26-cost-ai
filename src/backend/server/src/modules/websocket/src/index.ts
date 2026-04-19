/**
 * WebSocket模块 - 实时通信
 * 提供管道式WebSocket接口
 */

import { WebSocketEvent, WebSocketConfig } from '../../common/types'
import { EventBus } from '../../common/event-bus'

export interface WebSocketConnection {
  id: string
  socket: any
  subscriptions: Set<string>
}

export interface WebSocketServer {
  connections: Map<string, WebSocketConnection>
  broadcast(event: WebSocketEvent): void
  subscribe(connectionId: string, channel: string): void
  unsubscribe(connectionId: string, channel: string): void
}

// 连接存储
const connections: Map<string, WebSocketConnection> = new Map()
let eventBus: EventBus | null = null

/**
 * 创建WebSocket服务器
 */
export function createWebSocketServer(config: WebSocketConfig & { eventBus?: EventBus }): WebSocketServer {
  eventBus = config.eventBus || null

  const server: WebSocketServer = {
    connections,

    broadcast(event: WebSocketEvent) {
      for (const conn of connections.values()) {
        if (conn.socket.readyState === 1) { // WebSocket.OPEN
          conn.socket.send(JSON.stringify(event))
        }
      }

      eventBus?.emit('websocket:broadcast', { event, connections: connections.size })
    },

    subscribe(connectionId: string, channel: string) {
      const conn = connections.get(connectionId)
      if (conn) {
        conn.subscriptions.add(channel)
      }
    },

    unsubscribe(connectionId: string, channel: string) {
      const conn = connections.get(connectionId)
      if (conn) {
        conn.subscriptions.delete(channel)
      }
    }
  }

  return server
}

/**
 * 广播消息
 */
export function broadcast(server: WebSocketServer, channel?: string) {
  return function send(event: Omit<WebSocketEvent, 'timestamp'>): WebSocketEvent {
    const fullEvent: WebSocketEvent = {
      ...event,
      timestamp: Date.now()
    }

    if (channel) {
      // 只发送给订阅了该频道的连接
      for (const conn of connections.values()) {
        if (conn.subscriptions.has(channel) && conn.socket.readyState === 1) {
          conn.socket.send(JSON.stringify(fullEvent))
        }
      }
    } else {
      server.broadcast(fullEvent)
    }

    return fullEvent
  }
}

/**
 * 订阅频道
 */
export function subscribe(server: WebSocketServer, connectionId: string) {
  return function sub(channel: string): string {
    server.subscribe(connectionId, channel)
    eventBus?.emit('websocket:subscribe', { connectionId, channel })
    return channel
  }
}

/**
 * 取消订阅
 */
export function unsubscribe(server: WebSocketServer, connectionId: string) {
  return function unsub(channel: string): string {
    server.unsubscribe(connectionId, channel)
    eventBus?.emit('websocket:unsubscribe', { connectionId, channel })
    return channel
  }
}

/**
 * 格式化事件
 */
export function formatEvent<T>(
  type: string,
  formatter?: (data: T) => any
) {
  return function format(payload: T, sessionId?: string): WebSocketEvent {
    return {
      type,
      payload: formatter ? formatter(payload) : payload,
      timestamp: Date.now(),
      sessionId
    }
  }
}

/**
 * 创建连接
 */
export function createConnection(socket: any): WebSocketConnection {
  const id = `ws_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`

  const connection: WebSocketConnection = {
    id,
    socket,
    subscriptions: new Set()
  }

  connections.set(id, connection)
  eventBus?.emit('websocket:connect', { connectionId: id })

  return connection
}

/**
 * 断开连接
 */
export function disconnect(connectionId: string): boolean {
  const conn = connections.get(connectionId)
  if (!conn) return false

  conn.socket.close()
  connections.delete(connectionId)

  eventBus?.emit('websocket:disconnect', { connectionId })
  return true
}

/**
 * 获取连接数
 */
export function getConnectionCount(): number {
  return connections.size
}

/**
 * 获取连接信息
 */
export function getConnection(id: string): WebSocketConnection | undefined {
  return connections.get(id)
}

/**
 * 发送消息给特定连接
 */
export function sendTo(connectionId: string, event: WebSocketEvent): boolean {
  const conn = connections.get(connectionId)
  if (!conn || conn.socket.readyState !== 1) return false

  conn.socket.send(JSON.stringify(event))
  return true
}

/**
 * 创建WebSocket管道
 */
export function createWebSocketPipeline(config: WebSocketConfig & { eventBus?: EventBus }) {
  const server = createWebSocketServer(config)

  return {
    server,
    broadcast: (channel?: string) => broadcast(server, channel),
    subscribe: (connectionId: string) => subscribe(server, connectionId),
    unsubscribe: (connectionId: string) => unsubscribe(server, connectionId),
    formatEvent,
    createConnection,
    disconnect,
    getConnectionCount,
    sendTo
  }
}

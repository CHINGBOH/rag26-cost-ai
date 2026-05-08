/**
 * WebSocket 连接 Hook
 * 管理实时通信 — 全局连接池 + 引用计数，防止多组件重复建连导致内存泄漏
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import { DashboardEvent, SystemVitals } from '@rag/shared';
import { frontendRuntimeConfig, resolveWebSocketUrl } from '../config/runtime';

type MessageHandler = (event: DashboardEvent) => void;

interface WebSocketInstance {
  socket: WebSocket;
  handlers: Set<MessageHandler>;
  refCount: number;
  reconnectTimeout: ReturnType<typeof setTimeout> | null;
}

// Module-level connection registry — one socket per room across all component instances
const wsRegistry = new Map<string, WebSocketInstance>();

function getOrCreateInstance(room: string): WebSocketInstance {
  const existing = wsRegistry.get(room);
  if (existing) return existing;

  const instance: WebSocketInstance = {
    socket: null as unknown as WebSocket,
    handlers: new Set(),
    refCount: 0,
    reconnectTimeout: null,
  };

  const connect = () => {
    const wsUrl = resolveWebSocketUrl(room);
    const socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      console.log(`[WebSocket] Connected to room=${room}`);
      instance.socket = socket;
    };

    socket.onmessage = (event) => {
      try {
        const data: DashboardEvent = JSON.parse(event.data);
        instance.handlers.forEach(handler => handler(data));
      } catch (err) {
        console.error('[WebSocket] Failed to parse message:', err);
      }
    };

    socket.onclose = () => {
      console.log(`[WebSocket] Disconnected from room=${room}`);
      if (instance.refCount > 0) {
        // Only reconnect if someone is still holding a reference
        instance.reconnectTimeout = setTimeout(
          connect,
          frontendRuntimeConfig.wsReconnectDelayMs,
        );
      }
    };

    socket.onerror = (err) => {
      console.error(`[WebSocket] Error on room=${room}:`, err);
    };

    instance.socket = socket;
  };

  connect();
  wsRegistry.set(room, instance);
  return instance;
}

export function useWebSocket(room: string = 'dashboard') {
  const [isConnected, setIsConnected] = useState(false);
  const [vitals, setVitals] = useState<SystemVitals | null>(null);
  const instanceRef = useRef<WebSocketInstance | null>(null);

  // Subscribe to messages
  const subscribe = useCallback((handler: MessageHandler) => {
    instanceRef.current?.handlers.add(handler);
    return () => instanceRef.current?.handlers.delete(handler);
  }, []);

  // Send a raw message
  const send = useCallback((data: unknown) => {
    const sock = instanceRef.current?.socket;
    if (sock?.readyState === WebSocket.OPEN) {
      sock.send(JSON.stringify(data));
    }
  }, []);

  const startRecursion = useCallback((query: string) => {
    send({ type: 'start_recursion', query });
  }, [send]);

  const submitHumanReview = useCallback((sessionId: string, approved: boolean) => {
    send({ type: 'human_review', sessionId, approved });
  }, [send]);

  // Attach/detach from the shared connection pool
  useEffect(() => {
    const instance = getOrCreateInstance(room);
    instance.refCount++;
    instanceRef.current = instance;

    // Inject a vitals handler scoped to this hook instance
    const vitalsHandler: MessageHandler = (data) => {
      if (data.type === 'vitals_update') setVitals(data.payload);
    };
    instance.handlers.add(vitalsHandler);

    // Sync connected state from existing socket
    setIsConnected(instance.socket?.readyState === WebSocket.OPEN);

    // Patch onopen to update local state when the socket eventually opens
    const originalOnOpen = instance.socket.onopen;
    instance.socket.onopen = (ev) => {
      setIsConnected(true);
      if (typeof originalOnOpen === 'function') originalOnOpen.call(instance.socket, ev);
    };

    const originalOnClose = instance.socket.onclose;
    instance.socket.onclose = (ev) => {
      setIsConnected(false);
      if (typeof originalOnClose === 'function') originalOnClose.call(instance.socket, ev);
    };

    return () => {
      instance.handlers.delete(vitalsHandler);
      instance.refCount--;

      if (instance.refCount === 0) {
        // Last consumer — clean up the shared connection
        if (instance.reconnectTimeout !== null) {
          clearTimeout(instance.reconnectTimeout);
          instance.reconnectTimeout = null;
        }
        instance.socket.close();
        wsRegistry.delete(room);
      }
    };
  }, [room]); // re-run when room changes so we join the correct pool

  return {
    isConnected,
    vitals,
    subscribe,
    send,
    startRecursion,
    submitHumanReview,
  };
}


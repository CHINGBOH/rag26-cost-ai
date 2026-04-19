/**
 * WebSocket 连接 Hook
 * 管理实时通信
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import { DashboardEvent, SystemVitals } from '@rag/shared';

type MessageHandler = (event: DashboardEvent) => void;

export function useWebSocket(room: string = 'dashboard') {
  const ws = useRef<WebSocket | null>(null);
  const handlers = useRef<Set<MessageHandler>>(new Set());
  const [isConnected, setIsConnected] = useState(false);
  const [vitals, setVitals] = useState<SystemVitals | null>(null);
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 订阅消息
  const subscribe = useCallback((handler: MessageHandler) => {
    handlers.current.add(handler);
    return () => handlers.current.delete(handler);
  }, []);

  // 发送消息
  const send = useCallback((data: any) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(data));
    }
  }, []);

  // 启动递归
  const startRecursion = useCallback((query: string) => {
    send({ type: 'start_recursion', query });
  }, [send]);

  // 提交人工审核
  const submitHumanReview = useCallback((sessionId: string, approved: boolean) => {
    send({ type: 'human_review', sessionId, approved });
  }, [send]);

  // 连接 WebSocket
  useEffect(() => {
    const connect = () => {
      const wsUrl = import.meta.env.VITE_WS_URL || `ws://${window.location.host}/ws?room=${room}`;
      const socket = new WebSocket(wsUrl);

      socket.onopen = () => {
        console.log('[WebSocket] Connected');
        setIsConnected(true);
      };

      socket.onmessage = (event) => {
        try {
          const data: DashboardEvent = JSON.parse(event.data);
          
          // 处理系统生命体征更新
          if (data.type === 'vitals_update') {
            setVitals(data.payload);
          }
          
          // 分发到所有订阅者
          handlers.current.forEach(handler => handler(data));
        } catch (err) {
          console.error('[WebSocket] Failed to parse message:', err);
        }
      };

      socket.onclose = () => {
        console.log('[WebSocket] Disconnected');
        setIsConnected(false);
        
        // 自动重连
        reconnectTimeout.current = setTimeout(connect, 3000);
      };

      socket.onerror = (err) => {
        console.error('[WebSocket] Error:', err);
      };

      ws.current = socket;
    };

    connect();

    return () => {
      if (reconnectTimeout.current) {
        clearTimeout(reconnectTimeout.current);
        reconnectTimeout.current = null;
      }
      ws.current?.close();
    };
  }, []);

  return {
    isConnected,
    vitals,
    subscribe,
    send,
    startRecursion,
    submitHumanReview
  };
}

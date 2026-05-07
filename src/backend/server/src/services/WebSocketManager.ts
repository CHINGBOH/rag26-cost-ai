/**
 * WebSocket 网关广播客户端
 * 通过 HTTP POST 将事件转发到外部 Go WebSocket 网关
 */

import { DashboardEvent, SystemVitals } from '@rag/shared';

export interface WebSocketManagerConfig {
  gatewayUrl: string;
}

export class WebSocketManager {
  constructor(private readonly config: WebSocketManagerConfig) {}

  /**
   * 广播事件到 Go WebSocket 网关
   */
  broadcast(event: DashboardEvent) {
    // 异步发送，不阻塞调用方
    fetch(this.config.gatewayUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(event)
    }).catch((err) => {
      console.warn('[WebSocketManager] 转发到网关失败:', err);
    });
  }

  /**
   * 发送系统生命体征
   */
  broadcastVitals(vitals: SystemVitals) {
    this.broadcast({
      type: 'vitals_update',
      sessionId: 'system',
      timestamp: Date.now(),
      payload: vitals
    });
  }
}

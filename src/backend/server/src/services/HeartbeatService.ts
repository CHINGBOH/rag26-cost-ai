/**
 * 心跳服务 - 真实的时间感知和自动触发
 */

import { EventEmitter } from 'events';
import { YoloCodeGenerator } from './YoloCodeGenerator';

interface HeartbeatConfig {
  silenceThresholdMs: number;
  checkIntervalMs: number;
  autoYoloEnabled: boolean;
}

interface SessionHeartbeat {
  sessionId: string;
  lastActivityAt: number;
  silenceTimer?: NodeJS.Timeout;
  isYoloActive: boolean;
  yoloFeature?: string;
}

export class HeartbeatService {
  private config: HeartbeatConfig;
  private sessions: Map<string, SessionHeartbeat> = new Map();
  private eventEmitter: EventEmitter;
  private globalTimer?: NodeJS.Timeout;
  private yoloGenerator: YoloCodeGenerator;

  constructor(
    eventEmitter: EventEmitter, 
    projectRoot: string,
    config?: Partial<HeartbeatConfig>
  ) {
    this.eventEmitter = eventEmitter;
    this.yoloGenerator = new YoloCodeGenerator(eventEmitter, projectRoot);
    this.config = {
      silenceThresholdMs: 30000,
      checkIntervalMs: 1000,
      autoYoloEnabled: true,
      ...config
    };
  }

  start(): void {
    if (this.globalTimer) return;
    console.log('[Heartbeat] Service started');
    
    this.globalTimer = setInterval(() => {
      this.checkAllSessions();
    }, this.config.checkIntervalMs);
  }

  stop(): void {
    if (this.globalTimer) {
      clearInterval(this.globalTimer);
      this.globalTimer = undefined;
    }
    this.sessions.forEach(session => {
      if (session.silenceTimer) clearTimeout(session.silenceTimer);
    });
    console.log('[Heartbeat] Service stopped');
  }

  registerSession(sessionId: string, feature: string): void {
    const existing = this.sessions.get(sessionId);
    if (existing) {
      this.resetTimer(sessionId);
      return;
    }

    const session: SessionHeartbeat = {
      sessionId,
      lastActivityAt: Date.now(),
      isYoloActive: false,
      yoloFeature: feature
    };

    this.sessions.set(sessionId, session);
    this.startSilenceTimer(sessionId);
    console.log(`[Heartbeat] Session ${sessionId} registered`);
  }

  recordActivity(sessionId: string): void {
    const session = this.sessions.get(sessionId);
    if (!session) return;

    session.lastActivityAt = Date.now();
    session.isYoloActive = false;
    this.resetTimer(sessionId);

    this.eventEmitter.emit('heartbeat:activity', {
      sessionId,
      silenceDuration: 0,
      timestamp: Date.now()
    });
  }

  removeSession(sessionId: string): void {
    const session = this.sessions.get(sessionId);
    if (session?.silenceTimer) clearTimeout(session.silenceTimer);
    this.sessions.delete(sessionId);
  }

  getSilenceDuration(sessionId: string): number {
    const session = this.sessions.get(sessionId);
    if (!session) return 0;
    return Date.now() - session.lastActivityAt;
  }

  private startSilenceTimer(sessionId: string): void {
    const session = this.sessions.get(sessionId);
    if (!session) return;
    if (session.silenceTimer) clearTimeout(session.silenceTimer);

    session.silenceTimer = setTimeout(() => {
      this.onSilenceDetected(sessionId);
    }, this.config.silenceThresholdMs);
  }

  private resetTimer(sessionId: string): void {
    this.startSilenceTimer(sessionId);
  }

  private onSilenceDetected(sessionId: string): void {
    const session = this.sessions.get(sessionId);
    if (!session || session.isYoloActive) return;

    console.log(`[Heartbeat] Silence detected for ${sessionId}`);
    this.eventEmitter.emit('heartbeat:silence', {
      sessionId,
      silenceDuration: this.config.silenceThresholdMs,
      timestamp: Date.now()
    });

    if (this.config.autoYoloEnabled && session.yoloFeature) {
      this.enterYoloMode(sessionId, session.yoloFeature);
    }
  }

  private async enterYoloMode(sessionId: string, feature: string): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (!session) return;

    session.isYoloActive = true;
    console.log(`[Heartbeat] Entering YOLO mode for ${sessionId}`);

    this.eventEmitter.emit('heartbeat:yolo', {
      sessionId,
      timestamp: Date.now(),
      feature,
      message: '30秒沉默，进入自动递归编码模式'
    });

    // 执行真实的YOLO递归编码
    await this.yoloGenerator.execute(sessionId, feature);
  }

  private checkAllSessions(): void {
    const now = Date.now();
    this.sessions.forEach((session, sessionId) => {
      const silenceDuration = now - session.lastActivityAt;
      if (silenceDuration >= this.config.silenceThresholdMs && !session.isYoloActive) {
        this.onSilenceDetected(sessionId);
      }
    });
  }

  getAllSessionsStatus(): Array<{
    sessionId: string;
    silenceDuration: number;
    isYoloActive: boolean;
    lastActivityAt: number;
  }> {
    const now = Date.now();
    return Array.from(this.sessions.entries()).map(([sessionId, session]) => ({
      sessionId,
      silenceDuration: now - session.lastActivityAt,
      isYoloActive: session.isYoloActive,
      lastActivityAt: session.lastActivityAt
    }));
  }
}

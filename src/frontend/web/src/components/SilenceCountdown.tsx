/**
 * 沉默倒计时组件
 * 实时显示距离YOLO模式触发的时间
 */

import { useState, useEffect, useCallback } from 'react';
import './SilenceCountdown.css';

interface SilenceCountdownProps {
  sessionId: string;
  lastActivityAt: number;
  silenceThresholdMs: number;
  isYoloActive: boolean;
  onActivity: () => void;
}

export const SilenceCountdown: React.FC<SilenceCountdownProps> = ({
  sessionId,
  lastActivityAt,
  silenceThresholdMs,
  isYoloActive,
  onActivity
}) => {
  const [remainingMs, setRemainingMs] = useState(silenceThresholdMs);
  const [isWarning, setIsWarning] = useState(false);

  const updateCountdown = useCallback(() => {
    const elapsed = Date.now() - lastActivityAt;
    const remaining = Math.max(0, silenceThresholdMs - elapsed);
    
    setRemainingMs(remaining);
    setIsWarning(remaining < 10000); // 最后10秒警告

    if (remaining === 0 && !isYoloActive) {
      // YOLO即将触发
    }
  }, [lastActivityAt, silenceThresholdMs, isYoloActive]);

  useEffect(() => {
    const interval = setInterval(updateCountdown, 100);
    updateCountdown();
    return () => clearInterval(interval);
  }, [updateCountdown]);

  // 格式化时间
  const formatTime = (ms: number): string => {
    const seconds = Math.floor(ms / 1000);
    const milliseconds = Math.floor((ms % 1000) / 100);
    return `${seconds}.${milliseconds}s`;
  };

  // 计算进度条宽度
  const progressPercent = (remainingMs / silenceThresholdMs) * 100;

  if (isYoloActive) {
    return (
      <div className="silence-countdown yolo-active">
        <div className="countdown-icon">⚡</div>
        <div className="countdown-text">
          <span className="yolo-label">YOLO模式运行中</span>
          <span className="yolo-sub">自动递归编码...</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`silence-countdown ${isWarning ? 'warning' : ''}`}>
      <div className="countdown-header">
        <span className="countdown-label">
          {isWarning ? '⚠️ 即将自动编码' : '⏱️ 沉默计时'}
        </span>
        <button className="activity-btn" onClick={onActivity}>
          我在线
        </button>
      </div>

      <div className="countdown-display">
        <span className={`time-value ${isWarning ? 'warning' : ''}`}>
          {formatTime(remainingMs)}
        </span>
        <span className="time-label">后进入YOLO模式</span>
      </div>

      <div className="progress-container">
        <div 
          className={`progress-bar ${isWarning ? 'warning' : ''}`}
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      <div className="countdown-info">
        <span>会话: {sessionId.slice(0, 8)}...</span>
        <span>阈值: {silenceThresholdMs / 1000}s</span>
      </div>

      {isWarning && (
        <div className="warning-message">
          30秒无操作将自动进入递归编码模式
        </div>
      )}
    </div>
  );
};

/**
 * 状态徽章组件
 * 用于展示服务状态
 */

import './Charts.css';

export type StatusType = 'healthy' | 'degraded' | 'down' | 'unknown' | 'running' | 'idle' | 'error';

interface StatusBadgeProps {
  status: StatusType;
  text?: string;
  showDot?: boolean;
  size?: 'small' | 'medium' | 'large';
  className?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  text,
  showDot = true,
  size = 'medium',
  className = ''
}) => {
  const statusConfig = {
    healthy: { color: 'var(--color-success)', text: '健康', pulse: false },
    running: { color: 'var(--color-success)', text: '运行中', pulse: true },
    degraded: { color: 'var(--color-warning)', text: '降级', pulse: false },
    down: { color: 'var(--color-error)', text: '故障', pulse: false },
    unknown: { color: 'var(--text-muted)', text: '未知', pulse: false },
    idle: { color: 'var(--color-primary)', text: '空闲', pulse: false },
    error: { color: 'var(--color-error)', text: '错误', pulse: false }
  };

  const config = statusConfig[status] || statusConfig.unknown;
  const displayText = text || config.text;

  const sizeClasses = {
    small: 'badge-small',
    medium: 'badge-medium',
    large: 'badge-large'
  };

  return (
    <span 
      className={`status-badge ${sizeClasses[size]} ${className}`}
      style={{ color: config.color }}
    >
      {showDot && (
        <span 
          className={`status-dot ${config.pulse ? 'pulse' : ''}`}
          style={{ backgroundColor: config.color }}
        />
      )}
      <span className="status-text">{displayText}</span>
    </span>
  );
};

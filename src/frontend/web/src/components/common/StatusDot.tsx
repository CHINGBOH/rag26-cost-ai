/**
 * 状态点：用 CSS 圆点替代 🟢🟡🔴 emoji
 */

import './StatusDot.css';

export type StatusKind = 'healthy' | 'degraded' | 'unhealthy' | 'unknown';

interface StatusDotProps {
  status: string;
  label?: string;
  size?: 'sm' | 'md';
}

function classify(status: string): StatusKind {
  const s = status.toLowerCase();
  if (s === 'healthy' || s === 'ok' || s === 'online' || s === '在线') return 'healthy';
  if (s === 'degraded' || s === 'warn' || s === 'warning') return 'degraded';
  if (s === 'unknown' || s === '—' || !s) return 'unknown';
  return 'unhealthy';
}

export const StatusDot: React.FC<StatusDotProps> = ({ status, label, size = 'md' }) => {
  const kind = classify(status);
  return (
    <span className={`status-dot-wrap size-${size}`}>
      <span className={`status-dot status-${kind}`} aria-hidden />
      {label && <span className="status-dot-label">{label}</span>}
    </span>
  );
};

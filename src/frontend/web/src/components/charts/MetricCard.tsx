/**
 * 指标卡片组件
 * 展示单个关键指标
 */

import './Charts.css';

interface MetricCardProps {
  title: string;
  value: string | number;
  unit?: string;
  trend?: 'up' | 'down' | 'stable';
  trendValue?: string;
  status?: 'good' | 'warning' | 'critical' | 'neutral';
  icon?: string;
  subtitle?: string;
  onClick?: () => void;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  unit = '',
  trend,
  trendValue,
  status = 'neutral',
  icon,
  subtitle,
  onClick
}) => {
  const statusColors = {
    good: 'var(--color-success)',
    warning: 'var(--color-warning)',
    critical: 'var(--color-error)',
    neutral: 'var(--color-primary)'
  };

  const trendIcons = {
    up: '↑',
    down: '↓',
    stable: '→'
  };

  const trendColors = {
    up: 'var(--color-success)',
    down: 'var(--color-error)',
    stable: 'var(--text-muted)'
  };

  return (
    <div 
      className={`metric-card ${onClick ? 'clickable' : ''}`}
      onClick={onClick}
      style={{ borderLeftColor: statusColors[status] }}
    >
      <div className="metric-header">
        {icon && <span className="metric-icon">{icon}</span>}
        <span className="metric-title">{title}</span>
      </div>
      
      <div className="metric-value-row">
        <span className="metric-value" style={{ color: statusColors[status] }}>
          {value}
        </span>
        {unit && <span className="metric-unit">{unit}</span>}
      </div>
      
      {subtitle && <div className="metric-subtitle">{subtitle}</div>}
      
      {trend && (
        <div className="metric-trend" style={{ color: trendColors[trend] }}>
          <span className="trend-icon">{trendIcons[trend]}</span>
          {trendValue && <span className="trend-value">{trendValue}</span>}
        </div>
      )}
    </div>
  );
};

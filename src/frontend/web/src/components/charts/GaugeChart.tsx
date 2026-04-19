/**
 * 仪表盘/环形图组件
 * 用于展示健康度、完成度等百分比指标
 */

import './Charts.css';

interface GaugeChartProps {
  value: number;  // 0-100
  size?: number;
  strokeWidth?: number;
  color?: string;
  label?: string;
  sublabel?: string;
  className?: string;
}

export const GaugeChart: React.FC<GaugeChartProps> = ({
  value,
  size = 120,
  strokeWidth = 10,
  color,
  label,
  sublabel,
  className = ''
}) => {
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * Math.PI * 2;
  const offset = circumference - (value / 100) * circumference;
  
  const center = size / 2;
  
  // 自动选择颜色
  const getColor = () => {
    if (color) return color;
    if (value >= 80) return 'var(--color-success)';
    if (value >= 60) return 'var(--color-warning)';
    return 'var(--color-error)';
  };

  const chartColor = getColor();

  return (
    <div className={`gauge-chart ${className}`} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {/* 背景圆环 */}
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="var(--border-default)"
          strokeWidth={strokeWidth}
        />
        
        {/* 进度圆环 */}
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke={chartColor}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform={`rotate(-90 ${center} ${center})`}
          style={{ transition: 'stroke-dashoffset 0.5s ease' }}
        />
      </svg>
      
      {/* 中心文本 */}
      <div className="gauge-center">
        <div className="gauge-value" style={{ color: chartColor }}>
          {Math.round(value)}%
        </div>
        {label && <div className="gauge-label">{label}</div>}
        {sublabel && <div className="gauge-sublabel">{sublabel}</div>}
      </div>
    </div>
  );
};

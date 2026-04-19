/**
 * 雷达图组件
 * 用于展示质量指标的多维评估
 */

import { useMemo } from 'react';
import './Charts.css';

interface RadarData {
  label: string;
  value: number;  // 0-1
  color?: string;
}

interface RadarChartProps {
  data: RadarData[];
  size?: number;
  className?: string;
}

export const RadarChart: React.FC<RadarChartProps> = ({ 
  data, 
  size = 200,
  className = '' 
}) => {
  const center = size / 2;
  const radius = size * 0.35;
  
  const axes = useMemo(() => {
    const angleStep = (Math.PI * 2) / data.length;
    return data.map((item, index) => {
      const angle = index * angleStep - Math.PI / 2;
      return {
        ...item,
        angle,
        x: center + Math.cos(angle) * radius,
        y: center + Math.sin(angle) * radius,
        valueX: center + Math.cos(angle) * radius * item.value,
        valueY: center + Math.sin(angle) * radius * item.value,
      };
    });
  }, [data, center, radius]);

  const pathData = useMemo(() => {
    if (axes.length === 0) return '';
    return axes.map((axis, i) => 
      `${i === 0 ? 'M' : 'L'} ${axis.valueX} ${axis.valueY}`
    ).join(' ') + ' Z';
  }, [axes]);

  const gridLevels = [0.2, 0.4, 0.6, 0.8, 1.0];

  return (
    <svg 
      className={`radar-chart ${className}`} 
      width={size} 
      height={size}
      viewBox={`0 0 ${size} ${size}`}
    >
      {/* 网格线 */}
      {gridLevels.map(level => {
        const levelRadius = radius * level;
        const points = axes.map(axis => {
          const x = center + Math.cos(axis.angle) * levelRadius;
          const y = center + Math.sin(axis.angle) * levelRadius;
          return `${x},${y}`;
        }).join(' ');
        
        return (
          <polygon
            key={level}
            points={points}
            fill="none"
            stroke="var(--border-default)"
            strokeWidth="1"
            strokeDasharray={level === 1 ? undefined : "3,3"}
          />
        );
      })}

      {/* 轴线 */}
      {axes.map((axis, index) => (
        <line
          key={index}
          x1={center}
          y1={center}
          x2={axis.x}
          y2={axis.y}
          stroke="var(--border-default)"
          strokeWidth="1"
        />
      ))}

      {/* 数据区域 */}
      <path
        d={pathData}
        fill="rgba(34, 197, 94, 0.2)"
        stroke="var(--color-success)"
        strokeWidth="2"
      />

      {/* 数据点 */}
      {axes.map((axis, index) => (
        <circle
          key={index}
          cx={axis.valueX}
          cy={axis.valueY}
          r="4"
          fill={axis.color || 'var(--color-success)'}
          stroke="var(--text-inverse)"
          strokeWidth="2"
        />
      ))}

      {/* 标签 */}
      {axes.map((axis, index) => {
        const labelRadius = radius + 20;
        const labelX = center + Math.cos(axis.angle) * labelRadius;
        const labelY = center + Math.sin(axis.angle) * labelRadius;
        
        return (
          <text
            key={index}
            x={labelX}
            y={labelY}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize="10"
            fill="var(--text-muted)"
          >
            {axis.label}
          </text>
        );
      })}

      {/* 数值标签 */}
      {axes.map((axis, index) => (
        <text
          key={`value-${index}`}
          x={axis.valueX}
          y={axis.valueY - 8}
          textAnchor="middle"
          fontSize="9"
          fill={axis.color || 'var(--color-success)'}
          fontWeight="bold"
        >
          {(axis.value * 100).toFixed(0)}%
        </text>
      ))}
    </svg>
  );
};

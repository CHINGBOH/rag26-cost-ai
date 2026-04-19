/**
 * 漏斗图组件
 * 用于展示检索召回->精排的转化过程
 */

import './Charts.css';

interface FunnelStage {
  name: string;
  value: number;
  label?: string;
  color?: string;
}

interface FunnelChartProps {
  stages: FunnelStage[];
  width?: number;
  height?: number;
  className?: string;
}

export const FunnelChart: React.FC<FunnelChartProps> = ({
  stages,
  width = 300,
  height = 200,
  className = ''
}) => {
  if (stages.length === 0) return null;

  const maxValue = Math.max(...stages.map(s => s.value));
  const stageHeight = height / stages.length;
  const colors = ['var(--color-primary)', 'var(--color-info)', 'var(--color-info)', 'var(--color-success)', 'var(--color-success)'];

  return (
    <div className={`funnel-chart ${className}`} style={{ width, height }}>
      <svg width={width} height={height}>
        {stages.map((stage, index) => {
          const ratio = stage.value / maxValue;
          const stageWidth = width * 0.8 * ratio;
          const x = (width - stageWidth) / 2;
          const y = index * stageHeight;
          
          // 梯形效果
          const nextRatio = index < stages.length - 1 
            ? stages[index + 1].value / maxValue 
            : ratio * 0.6;
          const nextWidth = width * 0.8 * nextRatio;
          const nextX = (width - nextWidth) / 2;
          
          const path = `
            M ${x} ${y}
            L ${x + stageWidth} ${y}
            L ${nextX + nextWidth} ${y + stageHeight - 4}
            L ${nextX} ${y + stageHeight - 4}
            Z
          `;

          return (
            <g key={index}>
              <path
                d={path}
                fill={stage.color || colors[index % colors.length]}
                opacity={0.8}
              />
              <text
                x={width / 2}
                y={y + stageHeight / 2}
                textAnchor="middle"
                dominantBaseline="middle"
                fill="var(--text-primary)"
                fontSize="11"
                fontWeight="bold"
              >
                {stage.name}
              </text>
              <text
                x={width / 2}
                y={y + stageHeight / 2 + 14}
                textAnchor="middle"
                dominantBaseline="middle"
                fill="var(--text-primary)"
                fontSize="10"
              >
                {stage.label || stage.value}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
};

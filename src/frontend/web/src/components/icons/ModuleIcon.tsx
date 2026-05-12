/**
 * 功能模块 SVG 图标系统
 *
 * 设计原则：
 * - 纯 SVG 内联，无外部依赖，跨平台渲染一致
 * - 单色 currentColor，自动跟随父元素颜色
 * - Outline 风格，2px 描边，stroke-linecap/linejoin: round
 * - 最少路径数表达最强特征，无装饰细节
 * - 与 Apple SF Symbol 设计语言对齐
 */

import type { SVGProps } from 'react';

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

const base = (size: number): SVGProps<SVGSVGElement> => ({
  width: size,
  height: size,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
});

/* ── 咨询馆员：两个弧形对话节点，右下角小圆点表示「回应」 ── */
export function LibraryIcon({ size = 16, ...p }: IconProps) {
  return (
    <svg {...base(size)} {...p}>
      {/* 主气泡：圆润矩形 */}
      <path d="M4 5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8l-4 3V5z" />
      {/* 内部三个横线节点，暗示知识条目 */}
      <line x1="8" y1="8" x2="16" y2="8" />
      <line x1="8" y1="12" x2="13" y2="12" />
    </svg>
  );
}

/* ── 管道：三个圆节点 + 两段连接线，体现流向 ── */
export function PipelineIcon({ size = 16, ...p }: IconProps) {
  return (
    <svg {...base(size)} {...p}>
      {/* 左节点 */}
      <circle cx="4" cy="12" r="2" />
      {/* 中节点 */}
      <circle cx="12" cy="6" r="2" />
      {/* 右节点 */}
      <circle cx="20" cy="12" r="2" />
      {/* 连接线 */}
      <line x1="6" y1="11" x2="10" y2="7" />
      <line x1="14" y1="7" x2="18" y2="11" />
    </svg>
  );
}

/* ── 综合面板：四象限格栅，克制几何 ── */
export function HubIcon({ size = 16, ...p }: IconProps) {
  return (
    <svg {...base(size)} {...p}>
      {/* 外框 */}
      <rect x="3" y="3" width="18" height="18" rx="2" />
      {/* 十字分割线 */}
      <line x1="12" y1="3" x2="12" y2="21" />
      <line x1="3" y1="12" x2="21" y2="12" />
    </svg>
  );
}

/* ── 运行时：动态脉冲圈，中心实心点 ── */
export function RuntimeIcon({ size = 16, ...p }: IconProps) {
  return (
    <svg {...base(size)} {...p}>
      {/* 外环 */}
      <circle cx="12" cy="12" r="9" />
      {/* 中间环 */}
      <circle cx="12" cy="12" r="5" />
      {/* 中心点（fill） */}
      <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

/* ── 检索：菱形轮廓 + 手柄线，非常规圆形放大镜 ── */
export function SearchIcon({ size = 16, ...p }: IconProps) {
  return (
    <svg {...base(size)} {...p}>
      {/* 菱形 */}
      <path d="M12 3 L21 12 L12 21 L3 12 Z" />
      {/* 对角手柄 */}
      <line x1="18" y1="18" x2="22" y2="22" />
    </svg>
  );
}

/* ── 运维：仪表盘半圆 + 指针 ── */
export function OpsIcon({ size = 16, ...p }: IconProps) {
  return (
    <svg {...base(size)} {...p}>
      {/* 半圆表盘 */}
      <path d="M4 16 A9 9 0 0 1 20 16" />
      {/* 左右刻度 */}
      <line x1="4" y1="16" x2="5.5" y2="13" />
      <line x1="20" y1="16" x2="18.5" y2="13" />
      {/* 指针：指向右上方 */}
      <line x1="12" y1="16" x2="17" y2="10" />
      {/* 中心圆 */}
      <circle cx="12" cy="16" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

/* ── 系统：六边形蜂窝，单个正六边形 ── */
export function SystemIcon({ size = 16, ...p }: IconProps) {
  return (
    <svg {...base(size)} {...p}>
      {/* 正六边形 */}
      <polygon points="12,3 20.5,7.5 20.5,16.5 12,21 3.5,16.5 3.5,7.5" />
      {/* 三条辐射线，强调系统结构感 */}
      <line x1="12" y1="3" x2="12" y2="21" />
      <line x1="3.5" y1="7.5" x2="20.5" y2="16.5" />
      <line x1="20.5" y1="7.5" x2="3.5" y2="16.5" />
    </svg>
  );
}

/* ── 学习：上升折线 + 坐标轴 ── */
export function LearningIcon({ size = 16, ...p }: IconProps) {
  return (
    <svg {...base(size)} {...p}>
      {/* 坐标轴 */}
      <line x1="4" y1="20" x2="4" y2="4" />
      <line x1="4" y1="20" x2="21" y2="20" />
      {/* 上升折线数据 */}
      <polyline points="4,18 8,14 13,10 18,6" />
      {/* 最高点强调圆点 */}
      <circle cx="18" cy="6" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

/* ── AI 助手：三节点神经网络（左1→中2→右1），简洁 ── */
export function AgentsIcon({ size = 16, ...p }: IconProps) {
  return (
    <svg {...base(size)} {...p}>
      {/* 左输入节点 */}
      <circle cx="3" cy="12" r="2" />
      {/* 中间两节点 */}
      <circle cx="12" cy="7" r="2" />
      <circle cx="12" cy="17" r="2" />
      {/* 右输出节点 */}
      <circle cx="21" cy="12" r="2" />
      {/* 连接线 */}
      <line x1="5" y1="12" x2="10" y2="8" />
      <line x1="5" y1="12" x2="10" y2="16" />
      <line x1="14" y1="8" x2="19" y2="12" />
      <line x1="14" y1="16" x2="19" y2="12" />
    </svg>
  );
}

/* ── 统一入口 ── */
const ICON_MAP = {
  library:  LibraryIcon,
  pipeline: PipelineIcon,
  hub:      HubIcon,
  runtime:  RuntimeIcon,
  search:   SearchIcon,
  ops:      OpsIcon,
  system:   SystemIcon,
  learning: LearningIcon,
  agents:   AgentsIcon,
} as const;

export type ModuleName = keyof typeof ICON_MAP;

interface ModuleIconProps extends IconProps {
  name: ModuleName;
}

export function ModuleIcon({ name, size = 16, ...p }: ModuleIconProps) {
  const Icon = ICON_MAP[name];
  return <Icon size={size} {...p} />;
}

/**
 * 主题配置 - 统一浅色/深色两种风格
 */

export type ThemeType = 'light' | 'dark';

export interface ThemeColors {
  // 背景色
  bgPrimary: string;
  bgSurface: string;
  bgElevated: string;
  bgHover: string;
  
  // 文字色
  textPrimary: string;
  textSecondary: string;
  textMuted: string;
  textInverse: string;
  
  // 边框色
  borderDefault: string;
  borderHighlight: string;
  
  // 主题色
  primary: string;
  primaryHover: string;
  primaryLight: string;
  
  // 功能色
  success: string;
  warning: string;
  error: string;
  info: string;
}

// 浅色主题 - 白底
export const lightTheme: ThemeColors = {
  bgPrimary: '#ffffff',
  bgSurface: '#f8fafc',
  bgElevated: '#ffffff',
  bgHover: '#f1f5f9',
  
  textPrimary: '#000000',
  textSecondary: '#1e293b',
  textMuted: '#475569',
  textInverse: '#ffffff',
  
  borderDefault: '#e2e8f0',
  borderHighlight: '#3b82f6',
  
  primary: '#3b82f6',
  primaryHover: '#2563eb',
  primaryLight: '#dbeafe',
  
  success: '#22c55e',
  warning: '#f59e0b',
  error: '#ef4444',
  info: '#06b6d4'
};

// 深色主题 - 深蓝底
export const darkTheme: ThemeColors = {
  bgPrimary: '#0f172a',
  bgSurface: '#1e293b',
  bgElevated: '#334155',
  bgHover: '#475569',
  
  textPrimary: '#f8fafc',
  textSecondary: '#cbd5e1',
  textMuted: '#94a3b8',
  textInverse: '#0f172a',
  
  borderDefault: '#334155',
  borderHighlight: '#3b82f6',
  
  primary: '#3b82f6',
  primaryHover: '#60a5fa',
  primaryLight: 'rgba(59, 130, 246, 0.2)',
  
  success: '#22c55e',
  warning: '#f59e0b',
  error: '#ef4444',
  info: '#06b6d4'
};

// 主题管理
let currentTheme: ThemeType = 'dark';

export function setTheme(theme: ThemeType) {
  currentTheme = theme;
  const colors = theme === 'light' ? lightTheme : darkTheme;
  
  // 应用到 CSS 变量
  const root = document.documentElement;
  Object.entries(colors).forEach(([key, value]) => {
    const cssVar = '--' + key.replace(/[A-Z]/g, m => '-' + m.toLowerCase());
    root.style.setProperty(cssVar, value);
  });
  
  // 设置 data-theme 属性
  root.setAttribute('data-theme', theme);
  
  // 保存到本地存储
  localStorage.setItem('theme', theme);
}

export function getTheme(): ThemeType {
  return currentTheme;
}

export function toggleTheme() {
  setTheme(currentTheme === 'light' ? 'dark' : 'light');
}

export function initTheme() {
  // 从本地存储恢复
  const saved = localStorage.getItem('theme') as ThemeType;
  if (saved && (saved === 'light' || saved === 'dark')) {
    setTheme(saved);
  } else {
    // 默认跟随系统
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    setTheme(prefersDark ? 'dark' : 'light');
  }
}

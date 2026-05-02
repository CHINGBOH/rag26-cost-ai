/**
 * theme.ts — dark-only stub
 * Light mode removed. These exports are kept for archive-page compatibility.
 */

export type ThemeType = 'light' | 'dark';

export interface ThemeColors {
  bgPrimary: string; bgSurface: string; bgElevated: string; bgHover: string;
  textPrimary: string; textSecondary: string; textMuted: string; textInverse: string;
  borderDefault: string; borderHighlight: string;
  primary: string; primaryHover: string; primaryLight: string;
  success: string; warning: string; error: string; info: string;
}

export const darkTheme: ThemeColors = {
  bgPrimary: '#0c0e14', bgSurface: '#13161f', bgElevated: '#1a1e2d', bgHover: '#232a38',
  textPrimary: '#f0f4ff', textSecondary: '#c8cdd7', textMuted: '#8892a4', textInverse: '#0c0e14',
  borderDefault: '#252b3a', borderHighlight: '#5b8def',
  primary: '#5b8def', primaryHover: '#7ba3f5', primaryLight: 'rgba(91,141,239,0.14)',
  success: '#22c55e', warning: '#f59e0b', error: '#ef4444', info: '#06b6d4',
};

// Alias for archive-page imports
export const lightTheme: ThemeColors = darkTheme;

export function getTheme(): ThemeType { return 'dark'; }
export function setTheme(_theme: ThemeType) { /* no-op */ }
export function toggleTheme() { /* no-op */ }
export function initTheme() { /* no-op */ }


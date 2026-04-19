/**
 * 主题切换按钮
 */

import { useState, useEffect } from 'react';
import { getTheme, toggleTheme, ThemeType } from '../../config/theme';

export const ThemeToggle: React.FC = () => {
  const [theme, setThemeState] = useState<ThemeType>(getTheme());

  useEffect(() => {
    // 监听主题变化
    const handleStorageChange = () => {
      setThemeState(getTheme());
    };
    window.addEventListener('storage', handleStorageChange);
    return () => window.removeEventListener('storage', handleStorageChange);
  }, []);

  const handleToggle = () => {
    toggleTheme();
    setThemeState(getTheme());
  };

  return (
    <button 
      className="theme-toggle-btn"
      onClick={handleToggle}
      title={theme === 'light' ? '切换到深色模式' : '切换到浅色模式'}
    >
      {theme === 'light' ? '🌙' : '☀️'}
    </button>
  );
};

/**
 * Dashboard 主布局组件
 * 包含侧边栏、顶部导航、标签页内容区
 */

import { useState, ReactNode } from 'react';
import { StatusBadge } from '../charts/StatusBadge';
import { useRecursionStore } from '../../stores/recursionStore';
import { ThemeToggle } from '../common/ThemeToggle';
import './Layout.css';

export type DashboardTab = 
  | 'overview' 
  | 'chat'
  | 'sessions' 
  | 'infrastructure' 
  | 'retrieval' 
  | 'system' 
  | 'config';

interface DashboardLayoutProps {
  children: Record<DashboardTab, ReactNode>;
  activeAlerts?: number;
  overallHealth?: 'healthy' | 'degraded' | 'critical';
}

const tabLabels: Record<DashboardTab, { label: string; icon: string }> = {
  overview: { label: '总览', icon: '📊' },
  chat: { label: '对话', icon: '💬' },
  sessions: { label: '会话', icon: '🗂️' },
  infrastructure: { label: '基础设施', icon: '🏗️' },
  retrieval: { label: '检索流程', icon: '🔍' },
  system: { label: '系统', icon: '⚙️' },
  config: { label: '配置', icon: '🔧' }
};

export const DashboardLayout: React.FC<DashboardLayoutProps> = ({
  children,
  activeAlerts = 0,
  overallHealth = 'healthy'
}) => {
  const [activeTab, setActiveTab] = useState<DashboardTab>('overview');
  const sessions = useRecursionStore(state => state.sessions);
  
  const activeSessionCount = Array.from(sessions.values()).filter(
    s => s.currentState !== 'completed' && s.currentState !== 'failed'
  ).length;

  const healthStatusMap = {
    healthy: 'healthy' as const,
    degraded: 'degraded' as const,
    critical: 'down' as const
  };

  return (
    <div className="dashboard-layout">
      {/* 顶部导航 */}
      <header className="dashboard-header">
        <div className="header-left">
          <h1 className="dashboard-title">
            <span className="title-icon">🔄</span>
            RAG Dashboard
          </h1>
          <span className="env-badge">递归模式</span>
        </div>
        
        <div className="header-center">
          <div className="header-stats">
            <div className="header-stat">
              <span className="stat-label">活跃会话</span>
              <span className="stat-value">{activeSessionCount}</span>
            </div>
            <div className="header-stat">
              <span className="stat-label">系统状态</span>
              <StatusBadge 
                status={healthStatusMap[overallHealth]} 
                size="small"
              />
            </div>
          </div>
        </div>
        
        <div className="header-right">
          {activeAlerts > 0 && (
            <div className="alert-indicator">
              <span className="alert-icon">🔔</span>
              <span className="alert-count">{activeAlerts}</span>
            </div>
          )}
          <ThemeToggle />
          <button className="settings-btn">⚙️</button>
        </div>
      </header>

      <div className="dashboard-body">
        {/* 左侧标签栏 */}
        <nav className="dashboard-tabs">
          {(Object.keys(tabLabels) as DashboardTab[]).map(tab => (
            <button
              key={tab}
              className={`tab-btn ${activeTab === tab ? 'active' : ''}`}
              onClick={() => setActiveTab(tab)}
            >
              <span className="tab-icon">{tabLabels[tab].icon}</span>
              <span className="tab-label">{tabLabels[tab].label}</span>
            </button>
          ))}
        </nav>

        {/* 主内容区 */}
        <main className="dashboard-content">
          <div className="content-header">
            <h2 className="content-title">
              {tabLabels[activeTab].icon} {tabLabels[activeTab].label}
            </h2>
          </div>
          <div className="content-body">
            {children[activeTab]}
          </div>
        </main>
      </div>
    </div>
  );
};

/**
 * 主应用组件
 * 整合所有 Dashboard 面板
 * 使用 React Router 实现多页面导航
 */

import { useEffect, useCallback, useState } from 'react';
import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';

import { DashboardEvent } from '@rag/shared';
import { useWebSocket } from './hooks/useWebSocket';
import { useRecursionStore } from './stores';
import { useInfrastructureStore } from './stores';
import { DashboardLayout } from './components/layout/DashboardLayout';
import { OverviewDashboard } from './components/dashboard/OverviewDashboard';
import { SessionsPanel } from './components/dashboard/SessionsPanel';
import { ConfigPanel } from './components/dashboard/ConfigPanel';
import { ChatInterface } from './components/chat/ChatInterface';
import { InfrastructurePanel } from './components/infrastructure/InfrastructurePanel';
import { RetrievalFlowPanel } from './components/retrieval/RetrievalFlowPanel';
import { SystemMonitorPanel } from './components/system/SystemMonitorPanel';
import { QueryInput } from './components/QueryInput';
import { SilenceCountdown } from './components/SilenceCountdown';
import { SearchPanel } from './components/SearchPanel';
import { UploadPanel } from './components/UploadPanel';
import { DataPipelineDashboard } from './components/pipeline/DataPipelineDashboard';
import { AgentLoopPage } from './components/AgentLoopPage';
import AgentRuntimeDeepDive from './components/common/AgentRuntimeDeepDive';
import AgentRuntimeFolk from './components/common/AgentRuntimeFolk';
import DocsReader from './components/common/DocsReader';
import './App.css';
import './styles/theme.css';
import { initTheme } from './config/theme';
import { authFetch, ensureAuth } from './utils/auth';

// 导航链接样式 - 轻量级简约风格
const navStyle = {
  display: 'flex',
  gap: '8px',
  padding: '12px 24px',
  backgroundColor: 'var(--bg-primary)',
  borderBottom: '1px solid var(--border-default)',
  boxShadow: '0 1px 3px rgba(0,0,0,0.05)'
};

const linkStyle = (isActive: boolean) => ({
  padding: '8px 16px',
  backgroundColor: isActive ? 'var(--color-primary)' : 'transparent',
  color: isActive ? 'var(--text-inverse)' : 'var(--text-secondary)',
  border: 'none',
  borderRadius: '6px',
  cursor: 'pointer',
  textDecoration: 'none',
  display: 'inline-block',
  fontSize: '14px',
  fontWeight: isActive ? '500' : '400',
  transition: 'all 0.2s ease'
});

// 导航组件
function Navigation() {
  const location = useLocation();

  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/';
    return location.pathname.startsWith(path);
  };

  return (
    <div style={navStyle}>
      <Link to="/" style={linkStyle(isActive('/'))}>
        控制塔
      </Link>
      <Link to="/agent" style={linkStyle(isActive('/agent'))}>
        Agent 调试
      </Link>
      <Link to="/search" style={linkStyle(isActive('/search'))}>
        文档检索
      </Link>
      <Link to="/upload" style={linkStyle(isActive('/upload'))}>
        文档上传
      </Link>
      <Link to="/pipeline" style={linkStyle(isActive('/pipeline'))}>
        数据管道
      </Link>
      <Link to="/deep-dive" style={linkStyle(isActive('/deep-dive'))}>
        深度调研
      </Link>
      <Link to="/deep-dive-folk" style={linkStyle(isActive('/deep-dive-folk'))}>
        大白话版
      </Link>
      <Link to="/docs" style={linkStyle(isActive('/docs'))}>
        文档库
      </Link>
    </div>
  );
}

// 控制塔页面（原来的 dashboard tab）
function DashboardPage() {
  const { isConnected, vitals, subscribe, startRecursion } = useWebSocket();
  const { addEvent, updateSession } = useRecursionStore();
  const { setOverview, addAlert } = useInfrastructureStore();

  const [yoloStatus, setYoloStatus] = useState<Map<string, {
    isActive: boolean;
    currentLayer?: number;
    totalLayers?: number;
  }>>(new Map());

  // 处理 WebSocket 事件
  useEffect(() => {
    const unsubscribe = subscribe((event: DashboardEvent) => {
      addEvent(event);

      if (event.sessionId && event.sessionId !== 'system') {
        fetchSessionData(event.sessionId);
      }

      if (event.type === 'yolo:layer_start') {
        setYoloStatus(prev => new Map(prev).set(event.sessionId, {
          isActive: true,
          currentLayer: event.payload?.layer,
          totalLayers: event.payload?.totalLayers
        }));
      }

      if (event.type === 'yolo:completed' || event.type === 'yolo:failed') {
        setYoloStatus(prev => new Map(prev).set(event.sessionId, {
          isActive: false
        }));
      }

      if (event.type === 'vitals_update' && event.payload) {
        setOverview({
          overallHealth: event.payload.healthScore > 80 ? 'healthy' :
                        event.payload.healthScore > 50 ? 'degraded' : 'critical',
          healthyComponents: 8,
          totalComponents: 10,
          activeAlerts: 0,
          criticalAlerts: 0,
          llmStatus: 'healthy',
          retrievalStatus: 'healthy',
          storageStatus: 'healthy',
          pipelineStatus: 'healthy',
          lastUpdated: Date.now()
        });
      }

      if (event.type === 'anomaly_alert') {
        addAlert({
          id: `${Date.now()}-${crypto.randomUUID()}`,
          level: 'warning',
          category: 'performance',
          component: 'recursion',
          title: '异常检测',
          message: event.payload?.message || '检测到异常',
          timestamp: Date.now(),
          acknowledged: false,
          resolved: false
        });
      }
    });

    return () => { unsubscribe(); };
  }, [subscribe, addEvent, setOverview, addAlert]);

  const fetchSessionData = useCallback(async (_sessionId: string) => {
    try {
      const response = await authFetch(`/api/sessions`);
      const data = await response.json();
      data.forEach((session: any) => updateSession(session));
    } catch (err) {
      console.error('Failed to fetch session data:', err);
    }
  }, [updateSession]);

  useEffect(() => {
    const interval = setInterval(() => fetchSessionData(''), 1000);
    return () => clearInterval(interval);
  }, [fetchSessionData]);

  const handleQuerySubmit = useCallback((query: string) => {
    startRecursion(query);
  }, [startRecursion]);

  const sendActivity = useCallback((sessionId: string) => {
    authFetch(`/api/activity`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId })
    });
  }, []);

  const activeSessionId = useRecursionStore(state => state.activeSessionId);
  const sessions = useRecursionStore(state => state.sessions);
  const activeSession = activeSessionId ? sessions.get(activeSessionId) : null;
  const activeYolo = activeSessionId ? yoloStatus.get(activeSessionId) : undefined;
  const alerts = useInfrastructureStore(state => state.alerts);
  const unresolvedAlerts = alerts.filter(a => !a.resolved);

  const overallHealth = vitals?.healthScore && vitals.healthScore > 80 ? 'healthy' :
                        vitals?.healthScore && vitals.healthScore > 50 ? 'degraded' : 'critical';

  return (
    <DashboardLayout
      overallHealth={overallHealth}
      activeAlerts={unresolvedAlerts.length}
    >
      {{
        overview: (
          <div className="tab-content">
            <OverviewDashboard />

            <div className="query-section">
              <QueryInput
                onSubmit={handleQuerySubmit}
                disabled={!isConnected}
              />
            </div>

            {activeYolo?.isActive && (
              <div className="yolo-panel">
                <h4>⚡ YOLO递归编码中</h4>
                <div className="yolo-progress">
                  第 {activeYolo.currentLayer} / {activeYolo.totalLayers} 层
                </div>
                <div className="yolo-bar">
                  <div
                    className="yolo-fill"
                    style={{
                      width: `${((activeYolo.currentLayer || 0) / (activeYolo.totalLayers || 5)) * 100}%`
                    }}
                  />
                </div>
              </div>
            )}

            {activeSession && (
              <SilenceCountdown
                sessionId={activeSession.id}
                lastActivityAt={activeSession.updatedAt}
                silenceThresholdMs={30000}
                isYoloActive={activeYolo?.isActive || false}
                onActivity={() => sendActivity(activeSession.id)}
              />
            )}
          </div>
        ),
        chat: <ChatInterface />,
        sessions: <SessionsPanel />,
        infrastructure: <InfrastructurePanel />,
        retrieval: <RetrievalFlowPanel />,
        system: <SystemMonitorPanel />,
        config: <ConfigPanel />
      }}
    </DashboardLayout>
  );
}

// 主应用
function App() {
  // 初始化主题和认证
  useEffect(() => {
    initTheme();
    ensureAuth().catch(err => console.error('自动登录失败:', err));
  }, []);

  return (
    <BrowserRouter>
      <Navigation />
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/agent" element={<AgentLoopPage />} />
        <Route path="/search" element={<SearchPanel />} />
        <Route path="/upload" element={<UploadPanel />} />
        <Route path="/pipeline" element={<DataPipelineDashboard />} />
        <Route path="/deep-dive" element={<AgentRuntimeDeepDive />} />
        <Route path="/deep-dive-folk" element={<AgentRuntimeFolk />} />
        <Route path="/docs" element={<DocsReader />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
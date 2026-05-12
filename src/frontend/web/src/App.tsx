/**
 * 主应用 — 三板块架构 (#141)
 * 💬 咨询  /
 * ⛓  管道  /pipeline
 * 🧩 综合  /hub/:tab  (运行时·检索·运维·系统·学习·Agent)
 */

import { useEffect, Component } from 'react';
import type { ReactNode } from 'react';
import { BrowserRouter, Routes, Route, Link, Navigate, useLocation } from 'react-router-dom';

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null };
  static getDerivedStateFromError(e: Error) { return { error: e }; }
  render() {
    if (this.state.error) {
      const e = this.state.error as Error;
      return (
        <div style={{ padding: 32, fontFamily: 'monospace', color: '#dc2626', background: '#fef2f2', minHeight: '100vh' }}>
          <h2>⚠ React 渲染错误（请截图发给 Copilot）</h2>
          <pre style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{e.message}</pre>
          <pre style={{ whiteSpace: 'pre-wrap', fontSize: 11, color: '#6b7280' }}>{e.stack}</pre>
        </div>
      );
    }
    return this.props.children;
  }
}

// Core pages
import { LibraryPage }   from './pages/LibraryPage';
import { AgentChat }     from './pages/AgentChat';
import { PipelinePage }  from './pages/PipelinePage';

// Hub wrapper
import { DashHub } from './hubs/DashHub';

// Archive pages — lazy loaded to avoid broken-import cascade
import { lazy, Suspense } from 'react';
const AgentRuntimeDeepDive = lazy(() => import('./components/common/AgentRuntimeDeepDive'));
const AgentRuntimeFolk     = lazy(() => import('./components/common/AgentRuntimeFolk'));
const DocsReader           = lazy(() => import('./components/common/DocsReader'));

import './App.css';
import './styles/theme.css';

const NAV_ITEMS = [
  { path: '/',         label: '咨询馆员', icon: '📚' },
  { path: '/pipeline', label: '管道',    icon: '⛓'  },
  { path: '/hub',      label: '综合面板', icon: '🧩' },
];

const ROUTE_MODULE: [string, string][] = [
  ['/hub',      'hub'],
  ['/pipeline', 'pipeline'],
  ['/pro',      'library'],
  ['/',         'library'],
];

function getModule(pathname: string): string {
  for (const [prefix, mod] of ROUTE_MODULE) {
    if (pathname === prefix || (prefix !== '/' && pathname.startsWith(prefix + '/'))) {
      return mod;
    }
  }
  return 'library';
}

function Navigation() {
  const location = useLocation();

  useEffect(() => {
    document.documentElement.dataset.module = getModule(location.pathname);
  }, [location.pathname]);

  const isActive = (path: string) =>
    path === '/'
      ? location.pathname === '/'
      : location.pathname.startsWith(path);

  return (
    <header className="app-nav">
      <div className="nav-brand">
        <span className="nav-mark">R</span>
        <span className="nav-title">RAG 智库系统</span>
      </div>

      <nav className="nav-links">
        {NAV_ITEMS.map(({ path, label, icon }) => (
          <Link
            key={path}
            to={path === '/hub' ? '/hub/runtime' : path}
            className={`nav-link ${isActive(path) ? 'active' : ''}`}
          >
            <span aria-hidden="true" className="nav-icon">{icon}</span>
            {label}
          </Link>
        ))}
      </nav>
    </header>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
    <BrowserRouter>
      <div className="app-shell">
        <Navigation />
        <main className="app-main">
          <Routes>
            {/* ── 三大板块 ── */}
            <Route path="/"         element={<LibraryPage />} />
            <Route path="/pro"      element={<AgentChat />} />
            <Route path="/pipeline" element={<PipelinePage />} />
            <Route path="/hub/:tab" element={<DashHub />} />
            <Route path="/hub"      element={<Navigate to="/hub/runtime" replace />} />

            {/* ── 旧路由重定向（向后兼容） ── */}
            <Route path="/runtime"  element={<Navigate to="/hub/runtime"  replace />} />
            <Route path="/search"   element={<Navigate to="/hub/search"   replace />} />
            <Route path="/ops"      element={<Navigate to="/hub/ops"      replace />} />
            <Route path="/system"   element={<Navigate to="/hub/system"   replace />} />
            <Route path="/learning" element={<Navigate to="/hub/learning" replace />} />
            <Route path="/agents"   element={<Navigate to="/hub/agents"   replace />} />

            {/* ── 归档页（lazy，避免 DocsReader 的 ?raw 路径导致全局崩溃） ── */}
            <Route path="/archive/deep-dive"      element={<Suspense fallback={null}><AgentRuntimeDeepDive /></Suspense>} />
            <Route path="/archive/deep-dive-folk" element={<Suspense fallback={null}><AgentRuntimeFolk /></Suspense>} />
            <Route path="/archive/docs"           element={<Suspense fallback={null}><DocsReader /></Suspense>} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
    </ErrorBoundary>
  );
}

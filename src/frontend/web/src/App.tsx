/**
 * 主应用 — 6 页架构
 * 每个页面都有真实后端 API 支撑
 */

import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';

// Core pages
import { LibraryPage } from './pages/LibraryPage';
import { AgentChat } from './pages/AgentChat';
import { AgentManagePage } from './pages/AgentManagePage';
import { AgentRuntimePage } from './pages/AgentRuntimePage';
import { SearchPage } from './pages/SearchPage';
import { PipelinePage } from './pages/PipelinePage';
import { SystemPage } from './pages/SystemPage';
import { OpsPage } from './pages/OpsPage';
import { LearningPage } from './pages/LearningPage';

// Archive pages (hidden from nav)
import AgentRuntimeDeepDive from './components/common/AgentRuntimeDeepDive';
import AgentRuntimeFolk from './components/common/AgentRuntimeFolk';
import DocsReader from './components/common/DocsReader';

import './App.css';
import './styles/theme.css';

const NAV_ITEMS = [
  { path: '/', label: '咨询馆员', icon: '📚' },
  { path: '/runtime', label: '运行时', icon: '⚡' },
  { path: '/search', label: '检索', icon: '🔍' },
  { path: '/pipeline', label: '管道', icon: '⛓' },
  { path: '/ops', label: '运维', icon: '🛡' },
  { path: '/system', label: '系统', icon: '⚙' },
  { path: '/learning', label: '学习', icon: '🧠' },
  { path: '/agents', label: 'Agent', icon: '🤖' },
];

const ROUTE_MODULE: [string, string][] = [
  ['/runtime', 'runtime'],
  ['/search',   'search'],
  ['/pipeline', 'pipeline'],
  ['/ops',      'ops'],
  ['/system',   'system'],
  ['/learning', 'learning'],
  ['/agents',   'agents'],
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

  return (
    <header className="app-nav">
      <div className="nav-brand">
        <span className="nav-mark">四</span>
        <span className="nav-title">造价知识库</span>
      </div>

      <nav className="nav-links">
        {NAV_ITEMS.map(({ path, label, icon }) => (
          <Link
            key={path}
            to={path}
            className={`nav-link ${location.pathname === path ? 'active' : ''}`}
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
    <BrowserRouter>
      <div className="app-shell">
        <Navigation />
        <main className="app-main">
          <Routes>
            <Route path="/" element={<LibraryPage />} />
            <Route path="/pro" element={<AgentChat />} />
            <Route path="/runtime" element={<AgentRuntimePage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/pipeline" element={<PipelinePage />} />
            <Route path="/ops" element={<OpsPage />} />
            <Route path="/system" element={<SystemPage />} />
            <Route path="/learning" element={<LearningPage />} />
            <Route path="/agents" element={<AgentManagePage />} />
            {/* Archive pages, hidden from nav */}
            <Route path="/archive/deep-dive" element={<AgentRuntimeDeepDive />} />
            <Route path="/archive/deep-dive-folk" element={<AgentRuntimeFolk />} />
            <Route path="/archive/docs" element={<DocsReader />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

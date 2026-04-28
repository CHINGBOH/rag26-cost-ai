/**
 * 主应用 — 6 页架构
 * 每个页面都有真实后端 API 支撑
 */

import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import { ThemeToggle } from './components/common/ThemeToggle';
import { initTheme } from './config/theme';

// Core pages
import { AgentChat } from './pages/AgentChat';
import { AgentManagePage } from './pages/AgentManagePage';
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
  { path: '/', label: 'Agent' },
  { path: '/search', label: '检索' },
  { path: '/pipeline', label: '管道' },
  { path: '/ops', label: '运维' },
  { path: '/system', label: '系统' },
  { path: '/learning', label: '学习' },
  { path: '/agents', label: 'Agents' },
] as const;

function Navigation() {
  const location = useLocation();

  return (
    <header className="app-nav">
      <div className="nav-brand">
        <span className="nav-mark">R</span>
        <span className="nav-title">RAG Dashboard</span>
      </div>

      <nav className="nav-links">
        {NAV_ITEMS.map(({ path, label }) => (
          <Link
            key={path}
            to={path}
            className={`nav-link ${location.pathname === path ? 'active' : ''}`}
          >
            {label}
          </Link>
        ))}
      </nav>

      <div className="nav-actions">
        <ThemeToggle />
      </div>
    </header>
  );
}

export default function App() {
  useEffect(() => { initTheme(); }, []);

  return (
    <BrowserRouter>
      <div className="app-shell">
        <Navigation />
        <main className="app-main">
          <Routes>
            <Route path="/" element={<AgentChat />} />
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

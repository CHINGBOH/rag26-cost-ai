/**
 * 主应用 — 三板块架构 (#141)
 * 💬 咨询  /
 * ⛓  管道  /pipeline
 * 🧩 综合  /hub/:tab  (运行时·检索·运维·系统·学习·Agent)
 */

import { useEffect, useState, Component } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { BrowserRouter, Routes, Route, Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { ModuleIcon } from './components/icons/ModuleIcon';
import type { ModuleName } from './components/icons/ModuleIcon';

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

// 核心页面（主导航直接加载）
import { LibraryPage }   from './pages/LibraryPage';
import { AgentChat }     from './pages/AgentChat';
import { PipelinePage }  from './pages/PipelinePage';

// 综合面板外壳（包裹 6 个子标签页）
import { DashHub } from './hubs/DashHub';

// 归档页 — 懒加载，防止 DocsReader 的 ?raw 路径拖垮主包
import { lazy, Suspense } from 'react';
const AgentRuntimeDeepDive = lazy(() => import('./components/common/AgentRuntimeDeepDive'));
const AgentRuntimeFolk     = lazy(() => import('./components/common/AgentRuntimeFolk'));
const DocsReader           = lazy(() => import('./components/common/DocsReader'));

import './App.css';
import './styles/theme.css';

const NAV_ITEMS: { path: string; label: string; icon: ModuleName }[] = [
  { path: '/',         label: '咨询馆员', icon: 'library'  },
  { path: '/pipeline', label: '管道',    icon: 'pipeline' },
  { path: '/hub',      label: '综合面板', icon: 'hub'      },
];

type AuthUser = {
  id: string;
  username: string;
  role: string;
};

type AuthState = {
  token: string;
  user: AuthUser;
};

const AUTH_STORAGE_KEY = 'rag.auth';

function readAuthState(): AuthState | null {
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as AuthState) : null;
  } catch {
    return null;
  }
}

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
  const navigate = useNavigate();
  const [scrolled, setScrolled] = useState(false);
  const [auth, setAuth] = useState<AuthState | null>(() => readAuthState());

  useEffect(() => {
    document.documentElement.dataset.module = getModule(location.pathname);
  }, [location.pathname]);

  /* 监听内容区滚动，滚动后 nav 加阴影层次感 */
  useEffect(() => {
    const main = document.querySelector('.app-main');
    if (!main) return;
    const onScroll = () => setScrolled(main.scrollTop > 4);
    main.addEventListener('scroll', onScroll, { passive: true });
    return () => main.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    const onStorage = () => setAuth(readAuthState());
    window.addEventListener('storage', onStorage);
    window.addEventListener('rag-auth-changed', onStorage);
    return () => {
      window.removeEventListener('storage', onStorage);
      window.removeEventListener('rag-auth-changed', onStorage);
    };
  }, []);

  const isActive = (path: string) =>
    path === '/'
      ? location.pathname === '/'
      : location.pathname.startsWith(path);

  return (
    <header className={`app-nav${scrolled ? ' scrolled' : ''}`}>
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
            <span aria-hidden="true" className="nav-icon">
              <ModuleIcon name={icon} size={14} />
            </span>
            {label}
          </Link>
        ))}
      </nav>

      <div className="nav-actions">
        {auth ? (
          <>
            <span className="nav-user">已登录：{auth.user.username}</span>
            <button
              type="button"
              className="nav-auth-button"
              onClick={() => {
                window.localStorage.removeItem(AUTH_STORAGE_KEY);
                window.dispatchEvent(new Event('rag-auth-changed'));
                navigate('/login');
              }}
            >
              退出
            </button>
          </>
        ) : (
          <Link className="nav-auth-button primary" to="/login">
            登录
          </Link>
        )}
      </div>
    </header>
  );
}

function LoginPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setLoading(true);

    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const payload = await response.json();

      if (!response.ok || !payload.success || !payload.data?.token || !payload.data?.user) {
        throw new Error(payload?.error?.message || '登录失败，请检查用户名和密码');
      }

      const authState: AuthState = {
        token: payload.data.token,
        user: payload.data.user,
      };
      window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(authState));
      window.dispatchEvent(new Event('rag-auth-changed'));
      navigate('/hub/runtime', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div>
          <p className="login-eyebrow">RAG 智库系统</p>
          <h1>管理员登录</h1>
          <p className="login-subtitle">使用管理员账号进入受保护的后台功能。</p>
        </div>

        <label className="login-field">
          <span>用户名</span>
          <input
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="admin"
            required
          />
        </label>

        <label className="login-field">
          <span>密码</span>
          <input
            autoComplete="current-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="请输入密码"
            required
          />
        </label>

        {error && <div className="login-error">{error}</div>}

        <button className="login-submit" type="submit" disabled={loading}>
          {loading ? '登录中…' : '登录'}
        </button>
      </form>
    </section>
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
            <Route path="/login"    element={<LoginPage />} />
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

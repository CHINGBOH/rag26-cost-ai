# KIMI_FRONTEND.md — 前端 UI 全面改造指引

> Copilot（智囊）→ Kimi Code（执行者）  
> **规则**：按 Phase 顺序执行。每个 Phase 完成后填报告，等 Copilot 审查再继续。

---

## ⚠️ Kimi 行为准则（每次执行前必读）

### 🧠 举一反三原则

1. **同类问题一起修**（<10 行改动直接改，记录到报告）
2. **卡住不要死磕**——换角度诊断，记录失败原因
3. **安全第一**——不删除文件，只重命名/归档旧文件
4. **每一个按钮必须有真实后端支撑**——没有 API 的功能不做 UI
5. **CSS 全部走变量**——绝对不允许 inline style 里出现硬编码颜色值
6. **留白 > 密集**——设计原则是"呼吸感"，不是"信息轰炸"

### 🎯 举一反三思考清单（每 Phase 完成后自问）

> 每完成一个 Phase，花 2 分钟回答以下问题，把答案写进报告的「举一反三」小节：

1. **我改的这个组件，还有没有其他组件存在同样的问题？**（例：改了 SearchPanel 的 inline style，UploadPanel 也有同样问题，顺手一起改）
2. **这个 API 调用，前端有没有做好 loading / error / empty 三种状态？**（缺哪个补哪个）
3. **这个页面在浅色 / 深色主题下分别看一眼，有没有颜色混乱？**（用浏览器 DevTools 切换 `data-theme="light"` 和 `data-theme="dark"` 验证）
4. **这个组件在窄屏（width < 768px）下是否正常？**（浏览器 F12 → 响应式模式验证）
5. **我做了这个改动后，有没有更简洁的实现方式？**（3 行能搞定就别写 30 行）

---

## 📐 现状分析 & 改造目标

### 当前问题

```
┌─ 问题 1: 按钮"自嗨"（无后端支持）────────────────────────┐
│  - AgentRuntimeFolk.tsx: 合并/量化/扩容/故障注入按钮全是模拟数据
│  - AgentLoopPage.tsx: 调用 /api/agent/run（不存在的路由）
│  - InfrastructurePanel: Store 数据从未被 API 填充，全显示空状态
│  - ConfigPanel: 保存/重置只改本地 state，没有 API 持久化
│  - SystemMonitorPanel: performance 数据始终为 null
│  - OverviewDashboard: 雷达图/仪表盘全零
└───────────────────────────────────────────────────────────┘

┌─ 问题 2: 两套对话入口互不相通 ─────────────────────────────┐
│  - ChatInterface 走 /api/llm/chat（DeepSeek API 代理）
│  - DashboardPage 走 WebSocket start_recursion（Node XState）
│  - 实际造价问答走 /api/v1/agent（retrieval-service Agent）
│  → 三条路径完全脱节
└───────────────────────────────────────────────────────────┘

┌─ 问题 3: UI 样式混乱 ────────────────────────────────────┐
│  - 50%+ 组件用 inline style 硬编码颜色（白色背景出现在深色页面里）
│  - 导航栏 8 个入口，其中 3 个是教学文档页，占据主导航
│  - 组件密度过高，没有留白
│  - 浅色/深色切换时大量组件不跟随
└───────────────────────────────────────────────────────────┘
```

### 改造后目标

```
┌─ 目标 ────────────────────────────────────────────────────┐
│  1. 只有 4 个顶部页面：问答、检索、数据管道、系统看板        │
│  2. 问答页 = 唯一对话入口，走 /api/v1/agent（真实 RAG Agent）│
│  3. 系统看板 = 真实指标（从后端 /health + /api/v1/agent 拉取）│
│  4. 所有颜色走 CSS 变量，零 inline style 颜色              │
│  5. 大量留白，卡片 + 圆角 + 阴影，呼吸感设计               │
│  6. 深色/浅色主题完美切换                                   │
│  7. 每个按钮背后都有真实 API                                │
└───────────────────────────────────────────────────────────┘
```

---

## 🗺️ 后端 API 合约（前端能用的真实接口）

> **这是前端唯一的数据来源。没列在这里的 API，前端不调用。**

### retrieval-service (`:8002`，通过 Gateway `:8080` 代理)

| 路由 | 方法 | 说明 | 请求体 | 响应关键字段 |
|------|------|------|--------|-------------|
| `/health` | GET | 四库健康状态 | — | `{status, services: {qdrant, elasticsearch, neo4j, redis}, timestamp}` |
| `/api/v1/search` | POST | 混合检索 | `{query, top_k, mode, session_id}` | `{data: {results: [{chunk_id, content, score, metadata}], latency_ms, stats}}` |
| `/api/v1/agent` | POST | **RAG Agent 问答**（核心） | `{query, max_iterations?, session_id?}` | `{session_id, query, answer, chunks[], evaluation: {passed, confidence, completeness, consistency}, iterations, tool_calls[]}` |
| `/api/v1/rerank` | POST | 精排 | `{query, documents[], top_k}` | `{results: [{id, content, score}]}` |
| `/api/v1/evaluate` | POST | 质量评估 | `{query, retrieved_chunks[], generated_answer, history_rounds}` | `{completeness, consistency, confidence, source_diversity, ...}` |
| `/api/v1/decompose` | POST | 查询分解 | `{query}` | `{sub_queries: [{id, query, targetDB, status}]}` |

### python-legacy (`:8000`，通过 Gateway 代理)

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/v1/stats` | GET | 系统统计（文档数、向量数等） |
| `/api/v1/documents/process` | POST | 文档处理/上传入口 |
| `/api/v1/embedding` | POST | 嵌入向量接口 |

### Go Gateway (`:8080` 自身)

| 路由 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | Gateway 自身 + 各后端健康 |
| `/metrics` | GET | Prometheus 指标 |

### WebSocket (`:8081`)

| 路由 | 说明 |
|------|------|
| `/ws?room=dashboard` | 实时事件推送（可用于通知，但不作为主数据源） |

---

## 🏗️ 新页面结构

```
App.tsx
├── Navigation（4 个主入口 + 主题切换）
│   ├── /            → AgentChat（RAG 问答，核心页）
│   ├── /search      → SearchPage（文档检索）
│   ├── /pipeline    → PipelinePage（数据管道）
│   └── /system      → SystemPage（系统看板）
│
├── 归档（不删除，移到 /archive 路由或隐藏入口）
│   ├── /archive/deep-dive      → AgentRuntimeDeepDive
│   ├── /archive/deep-dive-folk → AgentRuntimeFolk
│   └── /archive/docs           → DocsReader
│
└── 删除的"自嗨"组件（重命名加 .bak 后缀，不 import）
    ├── ControlTower.tsx         → ControlTower.tsx.bak
    ├── AgentLoopPage.tsx        → AgentLoopPage.tsx.bak
    ├── SessionList.tsx          → SessionList.tsx.bak
    └── VitalsPanel.tsx          → VitalsPanel.tsx.bak
```

---

## ⏩ Phase 1：清理 + 导航重构

### 目标

1. 精简导航到 4 个核心页面
2. 教学文档页移到 `/archive/*`
3. 备份并移除自嗨组件
4. 修复主题不一致问题

### 1.1 备份自嗨组件

```bash
cd /home/l/rag-dashboard/src/frontend/web/src/components

# 备份，不删除
mv AgentLoopPage.tsx AgentLoopPage.tsx.bak
mv ControlTower.tsx ControlTower.tsx.bak
mv ControlTower.css ControlTower.css.bak
mv SessionList.tsx SessionList.tsx.bak
mv VitalsPanel.tsx VitalsPanel.tsx.bak
```

### 1.2 重写 App.tsx

**完全重写** `src/frontend/web/src/App.tsx`：

```tsx
/**
 * 主应用 — 4 页精简架构
 * 每个页面都有真实后端 API 支撑
 */

import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import { ThemeToggle } from './components/common/ThemeToggle';
import { initTheme } from './config/theme';

// 4 个核心页面
import { AgentChat } from './pages/AgentChat';
import { SearchPage } from './pages/SearchPage';
import { PipelinePage } from './pages/PipelinePage';
import { SystemPage } from './pages/SystemPage';

// 归档页面（教学文档，隐藏入口）
import AgentRuntimeDeepDive from './components/common/AgentRuntimeDeepDive';
import AgentRuntimeFolk from './components/common/AgentRuntimeFolk';
import DocsReader from './components/common/DocsReader';

import './App.css';
import './styles/theme.css';

const NAV_ITEMS = [
  { path: '/', label: '问答', icon: '💬' },
  { path: '/search', label: '检索', icon: '🔍' },
  { path: '/pipeline', label: '数据管道', icon: '📊' },
  { path: '/system', label: '系统', icon: '🖥️' },
] as const;

function Navigation() {
  const location = useLocation();

  return (
    <header className="app-nav">
      <div className="nav-brand">
        <span className="nav-logo">🧠</span>
        <span className="nav-title">RAG Dashboard</span>
      </div>

      <nav className="nav-links">
        {NAV_ITEMS.map(({ path, label, icon }) => (
          <Link
            key={path}
            to={path}
            className={`nav-link ${location.pathname === path ? 'active' : ''}`}
          >
            <span className="nav-icon">{icon}</span>
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
            <Route path="/system" element={<SystemPage />} />
            {/* 归档教学页，不在导航中显示 */}
            <Route path="/archive/deep-dive" element={<AgentRuntimeDeepDive />} />
            <Route path="/archive/deep-dive-folk" element={<AgentRuntimeFolk />} />
            <Route path="/archive/docs" element={<DocsReader />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
```

### 1.3 新 App.css（全局布局 + 导航样式）

**完全重写** `src/frontend/web/src/App.css`：

```css
/**
 * 全局布局 — 简洁留白风格
 */

* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  -webkit-font-smoothing: antialiased;
  transition: background 0.3s ease, color 0.3s ease;
}

/* ── App Shell ─────────────────────────── */

.app-shell {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.app-main {
  flex: 1;
  overflow-y: auto;
}

/* ── Navigation ────────────────────────── */

.app-nav {
  display: flex;
  align-items: center;
  gap: 32px;
  padding: 0 32px;
  height: 56px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-default);
  flex-shrink: 0;
}

.nav-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.nav-logo {
  font-size: 22px;
}

.nav-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.3px;
}

.nav-links {
  display: flex;
  gap: 4px;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 14px;
  color: var(--text-secondary);
  text-decoration: none;
  transition: all 0.2s ease;
}

.nav-link:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.nav-link.active {
  color: var(--color-primary);
  background: var(--color-primary-light);
  font-weight: 500;
}

.nav-icon {
  font-size: 16px;
}

.nav-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
}

/* ── Scrollbar ─────────────────────────── */

::-webkit-scrollbar {
  width: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--border-default);
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--text-muted);
}

/* ── Responsive ────────────────────────── */

@media (max-width: 768px) {
  .app-nav {
    padding: 0 16px;
    gap: 16px;
  }

  .nav-title {
    display: none;
  }

  .nav-link {
    padding: 8px 12px;
    font-size: 13px;
  }
}
```

### 1.4 创建 pages 目录（占位文件）

```bash
mkdir -p /home/l/rag-dashboard/src/frontend/web/src/pages
```

先创建 4 个页面占位（Phase 2-5 逐步实现内容）：

**`src/frontend/web/src/pages/AgentChat.tsx`**：
```tsx
export const AgentChat: React.FC = () => (
  <div style={{ padding: 32 }}>
    <h2>💬 RAG 问答</h2>
    <p style={{ color: 'var(--text-muted)' }}>Phase 2 实现</p>
  </div>
);
```

**`src/frontend/web/src/pages/SearchPage.tsx`**：
```tsx
export const SearchPage: React.FC = () => (
  <div style={{ padding: 32 }}>
    <h2>🔍 文档检索</h2>
    <p style={{ color: 'var(--text-muted)' }}>Phase 3 实现</p>
  </div>
);
```

**`src/frontend/web/src/pages/PipelinePage.tsx`**：
```tsx
export const PipelinePage: React.FC = () => (
  <div style={{ padding: 32 }}>
    <h2>📊 数据管道</h2>
    <p style={{ color: 'var(--text-muted)' }}>Phase 4 实现</p>
  </div>
);
```

**`src/frontend/web/src/pages/SystemPage.tsx`**：
```tsx
export const SystemPage: React.FC = () => (
  <div style={{ padding: 32 }}>
    <h2>🖥️ 系统看板</h2>
    <p style={{ color: 'var(--text-muted)' }}>Phase 5 实现</p>
  </div>
);
```

### 1.5 验证

```bash
cd /home/l/rag-dashboard/src/frontend/web
npm run dev 2>&1 | head -20

# 浏览器打开 http://localhost:3000
# 验证：
# - 顶部导航只有 4 项：问答、检索、数据管道、系统
# - 主题切换按钮存在且可用
# - 深色/浅色切换正常
# - 无报错
```

---

### 📋 Phase 1 报告

- [ ] 自嗨组件已备份（.bak）
- [ ] App.tsx 已重写
- [ ] App.css 已重写
- [ ] 4 个页面占位已创建
- [ ] `npm run dev` 无编译错误
- [ ] 导航 4 项 + 主题切换正常

#### 举一反三

```
（回答 5 个自检问题）
```

---

## Phase 2：AgentChat 页面（核心）

> ⚠️ 等 Phase 1 审查通过后再执行

### 目标

实现 **唯一的对话入口**，走 `/api/v1/agent`（retrieval-service 真实 RAG Agent）。

### 设计原则

```
┌───────────────────────────────────────────────────────────┐
│  AgentChat 页面布局                                        │
│                                                           │
│  ┌─ 消息区域（占 85% 高度）────────────────────────────┐  │
│  │                                                     │  │
│  │  大量留白                                            │  │
│  │                                                     │  │
│  │  👤 用户消息                                         │  │
│  │     ┌────────────────────────────────────┐          │  │
│  │     │ 某工程人工费500万，按2025版费率计算    │          │  │
│  │     │ 企业管理费是多少？                    │          │  │
│  │     └────────────────────────────────────┘          │  │
│  │                                                     │  │
│  │  🤖 助手消息                                         │  │
│  │     ┌────────────────────────────────────┐          │  │
│  │     │ 根据2025版费率，企业管理费 = ...      │          │  │
│  │     │ 📎 来源: chunk_xxx (confidence 0.92) │          │  │
│  │     └────────────────────────────────────┘          │  │
│  │                                                     │  │
│  │  [可折叠] 检索过程                                   │  │
│  │     工具调用: vector_search → 6 chunks               │  │
│  │     评估: passed=true, confidence=0.92               │  │
│  │     迭代: 1/3                                       │  │
│  │                                                     │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                           │
│  ┌─ 输入区 ───────────────────────────────────────────┐  │
│  │  [输入框]                                [发送按钮] │  │
│  └─────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────┘
```

### 2.1 创建 agentApi.ts（API 层）

文件：`src/frontend/web/src/services/agentApi.ts`

```typescript
/**
 * RAG Agent API — 对接 retrieval-service /api/v1/agent
 * 唯一的问答 API 入口
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export interface AgentChunk {
  chunk_id: string;
  doc_id: string;
  content: string;
  score: number;
  source?: string;
  metadata?: Record<string, any>;
}

export interface AgentEvaluation {
  passed: boolean;
  confidence: number;
  completeness?: number;
  consistency?: number;
}

export interface AgentToolCall {
  tool: string;
  args: Record<string, any>;
  result_summary?: string;
}

export interface AgentResponse {
  session_id: string;
  query: string;
  answer: string;
  chunks: AgentChunk[];
  evaluation: AgentEvaluation;
  iterations: number;
  tool_calls?: AgentToolCall[];
  error?: string;
}

export interface HealthResponse {
  status: string;
  services: Record<string, string>;
  timestamp: string;
}

/**
 * 发送问答请求到 RAG Agent
 */
export async function askAgent(
  query: string,
  options?: { maxIterations?: number; sessionId?: string }
): Promise<AgentResponse> {
  const response = await fetch(`${API_BASE}/api/v1/agent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      max_iterations: options?.maxIterations ?? 3,
      session_id: options?.sessionId,
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Agent API 错误: ${response.status} - ${text}`);
  }

  return response.json();
}

/**
 * 检查后端健康状态
 */
export async function checkHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) throw new Error('Health check failed');
  return response.json();
}
```

### 2.2 创建 useAgent hook

文件：`src/frontend/web/src/hooks/useAgent.ts`

```typescript
/**
 * Agent 交互 Hook
 * 管理对话状态、请求/响应、历史记录
 */

import { useState, useCallback, useRef } from 'react';
import { askAgent, AgentResponse, AgentChunk, AgentEvaluation } from '../services/agentApi';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  // 助手消息附加信息
  chunks?: AgentChunk[];
  evaluation?: AgentEvaluation;
  iterations?: number;
  toolCalls?: Array<{ tool: string; args: Record<string, any> }>;
  latencyMs?: number;
  error?: string;
}

export function useAgent() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const abortRef = useRef(false);

  const sendMessage = useCallback(async (query: string) => {
    if (!query.trim() || isLoading) return;

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: query.trim(),
      timestamp: Date.now(),
    };

    setMessages(prev => [...prev, userMsg]);
    setIsLoading(true);
    abortRef.current = false;

    const startTime = Date.now();

    try {
      const response: AgentResponse = await askAgent(query.trim());

      if (abortRef.current) return;

      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: response.answer,
        timestamp: Date.now(),
        chunks: response.chunks,
        evaluation: response.evaluation,
        iterations: response.iterations,
        toolCalls: response.tool_calls,
        latencyMs: Date.now() - startTime,
      };

      setMessages(prev => [...prev, assistantMsg]);
    } catch (error) {
      const errorMsg: ChatMessage = {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: '',
        timestamp: Date.now(),
        error: error instanceof Error ? error.message : '请求失败',
        latencyMs: Date.now() - startTime,
      };
      setMessages(prev => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  }, [isLoading]);

  const clearMessages = useCallback(() => {
    abortRef.current = true;
    setMessages([]);
    setIsLoading(false);
  }, []);

  return { messages, isLoading, sendMessage, clearMessages };
}
```

### 2.3 实现 AgentChat 页面

文件：`src/frontend/web/src/pages/AgentChat.tsx`（替换占位）

```tsx
/**
 * RAG 问答页 — 唯一对话入口
 * 走 /api/v1/agent（retrieval-service 真实 RAG Agent）
 */

import { useState, useRef, useEffect } from 'react';
import { useAgent, ChatMessage } from '../hooks/useAgent';
import './AgentChat.css';

export const AgentChat: React.FC = () => {
  const { messages, isLoading, sendMessage, clearMessages } = useAgent();
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // 自动滚动
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = () => {
    if (!input.trim() || isLoading) return;
    sendMessage(input);
    setInput('');
    inputRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="agent-chat">
      {/* 消息区域 */}
      <div className="chat-messages">
        {messages.length === 0 ? (
          <WelcomeScreen onQuickAsk={sendMessage} />
        ) : (
          messages.map(msg => (
            <MessageBubble key={msg.id} message={msg} />
          ))
        )}

        {isLoading && <ThinkingIndicator />}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区 */}
      <div className="chat-input-area">
        <div className="input-wrapper">
          <textarea
            ref={inputRef}
            className="chat-textarea"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入造价相关问题..."
            rows={1}
            disabled={isLoading}
          />
          <button
            className="send-btn"
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
          >
            {isLoading ? '⏳' : '➤'}
          </button>
        </div>
        <div className="input-hints">
          <span className="hint-text">Enter 发送 · Shift+Enter 换行</span>
          {messages.length > 0 && (
            <button className="clear-btn" onClick={clearMessages}>清空对话</button>
          )}
        </div>
      </div>
    </div>
  );
};

/* ── 欢迎页 ─────────────────────────────────────────── */

const QUICK_QUESTIONS = [
  '2025版费率标准中，企业管理费的计算方法是什么？',
  '某工程人工费500万，按2025版费率计算企业管理费是多少？',
  '2026年1月普通硅酸盐水泥P.O 42.5的含税价格是多少？',
  '一般计税与简易计税的适用条件分别是什么？',
];

const WelcomeScreen: React.FC<{ onQuickAsk: (q: string) => void }> = ({ onQuickAsk }) => (
  <div className="welcome-screen">
    <div className="welcome-content">
      <h1 className="welcome-title">🧠 造价知识问答</h1>
      <p className="welcome-desc">基于深圳市建设工程定额、费率标准、信息价的智能问答系统</p>
      <div className="quick-questions">
        {QUICK_QUESTIONS.map((q, i) => (
          <button key={i} className="quick-question-btn" onClick={() => onQuickAsk(q)}>
            {q}
          </button>
        ))}
      </div>
    </div>
  </div>
);

/* ── 消息气泡 ───────────────────────────────────────── */

const MessageBubble: React.FC<{ message: ChatMessage }> = ({ message }) => {
  const [showDetail, setShowDetail] = useState(false);

  if (message.error) {
    return (
      <div className="message-row assistant">
        <div className="message-bubble error">
          <p>❌ {message.error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`message-row ${message.role}`}>
      <div className={`message-bubble ${message.role}`}>
        {/* 消息内容 */}
        <div className="message-content">
          {message.content}
        </div>

        {/* 助手消息附加信息 */}
        {message.role === 'assistant' && message.evaluation && (
          <div className="message-meta">
            <span className="meta-tag confidence">
              置信度 {(message.evaluation.confidence * 100).toFixed(0)}%
            </span>
            <span className="meta-tag iterations">
              迭代 {message.iterations ?? 1} 轮
            </span>
            <span className="meta-tag chunks">
              引用 {message.chunks?.length ?? 0} 篇
            </span>
            {message.latencyMs && (
              <span className="meta-tag latency">
                {(message.latencyMs / 1000).toFixed(1)}s
              </span>
            )}
            <button
              className="detail-toggle"
              onClick={() => setShowDetail(!showDetail)}
            >
              {showDetail ? '收起详情 ▲' : '展开详情 ▼'}
            </button>
          </div>
        )}

        {/* 可折叠的检索详情 */}
        {showDetail && message.role === 'assistant' && (
          <div className="message-detail">
            {/* 工具调用 */}
            {message.toolCalls && message.toolCalls.length > 0 && (
              <div className="detail-section">
                <h4>🔧 工具调用</h4>
                {message.toolCalls.map((tc, i) => (
                  <div key={i} className="tool-call-item">
                    <code>{tc.tool}</code>
                    <span className="tool-args">{JSON.stringify(tc.args).slice(0, 100)}</span>
                  </div>
                ))}
              </div>
            )}

            {/* 引用文档 */}
            {message.chunks && message.chunks.length > 0 && (
              <div className="detail-section">
                <h4>📎 引用文档</h4>
                {message.chunks.slice(0, 5).map((chunk, i) => (
                  <div key={i} className="chunk-item">
                    <div className="chunk-score">
                      {(chunk.score * 100).toFixed(1)}%
                    </div>
                    <div className="chunk-content">
                      {chunk.content.slice(0, 200)}
                      {chunk.content.length > 200 && '...'}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

/* ── 思考动画 ───────────────────────────────────────── */

const ThinkingIndicator: React.FC = () => (
  <div className="message-row assistant">
    <div className="message-bubble thinking">
      <div className="thinking-dots">
        <span /><span /><span />
      </div>
      <span className="thinking-text">正在检索和分析...</span>
    </div>
  </div>
);
```

### 2.4 AgentChat.css

文件：`src/frontend/web/src/pages/AgentChat.css`

```css
/**
 * RAG 问答页样式 — 极简留白风格
 * 全部使用 CSS 变量，深色/浅色完美切换
 */

.agent-chat {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 56px);  /* 减去导航高度 */
  max-width: 800px;
  margin: 0 auto;
  padding: 0 24px;
}

/* ── 消息区域 ─────────────────────── */

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 32px 0;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.message-row {
  display: flex;
}

.message-row.user {
  justify-content: flex-end;
}

.message-row.assistant {
  justify-content: flex-start;
}

.message-bubble {
  max-width: 85%;
  padding: 14px 18px;
  border-radius: 16px;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}

.message-bubble.user {
  background: var(--color-primary);
  color: #fff;
  border-bottom-right-radius: 4px;
}

.message-bubble.assistant {
  background: var(--bg-elevated);
  color: var(--text-primary);
  border: 1px solid var(--border-default);
  border-bottom-left-radius: 4px;
}

.message-bubble.error {
  background: rgba(239, 68, 68, 0.1);
  color: var(--color-error);
  border: 1px solid rgba(239, 68, 68, 0.2);
}

/* ── 消息元信息 ───────────────────── */

.message-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border-default);
  align-items: center;
}

.meta-tag {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 10px;
  background: var(--bg-primary);
  color: var(--text-muted);
  border: 1px solid var(--border-default);
}

.meta-tag.confidence {
  color: var(--color-success);
  border-color: rgba(34, 197, 94, 0.3);
}

.detail-toggle {
  font-size: 11px;
  padding: 3px 8px;
  border: none;
  background: none;
  color: var(--color-primary);
  cursor: pointer;
  margin-left: auto;
}

.detail-toggle:hover {
  text-decoration: underline;
}

/* ── 检索详情（折叠） ─────────────── */

.message-detail {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--border-default);
}

.detail-section {
  margin-bottom: 16px;
}

.detail-section h4 {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 8px;
  font-weight: 500;
}

.tool-call-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--bg-primary);
  border-radius: 6px;
  margin-bottom: 4px;
  font-size: 12px;
}

.tool-call-item code {
  color: var(--color-primary);
  font-weight: 500;
}

.tool-args {
  color: var(--text-muted);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chunk-item {
  display: flex;
  gap: 10px;
  padding: 8px;
  background: var(--bg-primary);
  border-radius: 8px;
  margin-bottom: 6px;
  font-size: 12px;
  line-height: 1.5;
}

.chunk-score {
  flex-shrink: 0;
  padding: 2px 8px;
  border-radius: 8px;
  background: rgba(59, 130, 246, 0.1);
  color: var(--color-primary);
  font-size: 11px;
  font-weight: 500;
  height: fit-content;
}

.chunk-content {
  color: var(--text-secondary);
}

/* ── 欢迎页 ───────────────────────── */

.welcome-screen {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.welcome-content {
  text-align: center;
  max-width: 560px;
}

.welcome-title {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 12px;
}

.welcome-desc {
  font-size: 15px;
  color: var(--text-muted);
  margin-bottom: 36px;
  line-height: 1.6;
}

.quick-questions {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.quick-question-btn {
  padding: 12px 18px;
  border: 1px solid var(--border-default);
  border-radius: 12px;
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s ease;
  line-height: 1.5;
}

.quick-question-btn:hover {
  border-color: var(--color-primary);
  color: var(--text-primary);
  background: var(--bg-hover);
}

/* ── 输入区 ───────────────────────── */

.chat-input-area {
  padding: 16px 0 24px;
  flex-shrink: 0;
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 10px 14px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 16px;
  transition: border-color 0.2s ease;
}

.input-wrapper:focus-within {
  border-color: var(--color-primary);
}

.chat-textarea {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font-size: 14px;
  line-height: 1.5;
  resize: none;
  max-height: 150px;
  font-family: inherit;
}

.chat-textarea::placeholder {
  color: var(--text-muted);
}

.send-btn {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  border: none;
  background: var(--color-primary);
  color: #fff;
  font-size: 18px;
  cursor: pointer;
  flex-shrink: 0;
  transition: opacity 0.2s ease;
}

.send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.send-btn:not(:disabled):hover {
  opacity: 0.85;
}

.input-hints {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
  padding: 0 4px;
}

.hint-text {
  font-size: 11px;
  color: var(--text-muted);
}

.clear-btn {
  font-size: 11px;
  padding: 4px 10px;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.clear-btn:hover {
  border-color: var(--color-error);
  color: var(--color-error);
}

/* ── 思考动画 ─────────────────────── */

.message-bubble.thinking {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
}

.thinking-dots {
  display: flex;
  gap: 4px;
}

.thinking-dots span {
  width: 6px;
  height: 6px;
  background: var(--color-primary);
  border-radius: 50%;
  animation: thinking-bounce 1.4s infinite ease-in-out both;
}

.thinking-dots span:nth-child(1) { animation-delay: -0.32s; }
.thinking-dots span:nth-child(2) { animation-delay: -0.16s; }

@keyframes thinking-bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

.thinking-text {
  font-size: 13px;
  color: var(--text-muted);
}

/* ── Responsive ───────────────────── */

@media (max-width: 768px) {
  .agent-chat {
    padding: 0 12px;
  }

  .message-bubble {
    max-width: 92%;
    padding: 12px 14px;
  }

  .welcome-title {
    font-size: 24px;
  }
}
```

### 2.5 验证

```bash
cd /home/l/rag-dashboard/src/frontend/web
npm run dev

# 确保 retrieval-service 在运行
curl -s http://localhost:8002/health | python3 -m json.tool

# 浏览器测试：
# 1. 打开 http://localhost:3000 → 看到欢迎页 + 4 个快速问题
# 2. 点击快速问题 → 发送请求到 /api/v1/agent → 收到回答
# 3. 回答下方有置信度、迭代轮数、引用数等元信息
# 4. 点击"展开详情"→ 看到工具调用和引用文档
# 5. 切换深色/浅色主题 → 所有颜色正确
# 6. 浏览器 F12 → 响应式模式 375px → 布局不崩
```

---

### 📋 Phase 2 报告

- [ ] agentApi.ts 已创建
- [ ] useAgent.ts hook 已创建
- [ ] AgentChat.tsx 已实现
- [ ] AgentChat.css 已实现（零 inline style 颜色）
- [ ] 问答请求走 `/api/v1/agent` 成功
- [ ] 消息气泡显示正常（用户/助手/错误）
- [ ] 检索详情折叠/展开正常
- [ ] 深色/浅色主题切换正常
- [ ] 窄屏布局正常

#### 测试对话

```
（粘贴 2 轮实际对话截图或文本输出）
```

#### 举一反三

```
（5 个自检问题的回答）
```

---

## Phase 3：SearchPage（文档检索）

> ⚠️ 等 Phase 2 审查通过后再执行

### 目标

实现文档检索页，走 `/api/v1/search`，支持模式切换（向量/关键词/图/混合）。

### 3.1 实现 SearchPage.tsx

文件：`src/frontend/web/src/pages/SearchPage.tsx`（替换占位）

```tsx
/**
 * 文档检索页
 * 走 /api/v1/search — 支持四种检索模式
 */

import { useState } from 'react';
import './SearchPage.css';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

type SearchMode = 'hybrid' | 'vector' | 'keyword' | 'graph';

interface SearchResult {
  chunk_id: string;
  doc_id: string;
  content: string;
  score: number;
  metadata: Record<string, any>;
}

const MODES: { value: SearchMode; label: string; icon: string }[] = [
  { value: 'hybrid', label: '混合', icon: '🔄' },
  { value: 'vector', label: '向量', icon: '📐' },
  { value: 'keyword', label: '关键词', icon: '🔤' },
  { value: 'graph', label: '图谱', icon: '🕸️' },
];

export const SearchPage: React.FC = () => {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<SearchMode>('hybrid');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [latency, setLatency] = useState(0);
  const [error, setError] = useState('');

  const handleSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError('');
    const start = Date.now();

    try {
      const res = await fetch(`${API_BASE}/api/v1/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query.trim(), top_k: 10, mode }),
      });

      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);

      const data = await res.json();
      const items = data.data?.results || data.results || [];
      setResults(items);
      setLatency(Date.now() - start);
    } catch (e: any) {
      setError(e.message || '检索失败');
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="search-page">
      <div className="search-header">
        <h1>文档检索</h1>
        <p className="search-subtitle">在四库中搜索文档片段</p>
      </div>

      {/* 搜索栏 */}
      <div className="search-bar">
        <input
          className="search-input"
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
          placeholder="输入检索关键词..."
        />
        <div className="mode-selector">
          {MODES.map(m => (
            <button
              key={m.value}
              className={`mode-btn ${mode === m.value ? 'active' : ''}`}
              onClick={() => setMode(m.value)}
            >
              {m.icon} {m.label}
            </button>
          ))}
        </div>
        <button
          className="search-btn"
          onClick={handleSearch}
          disabled={loading || !query.trim()}
        >
          {loading ? '检索中...' : '🔍 检索'}
        </button>
      </div>

      {/* 统计 */}
      {latency > 0 && !loading && (
        <div className="search-stats">
          找到 <strong>{results.length}</strong> 个结果，耗时 <strong>{latency}ms</strong>
        </div>
      )}

      {error && <div className="search-error">❌ {error}</div>}

      {/* 结果列表 */}
      <div className="results-list">
        {results.map((r, i) => (
          <div key={r.chunk_id || i} className="result-card">
            <div className="result-top">
              <span className="result-rank">#{i + 1}</span>
              <span className="result-score">{(r.score * 100).toFixed(1)}%</span>
            </div>
            <div className="result-body">{r.content}</div>
            <div className="result-footer">
              <span>📄 {r.doc_id}</span>
              {r.metadata?.page_number && <span>p.{r.metadata.page_number}</span>}
            </div>
          </div>
        ))}
      </div>

      {results.length === 0 && !loading && query && !error && (
        <div className="empty-state">暂无匹配结果</div>
      )}
    </div>
  );
};
```

### 3.2 SearchPage.css

文件：`src/frontend/web/src/pages/SearchPage.css`

```css
.search-page {
  max-width: 800px;
  margin: 0 auto;
  padding: 40px 24px;
}

.search-header {
  margin-bottom: 32px;
}

.search-header h1 {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.search-subtitle {
  font-size: 14px;
  color: var(--text-muted);
}

/* ── 搜索栏 ─────────────────────── */

.search-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-bottom: 24px;
}

.search-input {
  flex: 1;
  min-width: 200px;
  padding: 12px 16px;
  border: 1px solid var(--border-default);
  border-radius: 10px;
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
}

.search-input:focus {
  border-color: var(--color-primary);
}

.mode-selector {
  display: flex;
  gap: 4px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 4px;
}

.mode-btn {
  padding: 6px 12px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.mode-btn:hover {
  color: var(--text-primary);
}

.mode-btn.active {
  background: var(--color-primary);
  color: #fff;
}

.search-btn {
  padding: 10px 20px;
  border: none;
  border-radius: 10px;
  background: var(--color-primary);
  color: #fff;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.2s;
}

.search-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ── 统计 & 错误 ────────────────── */

.search-stats {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 20px;
}

.search-error {
  padding: 12px 16px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 10px;
  color: var(--color-error);
  font-size: 13px;
  margin-bottom: 20px;
}

/* ── 结果卡片 ───────────────────── */

.results-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.result-card {
  padding: 16px 18px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  transition: border-color 0.2s;
}

.result-card:hover {
  border-color: var(--border-highlight);
}

.result-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.result-rank {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
}

.result-score {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 8px;
  background: rgba(59, 130, 246, 0.1);
  color: var(--color-primary);
  font-weight: 500;
}

.result-body {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
  margin-bottom: 10px;
}

.result-footer {
  display: flex;
  gap: 16px;
  font-size: 11px;
  color: var(--text-muted);
}

.empty-state {
  text-align: center;
  padding: 60px 0;
  color: var(--text-muted);
  font-size: 14px;
}
```

### 3.3 验证

```bash
# 浏览器打开 http://localhost:3000/search
# 1. 输入 "混凝土" → 点击检索 → 看到结果卡片
# 2. 切换模式（向量/关键词/图/混合）→ 重新检索 → 结果变化
# 3. 深色/浅色切换 → 所有颜色正确
# 4. 窄屏模式 → 搜索栏换行，结果卡片自适应
```

---

### 📋 Phase 3 报告

- [ ] SearchPage 替换占位实现
- [ ] CSS 零 inline style 颜色
- [ ] 四种检索模式切换正常
- [ ] 深色/浅色正常
- [ ] 窄屏布局正常

#### 举一反三

```
```

---

## Phase 4：PipelinePage（数据管道）

> ⚠️ 等 Phase 3 审查通过后再执行

### 目标

精简的数据管道页，核心功能：文档上传 + 四库状态。只做有 API 支撑的功能。

### 4.1 实现 PipelinePage.tsx

文件：`src/frontend/web/src/pages/PipelinePage.tsx`（替换占位）

```tsx
/**
 * 数据管道页
 * 文档上传 + 四库状态
 */

import { useState, useRef, useEffect } from 'react';
import { checkHealth, HealthResponse } from '../services/agentApi';
import './PipelinePage.css';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export const PipelinePage: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // 定时刷新健康状态
  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const h = await checkHealth();
        setHealth(h);
      } catch { /* ignore */ }
    };
    fetchHealth();
    const timer = setInterval(fetchHealth, 15000);
    return () => clearInterval(timer);
  }, []);

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setUploadResult(null);
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('title', file.name);
      const res = await fetch(`${API_BASE}/api/v1/documents/process`, {
        method: 'POST',
        body: form,
      });
      if (!res.ok) throw new Error(`上传失败: ${res.status}`);
      const data = await res.json();
      setUploadResult({ ok: true, msg: `文档 ${data.doc_id || file.name} 已提交处理` });
      setFile(null);
      if (fileRef.current) fileRef.current.value = '';
    } catch (e: any) {
      setUploadResult({ ok: false, msg: e.message });
    } finally {
      setUploading(false);
    }
  };

  const statusIcon = (s: string) =>
    s === 'healthy' || s === 'ok' ? '🟢' :
    s === 'degraded' ? '🟡' : '🔴';

  return (
    <div className="pipeline-page">
      <h1>数据管道</h1>
      <p className="page-subtitle">文档上传与四库运行状态</p>

      <div className="pipeline-grid">
        {/* 四库状态 */}
        <section className="pipeline-card">
          <h2>四库状态</h2>
          {health ? (
            <div className="health-grid">
              <div className="health-item">
                <span className="health-icon">{statusIcon(health.services?.qdrant || health.services?.vector || 'unknown')}</span>
                <span className="health-label">Qdrant</span>
                <span className="health-status">{health.services?.qdrant || health.services?.vector || '—'}</span>
              </div>
              <div className="health-item">
                <span className="health-icon">{statusIcon(health.services?.elasticsearch || health.services?.keyword || 'unknown')}</span>
                <span className="health-label">Elasticsearch</span>
                <span className="health-status">{health.services?.elasticsearch || health.services?.keyword || '—'}</span>
              </div>
              <div className="health-item">
                <span className="health-icon">{statusIcon(health.services?.neo4j || health.services?.graph || 'unknown')}</span>
                <span className="health-label">Neo4j</span>
                <span className="health-status">{health.services?.neo4j || health.services?.graph || '—'}</span>
              </div>
              <div className="health-item">
                <span className="health-icon">{statusIcon(health.services?.redis || health.services?.cache || 'unknown')}</span>
                <span className="health-label">Redis</span>
                <span className="health-status">{health.services?.redis || health.services?.cache || '—'}</span>
              </div>
            </div>
          ) : (
            <p className="loading-text">加载中...</p>
          )}
          {health && (
            <div className="health-footer">
              整体: <strong>{health.status}</strong>
              <span className="health-time">更新于 {new Date(health.timestamp).toLocaleTimeString()}</span>
            </div>
          )}
        </section>

        {/* 文档上传 */}
        <section className="pipeline-card">
          <h2>文档上传</h2>
          <div
            className="upload-zone"
            onClick={() => fileRef.current?.click()}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.docx"
              onChange={e => { setFile(e.target.files?.[0] || null); setUploadResult(null); }}
              hidden
            />
            {file ? (
              <div className="file-info">
                <span className="file-icon">📄</span>
                <span>{file.name}</span>
                <span className="file-size">({(file.size / 1024).toFixed(0)} KB)</span>
              </div>
            ) : (
              <div className="upload-hint">
                <span>📁</span>
                <span>点击选择文件</span>
                <span className="hint-formats">PDF / PNG / JPG / DOCX</span>
              </div>
            )}
          </div>

          {file && (
            <button
              className="upload-btn"
              onClick={handleUpload}
              disabled={uploading}
            >
              {uploading ? '处理中...' : '⬆️ 上传并处理'}
            </button>
          )}

          {uploadResult && (
            <div className={`upload-result ${uploadResult.ok ? 'success' : 'error'}`}>
              {uploadResult.ok ? '✅' : '❌'} {uploadResult.msg}
            </div>
          )}
        </section>
      </div>
    </div>
  );
};
```

### 4.2 PipelinePage.css

文件：`src/frontend/web/src/pages/PipelinePage.css`

```css
.pipeline-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 40px 24px;
}

.pipeline-page h1 {
  font-size: 24px;
  font-weight: 700;
  margin-bottom: 6px;
}

.page-subtitle {
  color: var(--text-muted);
  font-size: 14px;
  margin-bottom: 32px;
}

.pipeline-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

@media (max-width: 768px) {
  .pipeline-grid { grid-template-columns: 1fr; }
}

.pipeline-card {
  padding: 24px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 14px;
}

.pipeline-card h2 {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 18px;
  color: var(--text-primary);
}

/* ── 四库状态 ─────────────────────── */

.health-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.health-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: var(--bg-primary);
  border-radius: 10px;
  border: 1px solid var(--border-default);
}

.health-icon { font-size: 14px; }

.health-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.health-status {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-muted);
}

.health-footer {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--border-default);
  font-size: 12px;
  color: var(--text-muted);
  display: flex;
  justify-content: space-between;
}

.loading-text {
  color: var(--text-muted);
  font-size: 13px;
}

/* ── 文档上传 ─────────────────────── */

.upload-zone {
  border: 2px dashed var(--border-default);
  border-radius: 12px;
  padding: 32px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s;
}

.upload-zone:hover {
  border-color: var(--color-primary);
}

.upload-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  color: var(--text-muted);
  font-size: 14px;
}

.hint-formats {
  font-size: 11px;
  color: var(--text-muted);
}

.file-info {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: center;
  font-size: 14px;
  color: var(--text-primary);
}

.file-icon { font-size: 20px; }

.file-size {
  color: var(--text-muted);
  font-size: 12px;
}

.upload-btn {
  width: 100%;
  margin-top: 14px;
  padding: 12px;
  border: none;
  border-radius: 10px;
  background: var(--color-primary);
  color: #fff;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.2s;
}

.upload-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.upload-result {
  margin-top: 12px;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 13px;
}

.upload-result.success {
  background: rgba(34, 197, 94, 0.08);
  color: var(--color-success);
  border: 1px solid rgba(34, 197, 94, 0.2);
}

.upload-result.error {
  background: rgba(239, 68, 68, 0.08);
  color: var(--color-error);
  border: 1px solid rgba(239, 68, 68, 0.2);
}
```

### 📋 Phase 4 报告

- [ ] PipelinePage 实现
- [ ] 四库健康状态从真实 API 拉取
- [ ] 文档上传走 `/api/v1/documents/process`
- [ ] 15 秒自动刷新
- [ ] 深色/浅色正常

#### 举一反三

```
```

---

## Phase 5：SystemPage（系统看板）

> ⚠️ 等 Phase 4 审查通过后再执行

### 目标

系统看板展示**真实的 RAG Agent 运行指标**，从后端 API 拉取。这是运维核心页面。

### 设计

```
┌─ 系统看板布局 ────────────────────────────────────────────┐
│                                                           │
│  ┌─ 四库连通性 ────┐  ┌─ Agent 概览 ──────────────────┐  │
│  │ Qdrant    🟢    │  │ 最近 N 次查询通过率: 94%      │  │
│  │ ES        🟢    │  │ 平均置信度: 0.87              │  │
│  │ Neo4j     🟢    │  │ 平均迭代: 1.2 轮             │  │
│  │ Redis     🟢    │  │ 平均耗时: 8.5s               │  │
│  └─────────────────┘  └───────────────────────────────┘  │
│                                                           │
│  ┌─ 实时测试 ─────────────────────────────────────────┐  │
│  │ [输入框: 输入测试查询]            [发送] [清除历史] │  │
│  │                                                     │  │
│  │ 测试记录:                                           │  │
│  │ #1 "企业管理费..." → ✅ passed conf=0.92 8.2s     │  │
│  │ #2 "混凝土工程..."  → ✅ passed conf=0.88 7.1s     │  │
│  │ #3 "电线电缆价格..." → ❌ failed conf=0.45 12.3s   │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                           │
│  ┌─ Agent 参数调节 ───────────────────────────────────┐  │
│  │ max_iterations: [3]  (slider 1-5)                   │  │
│  │ 说明: 调整后在上方测试区实时验证效果                  │  │
│  └─────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────┘
```

### 5.1 实现 SystemPage.tsx

文件：`src/frontend/web/src/pages/SystemPage.tsx`（替换占位）

```tsx
/**
 * 系统看板 — 真实 RAG Agent 运行指标 + 实时测试
 */

import { useState, useEffect, useCallback } from 'react';
import { checkHealth, askAgent, HealthResponse, AgentResponse } from '../services/agentApi';
import './SystemPage.css';

interface TestRecord {
  id: number;
  query: string;
  passed: boolean;
  confidence: number;
  iterations: number;
  chunks: number;
  latencyMs: number;
  timestamp: number;
}

export const SystemPage: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [testQuery, setTestQuery] = useState('');
  const [testRecords, setTestRecords] = useState<TestRecord[]>([]);
  const [testing, setTesting] = useState(false);
  const [maxIterations, setMaxIterations] = useState(3);

  // 健康检查
  useEffect(() => {
    const fetch = async () => {
      try { setHealth(await checkHealth()); } catch {}
    };
    fetch();
    const t = setInterval(fetch, 15000);
    return () => clearInterval(t);
  }, []);

  // 统计指标
  const stats = (() => {
    if (testRecords.length === 0) return null;
    const passed = testRecords.filter(r => r.passed).length;
    const avgConf = testRecords.reduce((s, r) => s + r.confidence, 0) / testRecords.length;
    const avgIter = testRecords.reduce((s, r) => s + r.iterations, 0) / testRecords.length;
    const avgLatency = testRecords.reduce((s, r) => s + r.latencyMs, 0) / testRecords.length;
    return {
      passRate: ((passed / testRecords.length) * 100).toFixed(0),
      avgConfidence: avgConf.toFixed(2),
      avgIterations: avgIter.toFixed(1),
      avgLatency: (avgLatency / 1000).toFixed(1),
      total: testRecords.length,
    };
  })();

  const runTest = useCallback(async () => {
    if (!testQuery.trim() || testing) return;
    setTesting(true);
    const start = Date.now();

    try {
      const res = await askAgent(testQuery.trim(), { maxIterations });
      setTestRecords(prev => [{
        id: Date.now(),
        query: testQuery.trim(),
        passed: res.evaluation?.passed ?? false,
        confidence: res.evaluation?.confidence ?? 0,
        iterations: res.iterations ?? 1,
        chunks: res.chunks?.length ?? 0,
        latencyMs: Date.now() - start,
        timestamp: Date.now(),
      }, ...prev]);
    } catch (e: any) {
      setTestRecords(prev => [{
        id: Date.now(),
        query: testQuery.trim(),
        passed: false,
        confidence: 0,
        iterations: 0,
        chunks: 0,
        latencyMs: Date.now() - start,
        timestamp: Date.now(),
      }, ...prev]);
    } finally {
      setTesting(false);
      setTestQuery('');
    }
  }, [testQuery, testing, maxIterations]);

  const statusIcon = (s: string) =>
    s === 'healthy' || s === 'ok' ? '🟢' : s === 'degraded' ? '🟡' : '🔴';

  return (
    <div className="system-page">
      <h1>系统看板</h1>
      <p className="page-subtitle">RAG Agent 运行状态与实时测试</p>

      <div className="system-grid">
        {/* 四库状态 */}
        <div className="sys-card">
          <h2>四库连通性</h2>
          {health ? (
            <div className="sys-health-list">
              {Object.entries(health.services || {}).map(([k, v]) => (
                <div key={k} className="sys-health-row">
                  <span>{statusIcon(v)}</span>
                  <span className="sys-health-name">{k}</span>
                  <span className="sys-health-val">{v}</span>
                </div>
              ))}
              <div className="sys-health-overall">
                整体: <strong>{health.status}</strong>
              </div>
            </div>
          ) : (
            <p className="loading-text">连接中...</p>
          )}
        </div>

        {/* Agent 概览 */}
        <div className="sys-card">
          <h2>Agent 概览</h2>
          {stats ? (
            <div className="sys-stats-grid">
              <div className="stat-item">
                <div className="stat-value">{stats.passRate}%</div>
                <div className="stat-label">通过率 ({stats.total}次)</div>
              </div>
              <div className="stat-item">
                <div className="stat-value">{stats.avgConfidence}</div>
                <div className="stat-label">平均置信度</div>
              </div>
              <div className="stat-item">
                <div className="stat-value">{stats.avgIterations}</div>
                <div className="stat-label">平均迭代轮数</div>
              </div>
              <div className="stat-item">
                <div className="stat-value">{stats.avgLatency}s</div>
                <div className="stat-label">平均耗时</div>
              </div>
            </div>
          ) : (
            <p className="empty-hint">运行测试后显示统计指标</p>
          )}
        </div>
      </div>

      {/* 实时测试 */}
      <div className="sys-card full-width">
        <h2>实时测试</h2>
        <div className="test-bar">
          <input
            className="test-input"
            value={testQuery}
            onChange={e => setTestQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && runTest()}
            placeholder="输入测试查询..."
            disabled={testing}
          />
          <button className="test-btn" onClick={runTest} disabled={testing || !testQuery.trim()}>
            {testing ? '测试中...' : '▶ 测试'}
          </button>
          {testRecords.length > 0 && (
            <button className="clear-records-btn" onClick={() => setTestRecords([])}>
              清除记录
            </button>
          )}
        </div>

        {/* 测试记录 */}
        {testRecords.length > 0 && (
          <div className="test-records">
            {testRecords.map((r, i) => (
              <div key={r.id} className={`test-record ${r.passed ? 'passed' : 'failed'}`}>
                <span className="record-num">#{testRecords.length - i}</span>
                <span className="record-status">{r.passed ? '✅' : '❌'}</span>
                <span className="record-query">{r.query.slice(0, 40)}{r.query.length > 40 ? '...' : ''}</span>
                <span className="record-meta">
                  conf={r.confidence.toFixed(2)} · iter={r.iterations} · chunks={r.chunks} · {(r.latencyMs/1000).toFixed(1)}s
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Agent 参数 */}
      <div className="sys-card full-width">
        <h2>Agent 参数</h2>
        <div className="param-row">
          <label className="param-label">max_iterations</label>
          <input
            type="range"
            min={1}
            max={5}
            value={maxIterations}
            onChange={e => setMaxIterations(Number(e.target.value))}
            className="param-slider"
          />
          <span className="param-value">{maxIterations}</span>
          <span className="param-hint">Agent 最大 ReAct 轮次（调整后在上方测试区验证效果）</span>
        </div>
      </div>
    </div>
  );
};
```

### 5.2 SystemPage.css

文件：`src/frontend/web/src/pages/SystemPage.css`

```css
.system-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 40px 24px;
}

.system-page h1 {
  font-size: 24px;
  font-weight: 700;
  margin-bottom: 6px;
}

.system-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 20px;
}

@media (max-width: 768px) {
  .system-grid { grid-template-columns: 1fr; }
}

.sys-card {
  padding: 24px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 14px;
}

.sys-card.full-width {
  margin-bottom: 20px;
}

.sys-card h2 {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 16px;
  color: var(--text-primary);
}

/* ── 四库状态 ─────────────────────── */

.sys-health-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sys-health-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: var(--bg-primary);
  border-radius: 8px;
  font-size: 13px;
}

.sys-health-name {
  font-weight: 500;
  color: var(--text-primary);
}

.sys-health-val {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-muted);
}

.sys-health-overall {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-muted);
}

/* ── Agent 统计 ───────────────────── */

.sys-stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.stat-item {
  padding: 12px;
  background: var(--bg-primary);
  border-radius: 10px;
  border: 1px solid var(--border-default);
  text-align: center;
}

.stat-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--color-primary);
}

.stat-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 4px;
}

.empty-hint {
  font-size: 13px;
  color: var(--text-muted);
  text-align: center;
  padding: 20px 0;
}

/* ── 实时测试 ─────────────────────── */

.test-bar {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 16px;
}

.test-input {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid var(--border-default);
  border-radius: 10px;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
}

.test-input:focus {
  border-color: var(--color-primary);
}

.test-btn {
  padding: 10px 18px;
  border: none;
  border-radius: 10px;
  background: var(--color-primary);
  color: #fff;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
}

.test-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.clear-records-btn {
  padding: 10px 14px;
  border: 1px solid var(--border-default);
  border-radius: 10px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}

.clear-records-btn:hover {
  border-color: var(--color-error);
  color: var(--color-error);
}

.test-records {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 300px;
  overflow-y: auto;
}

.test-record {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 12px;
  border: 1px solid var(--border-default);
}

.test-record.passed {
  background: rgba(34, 197, 94, 0.04);
}

.test-record.failed {
  background: rgba(239, 68, 68, 0.04);
}

.record-num {
  font-weight: 600;
  color: var(--text-muted);
  min-width: 30px;
}

.record-query {
  flex: 1;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.record-meta {
  color: var(--text-muted);
  font-size: 11px;
  white-space: nowrap;
}

/* ── Agent 参数 ───────────────────── */

.param-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.param-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  font-family: monospace;
}

.param-slider {
  width: 160px;
  accent-color: var(--color-primary);
}

.param-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--color-primary);
  min-width: 24px;
  text-align: center;
}

.param-hint {
  font-size: 11px;
  color: var(--text-muted);
}
```

### 5.3 验证

```bash
# 浏览器 http://localhost:3000/system
# 1. 四库状态显示绿点
# 2. 输入测试查询 → 点击测试 → 记录出现在下方
# 3. 多次测试后 → Agent 概览显示通过率、平均置信度等
# 4. 调节 max_iterations slider → 再次测试 → 观察迭代轮数变化
# 5. 深色/浅色切换正常
```

---

### 📋 Phase 5 报告

- [ ] SystemPage 实现
- [ ] 四库健康从 `/health` 拉取
- [ ] 测试走 `/api/v1/agent`（真实 Agent）
- [ ] Agent 概览统计计算正确
- [ ] max_iterations 参数可调
- [ ] 深色/浅色正常

#### 测试记录

```
（粘贴 3-5 次测试的记录截图或文本）
```

#### 举一反三

```
```

---

## Phase 6：清理 + TypeScript 编译 + 最终验证

> ⚠️ 等 Phase 5 审查通过后再执行

### 目标

1. 删除旧的未使用的 store/hook
2. 确保 `tsc --noEmit` 通过
3. 确保 `npm run build` 通过
4. 全页面截图验证

### 6.1 清理旧代码

```bash
cd /home/l/rag-dashboard/src/frontend/web/src

# 备份旧 store（保留 chatStore 可能被新 hook 替代了）
# 注意：不要删除 infrastructureStore.ts（归档页面可能还引用）
# 只备份确认不再 import 的文件
grep -rn "recursionStore\|recursiveStore" pages/ hooks/ services/ App.tsx 2>/dev/null
# 如果 0 结果 → 可以备份
# mv stores/recursionStore.ts stores/recursionStore.ts.bak
# mv stores/recursiveStore.ts stores/recursiveStore.ts.bak
```

> **Kimi 自行判断**：用 `grep -rn "文件名" src/` 检查是否还有 import，有则保留，无则备份。

### 6.2 TypeScript 编译检查

```bash
cd /home/l/rag-dashboard/src/frontend/web
npx tsc --noEmit 2>&1 | head -40

# 如果有类型错误，逐一修复。常见问题：
# - 缺少 React import → 加 import React from 'react'（如果 tsconfig 没开 jsx: react-jsx）
# - @rag/shared 类型缺失 → 确保 packages/shared 已构建
```

### 6.3 构建验证

```bash
cd /home/l/rag-dashboard/src/frontend/web
npm run build 2>&1 | tail -10

# 期望：无错误，生成 dist/ 目录
```

### 6.4 全页面验证清单

启动前端 `npm run dev`，逐页检查：

| 页面 | URL | 深色 ✅/❌ | 浅色 ✅/❌ | 窄屏 ✅/❌ | API 真实 ✅/❌ |
|------|-----|-----------|-----------|-----------|--------------|
| 问答 | `/` | | | | `/api/v1/agent` |
| 检索 | `/search` | | | | `/api/v1/search` |
| 数据管道 | `/pipeline` | | | | `/health` + 上传 |
| 系统 | `/system` | | | | `/health` + `/api/v1/agent` |

### 6.5 前后对比

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| 导航页数 | 8 个（含 3 个教学文档） | 4 个核心 + 3 个归档 |
| 对话入口 | 3 条（互不相通） | 1 条（`/api/v1/agent`） |
| 自嗨按钮 | ~20 个 | 0 个 |
| inline style 颜色 | 50%+ 组件 | 0 |
| Store 被 API 填充 | 2/8 | 页面内 state + hook |
| 主题切换 | 部分失效 | 全面支持 |

---

### 📋 Phase 6 报告

- [ ] 旧代码已备份/清理
- [ ] `tsc --noEmit` 通过
- [ ] `npm run build` 通过
- [ ] 4 个页面深色/浅色/窄屏全部正常
- [ ] 所有 API 调用指向真实后端

#### 全页面截图

```
（贴 4 个页面的深色 + 浅色截图，或描述验证结果）
```

#### 最终举一反三

```
（回顾整个改造，还有什么可以做得更好？）
```

---

## 执行总览

```
Phase 1 (清理 + 导航重构)
├─ 1.1 备份自嗨组件
├─ 1.2 重写 App.tsx（4 页导航）
├─ 1.3 重写 App.css（留白风格）
└─ 1.4 创建 4 个页面占位
          ↓
Phase 2 (AgentChat — 核心问答页)
├─ 2.1 agentApi.ts（API 层）
├─ 2.2 useAgent hook
├─ 2.3 AgentChat.tsx
└─ 2.4 AgentChat.css
          ↓
Phase 3 (SearchPage — 文档检索)
├─ 3.1 SearchPage.tsx
└─ 3.2 SearchPage.css
          ↓
Phase 4 (PipelinePage — 数据管道)
├─ 4.1 PipelinePage.tsx
└─ 4.2 PipelinePage.css
          ↓
Phase 5 (SystemPage — 系统看板)
├─ 5.1 SystemPage.tsx
└─ 5.2 SystemPage.css
          ↓
Phase 6 (清理 + 编译 + 最终验证)
├─ 6.1 清理旧代码
├─ 6.2 tsc --noEmit
├─ 6.3 npm run build
└─ 6.4 全页面验证
```

**每个 Phase 完成后等 Copilot 审查再继续。**  
**新增文件约 10 个，修改 2 个（App.tsx + App.css），备份约 5 个。**  
**核心原则：每个按钮背后有真实 API，每个颜色走 CSS 变量，每处设计有留白。**

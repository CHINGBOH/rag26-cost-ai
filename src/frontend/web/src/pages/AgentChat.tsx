/**
 * RAG 问答页 — 3-panel layout
 * Left: config | Center: chat | Right: process visualization
 */

import { useState, useRef, useEffect } from 'react';
import { useAgent, ChatMessage, AgentConfig } from '../hooks/useAgent';
import { useRunStore } from '../stores/useRunStore';
import { submitFeedback } from '../services/metricsApi';
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  Radar,
  ResponsiveContainer,
  Tooltip,
} from 'recharts';
import './AgentChat.css';

/* ── Simple Markdown Renderer ───────────────────────── */
/** Converts **bold**, `code`, and line-breaks to HTML. No external deps. */
function renderMarkdown(text: string): string {
  return text
    // bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // inline code
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // line breaks
    .replace(/\n/g, '<br />');
}

/* ── Config State ────────────────────────────────────── */

interface ConfigState {
  searchMode: string;
  maxIterations: number;
  scoreThreshold: number;
  topK: number;
  docTypes: string[];
}

const DEFAULT_CONFIG: ConfigState = {
  searchMode: 'hybrid',
  maxIterations: 3,
  scoreThreshold: 0.6,
  topK: 8,
  docTypes: [],
};

const DOC_TYPE_OPTIONS = ['信息价', '定额', '费率', '指南', '划分'];

/* ── Main Component ──────────────────────────────────── */

export const AgentChat: React.FC = () => {
  const { messages, isLoading, sendMessage, clearMessages, cancelStream, sessionId } = useAgent();
  const [input, setInput] = useState('');
  const [config, setConfig] = useState<ConfigState>(DEFAULT_CONFIG);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = () => {
    if (!input.trim() || isLoading) return;
    const agentConfig: AgentConfig = {
      maxIterations: config.maxIterations,
      scoreThreshold: config.scoreThreshold,
      topK: config.topK,
      searchMode: config.searchMode,
      docTypes: config.docTypes,
    };
    sendMessage(input, agentConfig);
    setInput('');
    inputRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const toggleDocType = (dt: string) => {
    setConfig((c) => ({
      ...c,
      docTypes: c.docTypes.includes(dt) ? c.docTypes.filter((x) => x !== dt) : [...c.docTypes, dt],
    }));
  };

  return (
    <div className="agent-chat-3panel">
      {/* ── Left Panel ── */}
      <aside className="left-panel">
        <div className="panel-section">
          <h3 className="panel-title">会话</h3>
          <div className="session-info">
            <span className="session-id">{sessionId ? sessionId.slice(0, 8) + '…' : '新会话'}</span>
            <button className="new-session-btn" onClick={clearMessages}>+ 新对话</button>
          </div>
        </div>

        <div className="panel-section">
          <h3 className="panel-title">检索模式</h3>
          <div className="mode-select">
            {['hybrid', 'vector', 'text', 'price'].map((m) => (
              <button
                key={m}
                className={`mode-btn ${config.searchMode === m ? 'active' : ''}`}
                onClick={() => setConfig((c) => ({ ...c, searchMode: m }))}
              >
                {m}
              </button>
            ))}
          </div>
        </div>

        <div className="panel-section">
          <h3 className="panel-title">最大迭代次数</h3>
          <div className="slider-row">
            <input
              type="range"
              min={1}
              max={5}
              value={config.maxIterations}
              onChange={(e) => setConfig((c) => ({ ...c, maxIterations: Number(e.target.value) }))}
              className="config-slider"
            />
            <span className="slider-val">{config.maxIterations}</span>
          </div>
        </div>

        <div className="panel-section">
          <h3 className="panel-title">评分阈值</h3>
          <div className="slider-row">
            <input
              type="range"
              min={50}
              max={90}
              value={Math.round(config.scoreThreshold * 100)}
              onChange={(e) =>
                setConfig((c) => ({ ...c, scoreThreshold: Number(e.target.value) / 100 }))
              }
              className="config-slider"
            />
            <span className="slider-val">{(config.scoreThreshold * 100).toFixed(0)}%</span>
          </div>
        </div>

        <div className="panel-section">
          <h3 className="panel-title">Top K</h3>
          <div className="slider-row">
            <input
              type="range"
              min={3}
              max={20}
              value={config.topK}
              onChange={(e) => setConfig((c) => ({ ...c, topK: Number(e.target.value) }))}
              className="config-slider"
            />
            <span className="slider-val">{config.topK}</span>
          </div>
        </div>

        <div className="panel-section">
          <h3 className="panel-title">文档类型</h3>
          <div className="doctype-filters">
            {DOC_TYPE_OPTIONS.map((dt) => (
              <label key={dt} className="doctype-label">
                <input
                  type="checkbox"
                  checked={config.docTypes.includes(dt)}
                  onChange={() => toggleDocType(dt)}
                />
                {dt}
              </label>
            ))}
          </div>
        </div>
      </aside>

      {/* ── Center Panel ── */}
      <main className="center-panel">
        <div className="chat-messages">
          {messages.length === 0 ? (
            <WelcomeScreen onQuickAsk={(q) => sendMessage(q, config)} />
          ) : (
            messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} sessionId={sessionId} />
            ))
          )}
          {isLoading && <StreamingBubble />}
          <div ref={messagesEndRef} />
        </div>

        <div className="chat-input-area">
          <div className="input-wrapper">
            <textarea
              ref={inputRef}
              className="chat-textarea"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入造价相关问题…"
              rows={1}
              disabled={isLoading}
            />
            {isLoading ? (
              <button className="cancel-btn" onClick={cancelStream}>■ 停止</button>
            ) : (
              <button
                className="send-btn"
                onClick={handleSend}
                disabled={!input.trim()}
              >
                ➤
              </button>
            )}
          </div>
          <div className="input-hints">
            <span className="hint-text">Enter 发送 · Shift+Enter 换行</span>
            <span className="char-count">{input.length}</span>
            {messages.length > 0 && (
              <button className="clear-btn" onClick={clearMessages}>清空对话</button>
            )}
          </div>
        </div>
      </main>

      {/* ── Right Panel ── */}
      <aside className="right-panel">
        <ProcessVisualization />
      </aside>
    </div>
  );
};

/* ── Welcome Screen ──────────────────────────────────── */

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

/* ── Message Bubble ──────────────────────────────────── */

const MessageBubble: React.FC<{ message: ChatMessage; sessionId: string | null }> = ({
  message,
  sessionId,
}) => {
  const [showDetail, setShowDetail] = useState(false);
  const [feedbackSent, setFeedbackSent] = useState<number | null>(null);

  const sendFeedback = async (rating: number) => {
    if (!sessionId || feedbackSent !== null) return;
    try {
      await submitFeedback({
        session_id: sessionId,
        message_id: message.id,
        rating,
        query: undefined,
        answer_summary: message.content.slice(0, 200),
      });
      setFeedbackSent(rating);
    } catch (e) {
      console.error('Feedback error', e);
    }
  };

  if (message.error) {
    return (
      <div className="message-row assistant">
        <div className="message-bubble error">❌ {message.error}</div>
      </div>
    );
  }

  return (
    <div className={`message-row ${message.role}`}>
      <div className={`message-bubble ${message.role}`}>
        <div
          className="message-content"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }}
        />

        {message.role === 'assistant' && (
          <div className="message-meta">
            {message.evalScores && (
              <span className="meta-tag confidence">
                置信度 {(message.evalScores.confidence * 100).toFixed(0)}%
              </span>
            )}
            {message.iterations != null && (
              <span className="meta-tag iterations">迭代 {message.iterations} 轮</span>
            )}
            {message.chunks && (
              <span className="meta-tag chunks">引用 {message.chunks.length} 篇</span>
            )}
            {message.latencyMs && (
              <span className="meta-tag latency">{(message.latencyMs / 1000).toFixed(1)}s</span>
            )}

            {/* Feedback buttons */}
            <div className="feedback-btns">
              <button
                className={`feedback-btn ${feedbackSent === 1 ? 'active' : ''}`}
                onClick={() => sendFeedback(1)}
                title="有帮助"
                disabled={feedbackSent !== null}
              >
                👍
              </button>
              <button
                className={`feedback-btn ${feedbackSent === -1 ? 'active' : ''}`}
                onClick={() => sendFeedback(-1)}
                title="没帮助"
                disabled={feedbackSent !== null}
              >
                👎
              </button>
            </div>

            {message.chunks && message.chunks.length > 0 && (
              <button className="detail-toggle" onClick={() => setShowDetail(!showDetail)}>
                {showDetail ? '收起 ▲' : '详情 ▼'}
              </button>
            )}
          </div>
        )}

        {showDetail && message.role === 'assistant' && message.chunks && (
          <div className="message-detail">
            <h4>📎 引用文档</h4>
            {message.chunks.slice(0, 5).map((chunk, i) => (
              <div key={i} className="chunk-item">
                <span className="chunk-score">{(chunk.score * 100).toFixed(1)}%</span>
                <span className="chunk-content">
                  {chunk.content.slice(0, 200)}
                  {chunk.content.length > 200 && '…'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

/* ── Streaming Bubble ────────────────────────────────── */

const StreamingBubble: React.FC = () => {
  const streamingAnswer = useRunStore((s) => s.streamingAnswer);
  const queryAnalysis = useRunStore((s) => s.queryAnalysis);

  if (!streamingAnswer && !queryAnalysis) {
    return (
      <div className="message-row assistant">
        <div className="message-bubble thinking">
          <div className="thinking-dots">
            <span /><span /><span />
          </div>
          <span className="thinking-text">正在检索和分析…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="message-row assistant">
      <div className="message-bubble assistant streaming">
        <div className="message-content">
          {streamingAnswer
            ? <span dangerouslySetInnerHTML={{ __html: renderMarkdown(streamingAnswer) }} />
            : <span className="thinking-text">正在生成回答…</span>}
        </div>
        <span className="streaming-cursor" />
      </div>
    </div>
  );
};

/* ── Process Visualization (Right Panel) ─────────────── */

const ProcessVisualization: React.FC = () => {
  const runStore = useRunStore();
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const toggle = (key: string) =>
    setCollapsed((c) => ({ ...c, [key]: !c[key] }));

  const Section: React.FC<{
    id: string;
    title: string;
    count?: number;
    children: React.ReactNode;
  }> = ({ id, title, count, children }) => (
    <div className="proc-section">
      <button className="proc-section-header" onClick={() => toggle(id)}>
        <span>{title}</span>
        {count != null && count > 0 && <span className="proc-badge">{count}</span>}
        <span className="proc-chevron">{collapsed[id] ? '▶' : '▼'}</span>
      </button>
      {!collapsed[id] && <div className="proc-section-body">{children}</div>}
    </div>
  );

  return (
    <div className="process-viz">
      <div className="proc-header">
        <span>⚙ 执行过程</span>
        {runStore.isStreaming && <span className="proc-live">● LIVE</span>}
      </div>

      {/* 1. Query Analysis */}
      <Section id="qa" title="查询分析" count={runStore.queryAnalysis ? 1 : 0}>
        {runStore.queryAnalysis ? (
          <div className="qa-display">
            <div className="qa-intent">
              <span className="qa-label">意图</span>
              <span className="qa-badge">{runStore.queryAnalysis.intent || '–'}</span>
            </div>
            {runStore.queryAnalysis.entities &&
              Object.entries(runStore.queryAnalysis.entities).map(([k, v]) => (
                <div key={k} className="qa-entity">
                  <span className="qa-key">{k}:</span>
                  <span>{String(v)}</span>
                </div>
              ))}
            {runStore.queryAnalysis.sub_queries && runStore.queryAnalysis.sub_queries.length > 0 && (
              <div className="qa-subqueries">
                {runStore.queryAnalysis.sub_queries.map((q, i) => (
                  <div key={i} className="qa-subquery">↳ {q}</div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <p className="proc-empty">等待查询分析…</p>
        )}
      </Section>

      {/* 1b. Execution Plan */}
      {runStore.planSteps.length > 0 && (
        <Section id="plan" title="执行计划" count={runStore.planSteps.length}>
          <ol className="plan-list">
            {runStore.planSteps.map((step, i) => (
              <li key={i} className="plan-step">{step}</li>
            ))}
          </ol>
        </Section>
      )}

      {/* 2. Retrieval Results */}
      <Section id="ret" title="检索结果" count={runStore.retrievalChunks.length}>
        {runStore.retrievalChunks.length > 0 ? (
          <div className="ret-list">
            {runStore.retrievalChunks.slice(0, 8).map((c, i) => (
              <div key={i} className={`ret-chunk ${c.passed_threshold ? 'passed' : 'filtered'}`}>
                <div className="ret-chunk-header">
                  <span className="ret-doc">{c.doc_id.slice(0, 20)}</span>
                  <span className="ret-score">{(c.score * 100).toFixed(0)}%</span>
                </div>
                <div className="ret-score-bar">
                  <div
                    className="ret-score-fill"
                    style={{ width: `${c.score * 100}%` }}
                  />
                </div>
                <div className="ret-content">{c.content.slice(0, 80)}…</div>
              </div>
            ))}
          </div>
        ) : (
          <p className="proc-empty">等待检索…</p>
        )}
      </Section>

      {/* 3. Tool Calls */}
      <Section id="tools" title="工具调用" count={runStore.toolCalls.length}>
        {runStore.toolCalls.length > 0 ? (
          <div className="tool-timeline">
            {runStore.toolCalls.map((tc, i) => (
              <div key={i} className={`tool-item status-${tc.status}`}>
                <div className="tool-header">
                  <span className="tool-name">{tc.tool}</span>
                  <span className={`tool-status-badge ${tc.status}`}>
                    {tc.status === 'running' ? '⏳' : tc.status === 'done' ? '✓' : '✗'}
                  </span>
                  {tc.duration_ms != null && tc.duration_ms > 0 && (
                    <span className="tool-duration">{tc.duration_ms}ms</span>
                  )}
                </div>
                {tc.result != null && (
                  <div className="tool-result">{JSON.stringify(tc.result).slice(0, 100)}</div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="proc-empty">无工具调用</p>
        )}
      </Section>

      {/* 4. Sandbox Execution */}
      {runStore.sandboxExecs.length > 0 && (
        <Section id="sandbox" title="沙箱执行" count={runStore.sandboxExecs.length}>
          {runStore.sandboxExecs.map((ex, i) => (
            <div key={i} className="sandbox-item">
              <code className="sandbox-code">{ex.code}</code>
              <div className="sandbox-result">= {ex.result}</div>
              <div className="sandbox-meta">{ex.duration_ms}ms · {ex.safe ? '✓ 安全' : '⚠ 不安全'}</div>
            </div>
          ))}
        </Section>
      )}

      {/* 5. Iteration State */}
      <Section id="loops" title="迭代状态" count={runStore.loopStates.length}>
        {runStore.loopStates.length > 0 ? (
          <div className="loop-list">
            {runStore.loopStates.map((ls, i) => (
              <div key={i} className="loop-item">
                <span className="loop-iter">#{ls.iteration}</span>
                <div className="loop-score-bar-wrap">
                  <div className="loop-score-bar">
                    <div className="loop-score-fill" style={{ width: `${ls.eval_score * 100}%` }} />
                  </div>
                  <span className="loop-score-val">{(ls.eval_score * 100).toFixed(0)}%</span>
                </div>
                {ls.rewrite_reason && (
                  <div className="loop-reason">{ls.rewrite_reason}</div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="proc-empty">等待迭代…</p>
        )}
      </Section>

      {/* 6. Evaluator Scores */}
      <Section id="eval" title="评估分数" count={runStore.evalScores ? 7 : 0}>
        {runStore.evalScores ? (
          <EvalRadarChart scores={runStore.evalScores} />
        ) : (
          <p className="proc-empty">等待评估…</p>
        )}
      </Section>

      {/* 7. Performance Stats */}
      <Section id="perf" title="性能统计" count={runStore.finalLatencyMs > 0 ? 1 : 0}>
        {runStore.finalLatencyMs > 0 ? (
          <table className="perf-table">
            <tbody>
              <tr><td>总延迟</td><td>{runStore.finalLatencyMs}ms</td></tr>
              <tr><td>迭代次数</td><td>{runStore.finalIterations}</td></tr>
              {runStore.tokensIn > 0 && <tr><td>输入 tokens</td><td>{runStore.tokensIn}</td></tr>}
              {runStore.tokensOut > 0 && <tr><td>输出 tokens</td><td>{runStore.tokensOut}</td></tr>}
              {runStore.tokensThink > 0 && <tr><td>思考 tokens</td><td>{runStore.tokensThink}</td></tr>}
            </tbody>
          </table>
        ) : (
          <p className="proc-empty">运行完成后显示统计</p>
        )}
      </Section>
    </div>
  );
};

/* ── Eval Radar Chart ────────────────────────────────── */

import type { EvalScores } from '../stores/useRunStore';

const EVAL_LABELS: Record<keyof EvalScores, string> = {
  completeness: '完整性',
  consistency: '一致性',
  confidence: '置信度',
  information_gain: '信息增益',
  source_diversity: '来源多样',
  fact_consistency: '事实一致',
  coverage_estimate: '覆盖估计',
};

const EvalRadarChart: React.FC<{ scores: EvalScores }> = ({ scores }) => {
  const data = (Object.keys(scores) as Array<keyof EvalScores>).map((k) => ({
    subject: EVAL_LABELS[k],
    value: Math.round(scores[k] * 100),
    fullMark: 100,
  }));

  return (
    <div className="eval-radar">
      <ResponsiveContainer width="100%" height={200}>
        <RadarChart data={data}>
          <PolarGrid />
          <PolarAngleAxis dataKey="subject" tick={{ fontSize: 10 }} />
          <Radar
            name="评分"
            dataKey="value"
            stroke="var(--color-primary)"
            fill="var(--color-primary)"
            fillOpacity={0.25}
          />
          <Tooltip formatter={(v) => [`${v}%`]} />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
};

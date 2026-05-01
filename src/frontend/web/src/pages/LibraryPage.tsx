/**
 * LibraryPage — 图书馆员模式（极简咨询界面）
 *
 * 设计原则：用户只需开口提问，馆员自动查阅并作答。
 * 无任何技术配置暴露给用户；专业参数固定为最优默认值。
 */

import { useState, useRef, useEffect } from 'react';
import { useAgent, AgentConfig } from '../hooks/useAgent';
import { useRunStore } from '../stores/useRunStore';
import { submitFeedback } from '../services/metricsApi';
import { AgentChunk } from '../services/agentApi';
import type { ChatMessage } from '../hooks/useAgent';
import './LibraryPage.css';

/* ── Fixed config — never exposed to user ────────────── */
const LIBRARY_CONFIG: AgentConfig = {
  maxIterations: 3,
  scoreThreshold: 0.6,
  topK: 8,
  searchMode: 'hybrid',
  docTypes: [],
  llmRoute: 'deepseek',
  llmModel: 'deepseek-chat',
  llmEngine: 'api',
};

const QUICK_QUESTIONS = [
  '2025版费率标准中，企业管理费的计算方法是什么？',
  '某工程人工费500万，按2025版费率计算企业管理费是多少？',
  '2026年1月普通硅酸盐水泥P.O 42.5的含税价格是多少？',
  '一般计税与简易计税的适用条件分别是什么？',
];

/* ── Markdown renderer (XSS-safe) ────────────────────── */
const HTML_ESCAPE: Record<string, string> = {
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
};
function escapeHtml(s: string): string {
  return String(s).replace(/[&<>"']/g, ch => HTML_ESCAPE[ch] || ch);
}
function renderMarkdown(text: string): string {
  if (!text) return '';
  return escapeHtml(String(text))
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br />');
}

/* ── Source label helper ──────────────────────────────── */
function chunkLabel(chunk: AgentChunk): string {
  const meta = chunk.metadata;
  if (meta?.title) return String(meta.title);
  if (chunk.source) return chunk.source.replace(/\.[^.]+$/, '');
  return chunk.doc_id;
}

/* ── Main page ───────────────────────────────────────── */
export const LibraryPage: React.FC = () => {
  const { messages, isLoading, sendMessage, clearMessages, sessionId } = useAgent();
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const ask = (q: string) => {
    if (!q.trim() || isLoading) return;
    sendMessage(q, LIBRARY_CONFIG);
    setInput('');
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(input); }
  };

  return (
    <div className="library-page">
      {/* ── Header ── */}
      <div className="library-header">
        <span className="lib-icon">📚</span>
        <div className="lib-header-text">
          <h1 className="lib-title">企业知识库</h1>
          <p className="lib-subtitle">智能问答 · 精准检索 · 文档管理</p>
        </div>
        {messages.length > 0 && (
          <button className="lib-new-btn" onClick={clearMessages}>新咨询</button>
        )}
      </div>

      {/* ── Chat area ── */}
      <div className="library-chat">
        {messages.length === 0
          ? <LibraryWelcome onAsk={ask} />
          : messages.map(msg => (
              <LibraryBubble
                key={msg.id}
                message={msg}
                sessionId={sessionId}
                onFollowup={ask}
              />
            ))
        }
        {isLoading && <LibraryThinking />}
        <div ref={bottomRef} />
      </div>

      {/* ── Input ── */}
      <div className="library-input-area">
        <textarea
          ref={inputRef}
          className="lib-textarea"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="请问馆员想查什么资料……"
          rows={1}
          disabled={isLoading}
        />
        <button
          className="lib-send-btn"
          onClick={() => ask(input)}
          disabled={!input.trim() || isLoading}
        >
          发送
        </button>
      </div>
    </div>
  );
};

/* ── Welcome screen ──────────────────────────────────── */
const LibraryWelcome: React.FC<{ onAsk: (q: string) => void }> = ({ onAsk }) => (
  <div className="lib-welcome">
    <div className="lib-avatar-large">📚</div>
    <p className="lib-greeting">您好，我是您的企业知识助理</p>
    <p className="lib-desc">
      馆内收录您上传的企业文档，有任何业务问题，请直接告诉我。
    </p>
    <div className="lib-quick-list">
      {QUICK_QUESTIONS.map((q, i) => (
        <button key={i} className="lib-quick-btn" onClick={() => onAsk(q)}>
          {q}
        </button>
      ))}
    </div>
  </div>
);

/* ── Message bubble ──────────────────────────────────── */
const LibraryBubble: React.FC<{
  message: ChatMessage;
  sessionId: string | null;
  onFollowup: (q: string) => void;
}> = ({ message, sessionId, onFollowup }) => {
  const [showSources, setShowSources] = useState(false);
  const [feedbackSent, setFeedbackSent] = useState<number | null>(null);

  const sendFeedback = async (rating: number) => {
    if (!sessionId || feedbackSent !== null) return;
    try {
      await submitFeedback({
        session_id: sessionId,
        message_id: message.id,
        rating,
        answer_summary: message.content.slice(0, 200),
      });
      setFeedbackSent(rating);
    } catch { /* silent */ }
  };

  /* Error state */
  if (message.error) {
    return (
      <div className="lib-row assistant">
        <span className="lib-avatar">📚</span>
        <div className="lib-bubble lib-bubble--error">
          ⚠️ 抱歉，查阅时遇到了问题，请稍后再试。
        </div>
      </div>
    );
  }

  /* User message */
  if (message.role === 'user') {
    return (
      <div className="lib-row lib-row--user">
        <div className="lib-bubble lib-bubble--user">{message.content}</div>
      </div>
    );
  }

  /* Assistant message */
  const chunks = message.chunks ?? [];
  const uniqueSources = [...new Map(chunks.map(c => [chunkLabel(c), c])).values()];

  return (
    <div className="lib-row assistant">
      <span className="lib-avatar">📚</span>
      <div className="lib-bubble-wrap">
        <div className="lib-bubble lib-bubble--assistant">
          <div dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }} />
        </div>

        {/* Source references */}
        {uniqueSources.length > 0 && (
          <div className="lib-sources">
            <button
              className="lib-sources-toggle"
              onClick={() => setShowSources(v => !v)}
            >
              📖 查阅了 {uniqueSources.length} 份资料 {showSources ? '▲' : '▼'}
            </button>
            {showSources && (
              <div className="lib-sources-list">
                {uniqueSources.slice(0, 6).map((c, i) => (
                  <span key={i} className="lib-source-tag">《{chunkLabel(c)}》</span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Follow-up suggestions */}
        {message.followups && message.followups.length > 0 && (
          <div className="lib-followups">
            <span className="lib-followups-label">您可能还想了解：</span>
            <div className="lib-followup-chips">
              {message.followups.slice(0, 4).map((f, i) => (
                <button key={i} className="lib-followup-chip" onClick={() => onFollowup(f.question)}>
                  {f.question}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Feedback */}
        <div className="lib-feedback">
          <button
            className={`lib-fb-btn ${feedbackSent === 1 ? 'lib-fb-btn--active' : ''}`}
            onClick={() => sendFeedback(1)}
            disabled={feedbackSent !== null}
          >👍 有帮助</button>
          <button
            className={`lib-fb-btn ${feedbackSent === -1 ? 'lib-fb-btn--active' : ''}`}
            onClick={() => sendFeedback(-1)}
            disabled={feedbackSent !== null}
          >👎 没帮助</button>
        </div>
      </div>
    </div>
  );
};

/* ── Streaming / thinking bubble ─────────────────────── */
const LibraryThinking: React.FC = () => {
  const statusMessage = useRunStore(s => s.statusMessage);
  const streamingAnswer = useRunStore(s => s.streamingAnswer);

  return (
    <div className="lib-row assistant">
      <span className="lib-avatar">📚</span>
      <div className="lib-bubble lib-bubble--assistant lib-bubble--streaming">
        {streamingAnswer
          ? <span dangerouslySetInnerHTML={{ __html: renderMarkdown(streamingAnswer) }} />
          : <span className="lib-thinking-text">
              {statusMessage || '馆员正在查阅资料…'}
              <span className="lib-dots">···</span>
            </span>
        }
      </div>
    </div>
  );
};

export default LibraryPage;

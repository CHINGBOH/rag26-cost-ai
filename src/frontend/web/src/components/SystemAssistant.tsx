/**
 * SystemAssistant — floating chat widget explaining the RAG system internals.
 * Uses /api/v1/guide-agent/stream: true LangChain tool-calling agent backed by rag_system_kb.
 * Renders Mermaid diagrams when LLM outputs ```mermaid blocks.
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import mermaid from 'mermaid';
import './SystemAssistant.css';

mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'loose' });

// Strip residual markdown — used on plain-text segments only
function renderTextPart(text: string): string {
  if (!text) return '';
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/^#{1,6}\s*/gm, '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*/g, '')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^---+$/gm, '')
    .replace(/^[-•]\s+(.+)$/gm, '$1')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/\n/g, '<br />');
}

// Renders a single Mermaid diagram; falls back to <pre> on parse error
const MermaidBlock: React.FC<{ code: string }> = ({ code }) => {
  const [svg, setSvg] = useState('');
  const [error, setError] = useState(false);
  const uid = useRef(`sa-mmd-${Math.random().toString(36).slice(2)}`);

  useEffect(() => {
    let cancelled = false;
    setSvg('');
    setError(false);
    mermaid.render(uid.current, code.trim())
      .then(({ svg: s }) => { if (!cancelled) setSvg(s); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [code]);

  if (error) return <pre className="sa-mermaid-fallback">{code}</pre>;
  if (!svg) return <div className="sa-mermaid-loading">⏳ 绘图中…</div>;
  return <div className="sa-mermaid" dangerouslySetInnerHTML={{ __html: svg }} />;
};

// Splits assistant message content into text and mermaid segments
const MERMAID_RE = /```mermaid\n([\s\S]*?)\n```/g;

const AssistantMessage: React.FC<{ content: string; streaming?: boolean }> = ({ content, streaming }) => {
  if (!content) return null;

  const segments: Array<{ type: 'text' | 'mermaid'; value: string }> = [];
  let lastIndex = 0;
  let m: RegExpExecArray | null;
  MERMAID_RE.lastIndex = 0;
  while ((m = MERMAID_RE.exec(content)) !== null) {
    if (m.index > lastIndex) segments.push({ type: 'text', value: content.slice(lastIndex, m.index) });
    segments.push({ type: 'mermaid', value: m[1] });
    lastIndex = m.index + m[0].length;
  }
  if (lastIndex < content.length) segments.push({ type: 'text', value: content.slice(lastIndex) });

  return (
    <>
      {segments.map((seg, i) => {
        if (seg.type === 'mermaid' && !streaming) {
          return <MermaidBlock key={i} code={seg.value} />;
        }
        const raw = seg.type === 'mermaid' ? `\`\`\`mermaid\n${seg.value}\n\`\`\`` : seg.value;
        return <span key={i} dangerouslySetInnerHTML={{ __html: renderTextPart(raw) }} />;
      })}
    </>
  );
};

// SSE async generator for the guide agent stream endpoint
async function* sendGuideStream(
  query: string,
  history: Array<{ role: string; content: string }>,
  signal: AbortSignal,
): AsyncGenerator<string, void, unknown> {
  const resp = await fetch('/api/v1/guide-agent/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, history }),
    signal,
  });
  if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let currentEvent = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop() ?? '';

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith('data: ')) {
        try {
          const obj = JSON.parse(line.slice(6).trim());
          if (currentEvent === 'token' && obj.delta) {
            yield obj.delta as string;
          } else if (currentEvent === 'error') {
            throw new Error(obj.message ?? 'guide agent error');
          } else if (currentEvent === 'done') {
            return;
          }
        } catch (e) {
          if (e instanceof SyntaxError) continue;
          throw e;
        }
        currentEvent = '';
      }
    }
  }
}

const MAX_HISTORY_TURNS = 8;

interface Msg {
  role: 'user' | 'assistant';
  content: string;
  streaming?: boolean;
}

export const SystemAssistant: React.FC = () => {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Focus input when panel opens
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  const stopStream = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    if (mountedRef.current) setIsStreaming(false);
  }, []);

  const handleClose = useCallback(() => {
    stopStream();
    setOpen(false);
  }, [stopStream]);

  const handleClear = useCallback(() => {
    stopStream();
    setMessages([]);
  }, [stopStream]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput('');

    // Capture history BEFORE mutating state — these are the prior completed turns
    const historySnapshot = messages
      .slice(-MAX_HISTORY_TURNS * 2)
      .map(m => ({ role: m.role, content: m.content }));

    setMessages(prev => {
      const trimmed =
        prev.length > MAX_HISTORY_TURNS * 2
          ? prev.slice(prev.length - MAX_HISTORY_TURNS * 2)
          : prev;
      return [
        ...trimmed,
        { role: 'user', content: text },
        { role: 'assistant', content: '', streaming: true },
      ];
    });
    setIsStreaming(true);

    const abort = new AbortController();
    abortRef.current = abort;
    let accumulated = '';

    try {
      for await (const delta of sendGuideStream(text, historySnapshot, abort.signal)) {
        if (abort.signal.aborted || !mountedRef.current) break;
        accumulated += delta;
        setMessages(prev => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last?.streaming) next[next.length - 1] = { ...last, content: accumulated };
          return next;
        });
      }
    } catch (e) {
      if (!abort.signal.aborted && mountedRef.current) {
        const msg = e instanceof Error ? e.message : '请求失败';
        setMessages(prev => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last?.streaming) next[next.length - 1] = { ...last, content: `（出错：${msg}）`, streaming: false };
          return next;
        });
        setIsStreaming(false);
        return;
      }
    } finally {
      if (!abort.signal.aborted && mountedRef.current) {
        setMessages(prev => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last?.streaming) next[next.length - 1] = { ...last, streaming: false };
          return next;
        });
        setIsStreaming(false);
      }
    }
  }, [input, isStreaming, messages]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <>
      {/* Floating trigger */}
      <button
        className={`sa-trigger${open ? ' sa-trigger--open' : ''}`}
        onClick={() => (open ? handleClose() : setOpen(true))}
        title="RAG 系统导览助手"
        aria-label={open ? '关闭系统助手' : '打开系统助手'}
      >
        <span className="sa-trigger-icon" aria-hidden="true">
          {open ? '✕' : '💡'}
        </span>
        {!open && <span className="sa-trigger-label">系统助手</span>}
      </button>

      {/* Chat panel */}
      {open && (
        <div className="sa-panel" role="dialog" aria-label="RAG 系统导览助手">
          <div className="sa-header">
            <span className="sa-header-icon" aria-hidden="true">💡</span>
            <span className="sa-header-title">系统导览助手</span>
            <div className="sa-header-actions">
              <button className="sa-btn-icon" onClick={handleClear} title="清空对话">
                ↺
              </button>
              <button className="sa-btn-icon" onClick={handleClose} title="关闭">
                ✕
              </button>
            </div>
          </div>

          <div className="sa-messages" aria-live="polite">
            {messages.length === 0 && (
              <div className="sa-empty">
                <p className="sa-empty-intro">您好！我是本系统的导览助手，可以解答：</p>
                <ul className="sa-empty-hints">
                  <li>系统整体架构是什么样的？（可画图）</li>
                  <li>检索请求的完整流程？（可画图）</li>
                  <li>为什么有时候回答说"信息不足"？</li>
                  <li>沙盒计算是怎么执行的？</li>
                  <li>知识库用了哪些数据库？</li>
                </ul>
              </div>
            )}

            {messages.map((m, i) => (
              <div key={i} className={`sa-msg sa-msg--${m.role}`}>
                <div className="sa-msg-content">
                  {m.role === 'user'
                    ? m.content
                    : !m.content && m.streaming
                      ? <span className="sa-cursor">▍</span>
                      : <AssistantMessage content={m.content} streaming={m.streaming} />}
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>

          <div className="sa-input-row">
            <textarea
              ref={inputRef}
              className="sa-input"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="问我关于系统的任何问题… (Enter 发送)"
              rows={2}
              disabled={isStreaming}
              aria-label="输入问题"
            />
            <button
              className={`sa-send${isStreaming ? ' sa-send--stop' : ''}`}
              onClick={isStreaming ? stopStream : send}
              disabled={!isStreaming && !input.trim()}
              aria-label={isStreaming ? '停止' : '发送'}
            >
              {isStreaming ? '停止' : '发送'}
            </button>
          </div>
        </div>
      )}
    </>
  );
};

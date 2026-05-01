/**
 * SystemAssistant — floating chat widget explaining the RAG system internals.
 * Routes LLM calls through /api/v1/llm/chat (retrieval-service proxy)
 * so it works even when the Node.js server is not running.
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import { sendLLMStream, LLMMessage } from '../services/llmApi';
import { retrieveDocs } from '../utils/docRetrieval';
import './SystemAssistant.css';

// ── Lean system prompt + doc context injected per-query ─────────────────────
const BASE_SYSTEM_PROMPT = `你是 RAG 智库系统的专属导览助手。
职责：解答关于本系统的工作原理、使用方法、内部机制的所有问题。
风格：简洁通俗，不用技术术语炫技，让不懂计算机的业务用户也能看懂。
约束：不回答与本系统无关的问题；不掌握实时运行数据（需要实时数据请去"系统运维"页面）。

如果用户问题在"参考文档"里有对应内容，优先使用文档内容作答。
如果文档里没有，可结合本系统架构常识回答，但要说明"这是一般原则"。`;

const ASSISTANT_MODEL = 'deepseek-v4-flash';

// Keep last N turns to avoid token bloat
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

    // Snapshot messages before mutating state
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

    // Build history — inject retrieved docs as context in system message
    const relevantDocs = retrieveDocs(text);
    const systemContent = relevantDocs
      ? `${BASE_SYSTEM_PROMPT}\n\n---\n\n# 参考文档（与本次问题相关）\n\n${relevantDocs}`
      : BASE_SYSTEM_PROMPT;

    const history: LLMMessage[] = [
      { role: 'system', content: systemContent },
      ...messages
        .slice(-MAX_HISTORY_TURNS * 2)
        .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content })),
      { role: 'user', content: text },
    ];

    const abort = new AbortController();
    abortRef.current = abort;
    let accumulated = '';

    try {
      for await (const chunk of sendLLMStream(history, {
        temperature: 0.5,
        maxTokens: 1400,
        model: ASSISTANT_MODEL,
        endpoint: '/api/v1/llm/chat',
      })) {
        if (abort.signal.aborted || !mountedRef.current) break;
        const delta = chunk.choices[0]?.delta?.content ?? '';
        if (delta) {
          accumulated += delta;
          setMessages(prev => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last?.streaming) next[next.length - 1] = { ...last, content: accumulated };
            return next;
          });
        }
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
                  <li>系统内部是怎么工作的？</li>
                  <li>为什么有时候回答说"信息不足"？</li>
                  <li>如何提问才能得到最准确的答案？</li>
                  <li>沙盒计算是怎么执行的？</li>
                  <li>知识库用了哪些数据库？</li>
                </ul>
              </div>
            )}

            {messages.map((m, i) => (
              <div key={i} className={`sa-msg sa-msg--${m.role}`}>
                <div className="sa-msg-content">
                  {m.content || (m.streaming ? <span className="sa-cursor">▍</span> : null)}
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

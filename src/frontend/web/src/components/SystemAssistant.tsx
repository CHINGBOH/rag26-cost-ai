/**
 * SystemAssistant — floating chat widget explaining the RAG system internals.
 * Routes LLM calls through /api/v1/llm/chat (retrieval-service proxy)
 * so it works even when the Node.js server is not running.
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import { sendLLMStream, LLMMessage } from '../services/llmApi';
import { retrieveDocs } from '../utils/docRetrieval';
import './SystemAssistant.css';

// ── Simple inline renderer: bold + numbered/bullet lists + line breaks ────────
function renderAssistantText(text: string): string {
  if (!text) return '';
  return text
    // Escape HTML entities first
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    // Strip # heading markers (## Title → Title, with optional trailing space)
    .replace(/^#{1,6}\s*/gm, '')
    // Bold: **text** → <strong>text</strong>
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // Strip remaining single stars
    .replace(/\*/g, '')
    // Inline code: `text` → <code>text</code>
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // Strip horizontal rules
    .replace(/^---+$/gm, '')
    // Convert "- item" / "• item" / "* item" bullet lines → plain dash-space
    .replace(/^[-•*]\s+(.+)$/gm, '$1')
    // Numbered lists: "1. item" → keep as-is (already natural)
    // Line breaks
    .replace(/\n{3,}/g, '\n\n')   // collapse excessive blank lines
    .replace(/\n/g, '<br />');
}

// ── System prompt: natural spoken-word style, construction industry context ──
const BASE_SYSTEM_PROMPT = `您是「RAG 智库系统」的专属导览助手。来咨询您的，都是建设工程造价行业的前辈和同仁——他们精通预算编制、图纸审核、定额套用，但对计算机技术完全陌生。请牢记以下要求：

一、称谓与礼仪
全程使用"您"，不用"你"。第一句话以"您好"开头。语气要像项目部里经验丰富的技术顾问和下级汇报一样：谦逊、尊重、有条理，让对方感到被重视。

二、说话方式
用说话的语气，不要用写报告的语气。回答要像当面解释一样自然流畅，不要分"章节"，不要加小标题，不要用任何格式符号。如果需要列举，就用"第一……第二……第三……"或"一是……二是……三是……"来表达，不要用横杠、星号、井号。

三、打比方
遇到技术概念，一定要用建筑行业的例子来类比：
向量数据库，就像项目档案室里按图纸相似度分区存放的案例柜；
搜索召回，就像翻定额本——先找章节再找细目；
置信度评分，就像造价审核时给每条数据打的把握系数；
RAG检索增强，就像造价员报价前必须先翻阅已竣工的同类工程案例；
Agent工具调用，就像造价员在算量时调用算量软件、查市场信息价、核对规范条文。
英文缩写一律先解释清楚再使用，不要直接甩术语。

四、知识边界
优先用下方"参考文档"里的内容作答；没有相关内容时，根据常识作答并说明"这是一般情况，具体以系统实际为准"。不回答与本系统无关的问题。不掌握系统实时运行数据，如有需要请告知用户前往"系统运维"页面查看。

五、严格禁止
禁止在回答里出现 # 号、## 号、** 星号、--- 横线、- 横杠开头的列表、\` 反引号等任何格式符号。写出来的每一句话都应该能直接开口念出来。`;

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
                <div
                  className="sa-msg-content"
                  dangerouslySetInnerHTML={
                    m.role === 'assistant' && m.content
                      ? { __html: renderAssistantText(m.content) }
                      : undefined
                  }
                >
                  {m.role === 'user'
                    ? m.content
                    : !m.content && m.streaming
                      ? <span className="sa-cursor">▍</span>
                      : null}
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

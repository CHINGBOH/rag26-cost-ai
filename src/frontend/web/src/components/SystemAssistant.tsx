/**
 * SystemAssistant — floating chat widget explaining the RAG system internals.
 * Placed on knowledge-base interaction pages (LibraryPage, etc.).
 * Uses /api/llm/chat via sendLLMStream with a pre-loaded system prompt.
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import { sendLLMStream, LLMMessage } from '../services/llmApi';
import './SystemAssistant.css';

// ── System prompt: accurate architecture description ────────────────────────
const SYSTEM_PROMPT = `你是 RAG 智库系统的专属导览助手，只解答关于本系统内部机制、工作原理和使用方法的问题。用简洁、通俗的中文回答，不用技术术语炫技，让不懂计算机的业务用户也能看懂。

## 系统采用"四库"架构
每种数据库负责一种检索方式，系统会自动选最合适的：
- Qdrant（向量库）：把文档转成数字向量，查"意思相近"的内容
- PostgreSQL（关系库）：存放价格、定额等结构化数字数据，精确查询
- Neo4j（图数据库）：记录概念之间的关系，支持关联推理
- Elasticsearch（全文库）：中文分词关键词匹配，精确找术语

## Agent 可调用的工具（自动选择，无需手动操作）
- hybrid_search：主力检索，向量＋全文组合
- vector_search：纯语义，适合模糊表达
- keyword_search：关键词精确匹配
- concept_search：知识图谱概念关联
- graph_search / topology_search：图数据库关系路径
- price_query：按材料名+规格+月份查价格
- price_trend：价格历史趋势
- rule_clause_search：条文条款专项检索
- pdf_page_search：PDF 原始页面检索
- calculator：数学表达式安全计算（沙盒）
- python_eval：带数据的 Python 计算（沙盒）
- sql_query / aggregate_query：结构化数据统计

## 每次提问的内部流程
1. 分析问题类型（价格/条文/计算/综合）
2. 改写查询语句，提升召回率
3. 多路并行检索，召回 8 个候选段落
4. 重排序模型精排，置信度阈值 0.60
5. LLM 基于检索结果生成答案，标注来源
6. 评估置信度，低于 0.60 明确告知"信息不足"

## 为什么有时候说"信息不足"？
- 真实原因：检索到的内容相关度不足，系统拒绝猜测
- 解决方法：换个角度提问，或查看"系统运维"页确认文档是否已正确索引

## 如何提问更有效？
- 价格查询：材料名 ＋ 规格型号 ＋ 年月，例如"2026年1月 P.O42.5 水泥含税价"
- 费率查询：工程类别 ＋ 计税方式，例如"建筑工程简易计税企业管理费率"
- 计算问题：直接给数字，例如"人工费500万，按8%计算企业管理费"
- 条文查询：说明具体条款名，例如"总承包服务费的适用条件"

## 实时系统状态
本助手不掌握系统实时运行数据。若需了解当前文档数量、索引状态、服务健康情况，请前往"系统运维"页面查看。`;

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

    // Build history from current snapshot (before new messages were appended)
    const history: LLMMessage[] = [
      { role: 'system', content: SYSTEM_PROMPT },
      ...messages
        .slice(-MAX_HISTORY_TURNS * 2)
        .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content })),
      { role: 'user', content: text },
    ];

    const abort = new AbortController();
    abortRef.current = abort;
    let accumulated = '';

    try {
      for await (const chunk of sendLLMStream(history, { temperature: 0.5, maxTokens: 1200 })) {
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

/**
 * 文档检索页 — Agent Toolbox 沙盒
 *
 * 不再是单一搜索框：把 retrieval-service 暴露的所有 @tool 都列出来，
 * 让用户像 agent 一样独立调用每个原子能力（向量/关键词/混合/概念/图谱/拓扑/
 * 类目/文本/PDF 页/规则条款/目录/价格查询/价格趋势/计算器/python_eval）。
 */

import { useEffect, useMemo, useState } from 'react';
import { PageHeader } from '../components/common/PageHeader';
import './SearchPage.css';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

interface ArgSpec {
  title?: string;
  type?: string;
  default?: any;
}

interface ToolMeta {
  name: string;
  description: string;
  category: string;
  args: Record<string, ArgSpec>;
  example: Record<string, any>;
}

interface ToolListResponse {
  tools: ToolMeta[];
  count: number;
  categories: string[];
}

interface InvokeResponse {
  tool: string;
  args: Record<string, any>;
  result: any;
  raw: string;
  latency_ms: number;
  error?: string | null;
}

const CATEGORY_LABELS: Record<string, string> = {
  retrieval: '检索',
  data: '数据',
  graph: '图谱',
  proactive: '主动',
  datasci: '分析',
  pricing: '价格',
  compute: '计算',
  other: '其它',
};

function defaultValueForArg(spec: ArgSpec, exampleValue: any): any {
  if (exampleValue !== undefined) return exampleValue;
  if (spec.default !== undefined) return spec.default;
  switch (spec.type) {
    case 'integer':
    case 'number':
      return 0;
    case 'boolean':
      return false;
    default:
      return '';
  }
}

function coerceArgValue(spec: ArgSpec, raw: string | boolean): any {
  if (typeof raw === 'boolean') return raw;
  if (raw === '') return undefined;
  if (spec.type === 'integer') {
    const n = parseInt(raw, 10);
    return Number.isNaN(n) ? undefined : n;
  }
  if (spec.type === 'number') {
    const n = parseFloat(raw);
    return Number.isNaN(n) ? undefined : n;
  }
  return raw;
}

export const SearchPage: React.FC = () => {
  const [tools, setTools] = useState<ToolMeta[]>([]);
  const [activeName, setActiveName] = useState<string>('');
  const [argsState, setArgsState] = useState<Record<string, any>>({});
  const [response, setResponse] = useState<InvokeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [showRaw, setShowRaw] = useState(false);
  const [history, setHistory] = useState<InvokeResponse[]>([]);

  // 加载工具清单
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/tools`);
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        const data: ToolListResponse = await res.json();
        if (cancelled) return;
        setTools(data.tools);
        if (data.tools.length > 0 && !activeName) {
          const first = data.tools.find((t) => t.category === 'retrieval') || data.tools[0];
          setActiveName(first.name);
        }
      } catch (e: any) {
        setLoadError(e.message || '加载工具失败');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const activeTool = useMemo(
    () => tools.find((t) => t.name === activeName) || null,
    [tools, activeName]
  );

  // 切换工具时用 example 填充表单
  useEffect(() => {
    if (!activeTool) return;
    const init: Record<string, any> = {};
    for (const [key, spec] of Object.entries(activeTool.args)) {
      init[key] = defaultValueForArg(spec, activeTool.example?.[key]);
    }
    setArgsState(init);
    setResponse(null);
    setShowRaw(false);
  }, [activeTool?.name]); // eslint-disable-line react-hooks/exhaustive-deps

  const groupedTools = useMemo(() => {
    const groups: Record<string, ToolMeta[]> = {};
    for (const t of tools) {
      if (!groups[t.category]) groups[t.category] = [];
      groups[t.category].push(t);
    }
    return groups;
  }, [tools]);

  const handleInvoke = async () => {
    if (!activeTool) return;
    setLoading(true);
    setResponse(null);
    try {
      const cleanedArgs: Record<string, any> = {};
      for (const [key, spec] of Object.entries(activeTool.args)) {
        const v = coerceArgValue(spec, argsState[key]);
        if (v !== undefined) cleanedArgs[key] = v;
      }
      const res = await fetch(
        `${API_BASE}/api/v1/tools/${activeTool.name}/invoke`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ args: cleanedArgs }),
        }
      );
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const data: InvokeResponse = await res.json();
      setResponse(data);
      setHistory((h) => [data, ...h].slice(0, 20));
    } catch (e: any) {
      setResponse({
        tool: activeTool.name,
        args: argsState,
        result: null,
        raw: '',
        latency_ms: 0,
        error: e.message || '调用失败',
      });
    } finally {
      setLoading(false);
    }
  };

  const renderResult = () => {
    if (!response) return null;
    if (response.error) {
      return <div className="tool-error">❌ {response.error}</div>;
    }
    const result = response.result;
    if (Array.isArray(result)) {
      return (
        <div className="tool-results">
          <div className="tool-results-meta">
            <strong>{result.length}</strong> 条结果 · {response.latency_ms} ms
          </div>
          {result.length === 0 && <div className="tool-empty">暂无匹配结果</div>}
          {result.map((item: any, i: number) => (
            <div key={i} className="tool-result-card">
              <div className="tool-result-head">
                <span className="tool-rank">#{i + 1}</span>
                {typeof item.score === 'number' && (
                  <span className="tool-score">{(item.score * 100).toFixed(1)}%</span>
                )}
              </div>
              {item.content && <div className="tool-result-body">{item.content}</div>}
              {item.title && !item.content && (
                <div className="tool-result-body">
                  <strong>{item.title}</strong>
                  {item.path && <div className="tool-result-meta">{item.path}</div>}
                </div>
              )}
              <div className="tool-result-foot">
                {Object.entries(item)
                  .filter(([k]) => !['content', 'score', 'title', 'path'].includes(k))
                  .slice(0, 4)
                  .map(([k, v]) => (
                    <span key={k} className="tool-tag">
                      {k}: {typeof v === 'object' ? JSON.stringify(v).slice(0, 30) : String(v).slice(0, 30)}
                    </span>
                  ))}
              </div>
            </div>
          ))}
        </div>
      );
    }
    return (
      <div className="tool-results">
        <div className="tool-results-meta">{response.latency_ms} ms</div>
        <pre className="tool-result-pre">
          {typeof result === 'string' ? result : JSON.stringify(result, null, 2)}
        </pre>
      </div>
    );
  };

  if (loadError) {
    return (
      <div className="toolbox-page">
        <PageHeader title="检索工具箱" subtitle="Agent 工具沙盒" />
        <div className="tool-error">加载工具失败：{loadError}</div>
      </div>
    );
  }

  return (
    <div className="toolbox-page">
      <PageHeader
        title="检索工具箱"
        subtitle={`Agent 工具沙盒 · 共 ${tools.length} 个原子能力`}
      />

      <div className="toolbox-layout">
        {/* 左：工具列表 */}
        <aside className="tool-sidebar">
          {Object.entries(groupedTools).map(([cat, list]) => (
            <div key={cat} className="tool-group">
              <div className="tool-group-title">
                {CATEGORY_LABELS[cat] || cat}
                <span className="tool-group-count">{list.length}</span>
              </div>
              {list.map((t) => (
                <button
                  key={t.name}
                  className={`tool-item ${t.name === activeName ? 'active' : ''}`}
                  onClick={() => setActiveName(t.name)}
                >
                  <span className="tool-item-name">{t.name}</span>
                  <span className="tool-item-desc">{t.description.slice(0, 28)}</span>
                </button>
              ))}
            </div>
          ))}
        </aside>

        {/* 右：执行面板 */}
        <section className="tool-panel">
          {!activeTool && <div className="tool-empty">选择左侧工具开始</div>}
          {activeTool && (
            <>
              <div className="tool-header">
                <h2>{activeTool.name}</h2>
                <span className={`tool-cat-badge cat-${activeTool.category}`}>
                  {CATEGORY_LABELS[activeTool.category] || activeTool.category}
                </span>
              </div>
              <p className="tool-desc">{activeTool.description}</p>

              <div className="tool-form">
                {Object.entries(activeTool.args).map(([key, spec]) => (
                  <div key={key} className="tool-field">
                    <label>
                      {key}
                      <span className="tool-field-type">
                        {spec.type === 'string' ? '文本' : spec.type === 'integer' ? '整数' : spec.type === 'number' ? '数值' : spec.type === 'boolean' ? '开关' : spec.type}
                        {spec.default !== undefined && ` · 默认值=${spec.default}`}
                      </span>
                    </label>
                    {spec.type === 'boolean' ? (
                      <input
                        type="checkbox"
                        checked={!!argsState[key]}
                        onChange={(e) =>
                          setArgsState({ ...argsState, [key]: e.target.checked })
                        }
                      />
                    ) : spec.type === 'integer' || spec.type === 'number' ? (
                      <input
                        type="number"
                        value={argsState[key] ?? ''}
                        onChange={(e) =>
                          setArgsState({ ...argsState, [key]: e.target.value })
                        }
                      />
                    ) : (
                      <input
                        type="text"
                        value={argsState[key] ?? ''}
                        onChange={(e) =>
                          setArgsState({ ...argsState, [key]: e.target.value })
                        }
                        onKeyDown={(e) => e.key === 'Enter' && handleInvoke()}
                      />
                    )}
                  </div>
                ))}
                <button
                  className="tool-run-btn"
                  onClick={handleInvoke}
                  disabled={loading}
                >
                  {loading ? '调用中…' : '执行'}
                </button>
              </div>

              {response && (
                <div className="tool-output">
                  <div className="tool-output-tabs">
                    <button
                      className={!showRaw ? 'active' : ''}
                      onClick={() => setShowRaw(false)}
                    >
                      结果
                    </button>
                    <button
                      className={showRaw ? 'active' : ''}
                      onClick={() => setShowRaw(true)}
                    >
                      Raw
                    </button>
                  </div>
                  {!showRaw && renderResult()}
                  {showRaw && (
                    <pre className="tool-result-pre">
                      {response.raw || JSON.stringify(response.result, null, 2)}
                    </pre>
                  )}
                </div>
              )}

              {history.length > 1 && (
                <details className="tool-history">
                  <summary>调用历史 ({history.length})</summary>
                  <ul>
                    {history.map((h, i) => (
                      <li key={i}>
                        <code>{h.tool}</code> · {h.latency_ms} ms ·{' '}
                        {h.error
                          ? `❌ ${h.error}`
                          : Array.isArray(h.result)
                          ? `${h.result.length} 条`
                          : 'ok'}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
};

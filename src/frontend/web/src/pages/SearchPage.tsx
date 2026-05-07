/**
 * 文档检索页 — Agent Toolbox 沙盒
 *
 * 不再是单一搜索框：把 retrieval-service 暴露的所有 @tool 都列出来，
 * 让用户像 agent 一样独立调用每个原子能力（向量/关键词/混合/概念/图谱/拓扑/
 * 类目/文本/PDF 页/规则条款/目录/价格查询/价格趋势/计算器/python_eval）。
 */

import { useEffect, useMemo, useState } from 'react';
import { PageHeader } from '../components/common/PageHeader';
import { getApiBaseUrl } from '../config/runtime';
import './SearchPage.css';

const API_BASE = getApiBaseUrl();

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
  const [showHelp, setShowHelp] = useState(false);

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
        actions={
          <button className="toolbox-help-btn" onClick={() => setShowHelp(true)} title="使用说明">
            📖 使用说明
          </button>
        }
      />

      {showHelp && <ToolboxHelpDrawer onClose={() => setShowHelp(false)} />}

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

// ── 使用说明 Drawer ──────────────────────────────────────────────────────
const ToolboxHelpDrawer: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  return (
    <div className="toolbox-help-overlay" onClick={onClose}>
      <aside className="toolbox-help-drawer" onClick={(e) => e.stopPropagation()}>
        <header className="toolbox-help-head">
          <h2>📖 检索工具箱使用说明</h2>
          <button className="toolbox-help-close" onClick={onClose}>✕</button>
        </header>
        <div className="toolbox-help-body">
          <section>
            <h3>这是什么？</h3>
            <p>
              本页面是 <strong>Agent 工具沙盒</strong>——RAG 系统内部 Agent
              在回答问题时调用的所有原子工具，都被独立暴露出来供你手动调用。
              想知道 Agent 是如何"思考"的？跟随它的脚步，自己点一遍即可。
            </p>
          </section>

          <section>
            <h3>工具分类速查</h3>
            <ul className="toolbox-help-cats">
              <li><strong>检索 (retrieval)</strong>：向量 / 关键词 / 混合检索 — 找文档与片段。</li>
              <li><strong>价格 (pricing)</strong>：<code>price_query</code> 单点查价、<code>price_trend</code> 时序趋势。</li>
              <li><strong>图谱 (graph)</strong>：从概念出发查关联、依赖、上下游。</li>
              <li><strong>数据 (data)</strong>：结构化表查询、目录索引、章节定位。</li>
              <li><strong>计算 (compute)</strong>：<code>calculator</code> 高精度数值计算、<code>python_eval</code> 沙盒脚本。</li>
              <li><strong>分析 (datasci)</strong>：可视化 / 数据统计。</li>
              <li><strong>主动 (proactive)</strong>：知识缺口诊断 / 追问建议。</li>
            </ul>
          </section>

          <section>
            <h3>典型用法</h3>
            <ol className="toolbox-help-cookbook">
              <li>
                <strong>找一个概念的定义</strong> →
                选 <code>vector_search</code>，<code>query</code> 填中文短语，回车执行。
              </li>
              <li>
                <strong>查某月某材料价格</strong> →
                选 <code>price_query</code>，填 <code>material_name</code> 和 <code>year_month</code>（格式 <code>YYYY-MM</code>）。
              </li>
              <li>
                <strong>查跨月价格趋势</strong> →
                选 <code>price_trend</code>，填 <code>start_month</code> / <code>end_month</code>。
                ⚠️ 系统会自动检测规格不一致并发出警告，避免误算环比。
              </li>
              <li>
                <strong>找规则条款 / 计算规则</strong> →
                选 <code>keyword_search</code> 或 <code>hybrid_search</code>，把规则关键字（如"系统调试"）放进去。
              </li>
              <li>
                <strong>跑一段 Python 计算</strong> →
                选 <code>python_eval</code>，沙盒禁网、限内存、超时 10 秒。
              </li>
            </ol>
          </section>

          <section>
            <h3>读懂结果</h3>
            <ul>
              <li>每条结果右上 <strong>百分比</strong> 是相关性分数（0–100%），越高越相关。</li>
              <li><strong>来源标记</strong>：<code>source_db</code> 标识结果来自哪个库（qdrant/postgres/elasticsearch/neo4j）。</li>
              <li>底部 <strong>历史记录</strong> 区可对比同一工具不同入参的耗时与结果数。</li>
              <li>开 <strong>原始 raw</strong> 可看 Agent 实际收到的字符串（含元数据）。</li>
            </ul>
          </section>

          <section>
            <h3>失败排查</h3>
            <ul>
              <li>结果为空 → 换近义词、放宽 <code>top_k</code>，或先用 <code>hybrid_search</code> 验证库里有相关内容。</li>
              <li>红色 ❌ → 看错误文本；常见为 PG/ES 未启动（去运维看板确认核心服务全绿）。</li>
              <li>价格类工具空结果 → 用 <code>price_db_diagnose</code> 看该材料在每个月的样本规格分布。</li>
            </ul>
          </section>
        </div>
      </aside>
    </div>
  );
};

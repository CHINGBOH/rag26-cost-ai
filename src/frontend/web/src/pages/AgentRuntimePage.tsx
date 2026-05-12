/**
 * Agent Runtime — 透视 agent 内部运行：channel / state / tool call 实时面板
 *
 * 数据来自 useRunStore（由 useAgent 的 SSE 流实时填充）。
 * 完成后的 run 自动落到 localStorage（最多 50 条），可回放。
 */

import { useEffect, useMemo, useState } from 'react';
import {
  ResponsiveContainer, LineChart, BarChart, AreaChart, ScatterChart, PieChart,
  Line, Bar, Area, Scatter, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts';
import { useAgent } from '../hooks/useAgent';
import { useRunStore } from '../stores/useRunStore';
import {
  getAgentTraces, getAgentTrace, getLearningEngine, getLearningBlindspots,
  getLearningSummary,
  AgentTraceSummary, AgentTrace, LearningEngineStatus, BlindspotCluster,
} from '../services/metricsApi';
import { AdvancedDataDrawer } from '../components/learning/AdvancedDataDrawer';
import './AgentRuntimePage.css';
import { fmtTime, fmtUnixTime } from '../utils/dateUtils';
import { AgentFlowPanel } from '../components/agent/AgentFlowPanel';
import { GuideHistoryPanel } from '../components/agent/GuideHistoryPanel';

const HISTORY_KEY = 'rag.agent.runtime.history.v1';
const HISTORY_MAX = 50;

interface RunSnapshot {
  id: string;
  query: string;
  answer: string;
  ts: number;
  durationMs: number;
  iterations: number;
  toolCalls: Array<{
    tool: string;
    args: Record<string, unknown>;
    result?: unknown;
    duration_ms?: number;
    status: string;
  }>;
  planSteps: string[];
  queryAnalysis: { intent: string; sub_queries?: string[] } | null;
  chunkCount: number;
  runtime: { provider?: string; model?: string; routeMode?: string } | null;
}

function loadHistory(): RunSnapshot[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

function saveHistory(snaps: RunSnapshot[]) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(snaps.slice(0, HISTORY_MAX)));
  } catch {
    /* noop */
  }
}

function fmtArgs(args: Record<string, unknown>): string {
  if (!args) return '{}';
  try {
    const compact = JSON.stringify(args);
    return compact.length > 280 ? compact.slice(0, 280) + '…' : compact;
  } catch {
    return String(args);
  }
}

export function AgentRuntimePage() {
  const { isLoading, sendMessage, cancelStream } = useAgent();
  const run = useRunStore();

  const [input, setInput] = useState('安装工程消耗量标准中送配电装置系统调试的计算规则是什么?');
  const [history, setHistory] = useState<RunSnapshot[]>(() => loadHistory());
  const [viewing, setViewing] = useState<RunSnapshot | null>(null);

  // 高级数据抽屉（来自学习模块）
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [engine, setEngine] = useState<LearningEngineStatus | null>(null);
  const [blindspots, setBlindspots] = useState<BlindspotCluster[]>([]);
  const [topTools, setTopTools] = useState<[string, number][]>([]);
  const [topTypes, setTopTypes] = useState<[string, number][]>([]);

  useEffect(() => {
    (async () => {
      const [eng, bs, s] = await Promise.all([
        getLearningEngine(), getLearningBlindspots(2), getLearningSummary(),
      ]);
      setEngine(eng);
      setBlindspots(bs?.clusters || []);
      setTopTools(Object.entries(s?.tool_frequency || {}).slice(0, 8) as [string, number][]);
      setTopTypes(Object.entries(s?.type_frequency || {}).sort((a, b) => b[1] - a[1]).slice(0, 6) as [string, number][]);
    })();
  }, []);

  // R9: server-side traces (persisted node trajectory)
  const [serverTraces, setServerTraces] = useState<AgentTraceSummary[]>([]);
  const [selectedTrace, setSelectedTrace] = useState<AgentTrace | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      const list = await getAgentTraces(30);
      if (alive) setServerTraces(list);
    };
    refresh();
    const t = setInterval(refresh, 5000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const handleSelectTrace = async (id: string) => {
    setTraceLoading(true);
    const t = await getAgentTrace(id);
    setSelectedTrace(t);
    setTraceLoading(false);
  };

  // 当一次 run 完成时，把当前 useRunStore 快照写入历史
  useEffect(() => {
    if (run.isStreaming) return;
    if (!run.runId) return;
    if (!run.streamingAnswer && run.toolCalls.length === 0) return;

    const exists = history.find((h) => h.id === run.runId);
    if (exists) return;

    const snap: RunSnapshot = {
      id: run.runId,
      query: input.trim(),
      answer: run.streamingAnswer,
      ts: Date.now(),
      durationMs: run.finalLatencyMs,
      iterations: run.finalIterations,
      toolCalls: run.toolCalls.map((tc) => ({
        tool: tc.tool,
        args: tc.args,
        result: tc.result,
        duration_ms: tc.duration_ms,
        status: tc.status,
      })),
      planSteps: run.planSteps,
      queryAnalysis: run.queryAnalysis
        ? { intent: run.queryAnalysis.intent, sub_queries: run.queryAnalysis.sub_queries }
        : null,
      chunkCount: run.retrievalChunks.length,
      runtime: run.runtimeInfo
        ? {
            provider: run.runtimeInfo.provider,
            model: run.runtimeInfo.model,
            routeMode: run.runtimeInfo.routeMode,
          }
        : null,
    };
    const next = [snap, ...history].slice(0, HISTORY_MAX);
    setHistory(next);
    saveHistory(next);
  }, [run.isStreaming, run.runId]);  // eslint-disable-line react-hooks/exhaustive-deps

  const live = !viewing;
  const display = viewing
    ? {
        query: viewing.query,
        answer: viewing.answer,
        toolCalls: viewing.toolCalls,
        planSteps: viewing.planSteps,
        queryAnalysis: viewing.queryAnalysis,
        chunkCount: viewing.chunkCount,
        durationMs: viewing.durationMs,
        iterations: viewing.iterations,
        runtime: viewing.runtime,
        isStreaming: false,
      }
    : {
        query: input,
        answer: run.streamingAnswer,
        toolCalls: run.toolCalls as RunSnapshot['toolCalls'],
        planSteps: run.planSteps,
        queryAnalysis: run.queryAnalysis
          ? { intent: run.queryAnalysis.intent, sub_queries: run.queryAnalysis.sub_queries }
          : null,
        chunkCount: run.retrievalChunks.length,
        durationMs: run.finalLatencyMs,
        iterations: run.finalIterations,
        runtime: run.runtimeInfo,
        isStreaming: run.isStreaming,
      };

  const channel = useMemo(
    () => ({
      query: display.query,
      query_type: display.queryAnalysis?.intent || '',
      sub_queries: display.queryAnalysis?.sub_queries || [],
      plan: display.planSteps,
      iteration: display.iterations,
      tool_calls_count: display.toolCalls.length,
      retrieved_chunks: display.chunkCount,
      runtime: display.runtime || {},
      streaming: display.isStreaming,
      answer_chars: (display.answer || '').length,
    }),
    [display],
  );

  const handleRun = () => {
    if (!input.trim() || isLoading) return;
    setViewing(null);
    sendMessage(input.trim());
  };

  const handleClearHistory = () => {
    if (!confirm('清空本地运行历史？')) return;
    setHistory([]);
    saveHistory([]);
    setViewing(null);
  };

  return (
    <div className="runtime-page">
      <AgentFlowPanel />
      <GuideHistoryPanel />
      <AdvancedDataDrawer
        open={advancedOpen}
        onClose={() => setAdvancedOpen(false)}
        blindspots={blindspots}
        topTools={topTools}
        topTypes={topTypes}
        engine={engine}
      />
      <header className="runtime-header">
        <div>
          <h1>Agent 运行时</h1>
          <p className="muted">
            实时观察智能体的共享状态·规划步骤·工具调用流程，内部运转一览无余。
          </p>
        </div>
        <div className="runtime-stats">
          <span>工具调用 {display.toolCalls.length}</span>
          <span>检索片段 {display.chunkCount}</span>
          <span>迭代 {display.iterations}</span>
          {display.durationMs > 0 && <span>{display.durationMs}ms</span>}
          <button className="runtime-advanced-btn" onClick={() => setAdvancedOpen(true)}>
            📊 高级数据
          </button>
        </div>
      </header>

      <section className="runtime-input">
        <textarea
          rows={2}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="输入问题，按 Ctrl/⌘+Enter 提交"
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') handleRun();
          }}
        />
        <div className="runtime-input-actions">
          {isLoading ? (
            <button className="btn-cancel" onClick={cancelStream}>
              中止
            </button>
          ) : (
            <button className="btn-run" onClick={handleRun} disabled={!input.trim()}>
              ▶ 运行
            </button>
          )}
          {viewing && (
            <button className="btn-back" onClick={() => setViewing(null)}>
              ← 返回实时
            </button>
          )}
        </div>
      </section>

      <div className="runtime-grid">
        {/* LEFT: history */}
        <aside className="runtime-history">
          <div className="panel-head">
            <h3>历史运行 <span className="muted">({history.length})</span></h3>
            {history.length > 0 && (
              <button className="link-danger" onClick={handleClearHistory}>清空</button>
            )}
          </div>
          {history.length === 0 ? (
            <p className="muted small">暂无历史。完成一次运行后会自动归档。</p>
          ) : (
            <ul className="history-list">
              {history.map((h) => (
                <li
                  key={h.id}
                  className={viewing?.id === h.id ? 'active' : ''}
                  onClick={() => setViewing(h)}
                >
                  <div className="hist-q">{h.query}</div>
                  <div className="hist-meta">
                    <span>{fmtTime(h.ts)}</span>
                    <span>{h.toolCalls.length} 工具</span>
                    <span>{h.iterations} 迭代</span>
                    <span>{h.durationMs}毫秒</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </aside>

        {/* CENTER: channel + tool timeline */}
        <main className="runtime-center">
          <section className="panel">
            <div className="panel-head">
              <h3>共享状态（Channel）</h3>
              {live && display.isStreaming && <span className="dot live" />}
            </div>
            <pre className="channel-box">{JSON.stringify(channel, null, 2)}</pre>
          </section>

          <section className="panel">
            <div className="panel-head">
              <h3>规划步骤（Plan）</h3>
            </div>
            {display.planSteps.length === 0 ? (
              <p className="muted small">无 plan（直答 / 简单意图 / 未到 planner 节点）。</p>
            ) : (
              <ol className="plan-list">
                {display.planSteps.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ol>
            )}
          </section>

          <section className="panel">
            <div className="panel-head">
              <h3>工具调用（Tool Calls）· {display.toolCalls.length} 次</h3>
            </div>
            {display.toolCalls.length === 0 ? (
              <p className="muted small">本次运行未调用 ReAct 工具（agent 直接走了线性管道）。</p>
            ) : (
              <ul className="tool-list">
                {display.toolCalls.map((tc, i) => (
                  <li key={i} className={`tool-card status-${tc.status}`}>
                    <div className="tool-head">
                      <span className="tool-idx">#{i + 1}</span>
                      <code className="tool-name">{tc.tool}</code>
                      <span className={`tool-status status-${tc.status}`}>{tc.status}</span>
                      {tc.duration_ms != null && (
                        <span className="muted small">{tc.duration_ms}ms</span>
                      )}
                    </div>
                    <div className="tool-args">
                      <span className="muted">args:</span>{' '}
                      <code>{fmtArgs(tc.args)}</code>
                    </div>
                    {tc.result != null && (
                      <ToolResultPreview tool={tc.tool} result={tc.result} />
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="panel">
            <div className="panel-head">
              <h3>最终答案</h3>
            </div>
            {display.answer ? (
              <pre className="answer-box">{display.answer}</pre>
            ) : (
              <p className="muted small">{display.isStreaming ? '生成中…' : '尚无答案'}</p>
            )}
          </section>

          {/* R9: Node Trajectory — server-persisted per-node version/latency/delta */}
          <section className="panel">
            <div className="panel-head">
              <h3>
                节点轨迹（Node Trajectory）
                {selectedTrace && (
                  <span className="muted small" style={{ marginLeft: 8 }}>
                    追踪 {selectedTrace.trace_id.slice(0, 8)} · {selectedTrace.nodes.length} 节点 · {selectedTrace.duration_ms ?? 0}毫秒
                  </span>
                )}
              </h3>
              {selectedTrace && (
                <button className="link-danger" onClick={() => setSelectedTrace(null)}>关闭</button>
              )}
            </div>
            {traceLoading ? (
              <p className="muted small">加载中…</p>
            ) : !selectedTrace ? (
              <p className="muted small">从下方"历史记录"选择一次运行，查看每个节点的版本号·耗时·状态变化·工具调用。</p>
            ) : (
              <ol className="plan-list" style={{ listStyle: 'none', paddingLeft: 0 }}>
                {selectedTrace.nodes.map((n) => (
                  <li key={n.version} style={{
                    border: '1px solid #e2e8f0', borderRadius: 6, padding: 8, marginBottom: 6,
                    background: n.error ? '#fef2f2' : '#fff',
                  }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <span style={{ background: '#0ea5e9', color: '#fff', padding: '1px 7px', borderRadius: 8, fontSize: 11 }}>
                        v{n.version}
                      </span>
                      <code style={{ color: '#0f172a', fontWeight: 600 }}>{n.node}</code>
                      <span className="muted small">{n.latency_ms}ms</span>
                      {n.iteration_at_entry != null && (
                        <span className="muted small">iter={n.iteration_at_entry}</span>
                      )}
                      {n.tool_calls.length > 0 && (
                        <span style={{ background: '#ede9fe', color: '#5b21b6', padding: '1px 6px', borderRadius: 6, fontSize: 11 }}>
                          {n.tool_calls.length} tool
                        </span>
                      )}
                      {n.error && <span style={{ color: '#dc2626', fontSize: 12 }}>⚠ {n.error}</span>}
                    </div>
                    {n.delta_keys.length > 0 && (
                      <div className="muted small" style={{ marginTop: 4 }}>
                        Δ {n.delta_keys.map((k) => {
                          const summary = (n.delta_summary || {})[k];
                          return (
                            <code key={k} style={{ marginRight: 6, background: '#f1f5f9', padding: '0 4px', borderRadius: 3 }}>
                              {k}{summary != null ? `=${typeof summary === 'object' ? JSON.stringify(summary) : String(summary)}` : ''}
                            </code>
                          );
                        })}
                      </div>
                    )}
                    {n.tool_calls.length > 0 && (
                      <div className="muted small" style={{ marginTop: 4 }}>
                        {n.tool_calls.map((tc, i) => (
                          <span key={i} style={{ marginRight: 8 }}>
                            🔧 <code>{tc.tool}</code>{tc.duration_ms != null ? ` (${tc.duration_ms}ms)` : ''}
                          </span>
                        ))}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </section>

          {/* R9: Server Trace History */}
          <section className="panel">
            <div className="panel-head">
              <h3>历史记录（Server Traces）<span className="muted">({serverTraces.length})</span></h3>
            </div>
            {serverTraces.length === 0 ? (
              <p className="muted small">暂无服务端持久化轨迹。运行一次 agent 即可生成。</p>
            ) : (
              <ul className="history-list" style={{ maxHeight: 320, overflowY: 'auto' }}>
                {serverTraces.map((t) => (
                  <li
                    key={t.trace_id}
                    className={selectedTrace?.trace_id === t.trace_id ? 'active' : ''}
                    onClick={() => handleSelectTrace(t.trace_id)}
                  >
                    <div className="hist-q">{t.query}</div>
                    <div className="hist-meta">
                      <span>{fmtUnixTime(t.started_ts)}</span>
                      <span>{t.node_count} 节点</span>
                      {t.iterations != null && <span>{t.iterations} 迭代</span>}
                      {t.duration_ms != null && <span>{t.duration_ms}ms</span>}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </main>
      </div>
    </div>
  );
}

/** 解析 result（可能是字符串化 JSON）→ object，失败返回 null */
function tryParseResult(result: unknown): unknown {
  if (typeof result !== 'string') return result;
  try {
    return JSON.parse(result);
  } catch {
    return null;
  }
}

/** 工具结果预览：对 R6 工具有特定渲染，否则回退到 details/pre */
const ToolResultPreview: React.FC<{ tool: string; result: unknown }> = ({ tool, result }) => {
  const parsed = tryParseResult(result);

  if (tool === 'chart_spec' && parsed && typeof parsed === 'object' && 'chart_spec' in parsed) {
    const spec = (parsed as Record<string, unknown>).chart_spec as Record<string, unknown>;
    return <InlineChart spec={spec} />;
  }

  if (tool === 'proactive_explore' && parsed && typeof parsed === 'object') {
    return <ProactiveMap data={parsed as Record<string, unknown>} />;
  }

  if ((tool === 'unit_convert' || tool === 'compare_values' || tool === 'number_stats')
      && parsed && typeof parsed === 'object') {
    return <KvBadgeList data={parsed as Record<string, unknown>} />;
  }

  return (
    <details>
      <summary>result</summary>
      <pre>{typeof result === 'string' ? result : JSON.stringify(result, null, 2)}</pre>
    </details>
  );
};

const KvBadgeList: React.FC<{ data: Record<string, unknown> }> = ({ data }) => (
  <div className="kv-badges">
    {Object.entries(data).slice(0, 10).map(([k, v]) => (
      <span key={k} className="kv-badge">
        <span className="kv-k">{k}</span>
        <span className="kv-v">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
      </span>
    ))}
  </div>
);

const ProactiveMap: React.FC<{ data: Record<string, unknown> }> = ({ data }) => {
  const concepts = (data.concepts as Array<Record<string, unknown>>) || [];
  const followups = (data.followups as string[]) || [];
  const gaps = (data.gaps as Array<Record<string, unknown> | string>) || [];
  return (
    <div className="proactive-map">
      {concepts.length === 0 && (
        <p className="muted small">无概念命中（图谱中未找到相关节点）</p>
      )}
      {concepts.map((c, idx) => (
        <div key={idx} className="proactive-concept">
          <div className="proactive-name">🧭 {String(c.concept ?? '')}</div>
          <div className="proactive-row">
            {Array.isArray(c.neighbors) && (c.neighbors as unknown[]).length > 0 && (
              <ConceptChips label="邻居" items={c.neighbors as Array<Record<string, unknown>>} />
            )}
            {Array.isArray(c.upstream) && (c.upstream as unknown[]).length > 0 && (
              <ConceptChips label="上游" items={c.upstream as Array<Record<string, unknown>>} />
            )}
            {Array.isArray(c.downstream) && (c.downstream as unknown[]).length > 0 && (
              <ConceptChips label="下游" items={c.downstream as Array<Record<string, unknown>>} />
            )}
          </div>
        </div>
      ))}
      {followups.length > 0 && (
        <div className="proactive-section">
          <span className="proactive-label">💡 追问建议</span>
          <ul className="followup-list">
            {followups.slice(0, 5).map((f, i) => <li key={i}>{f}</li>)}
          </ul>
        </div>
      )}
      {gaps.length > 0 && (
        <div className="proactive-section">
          <span className="proactive-label">⚠️ 知识缺口</span>
          <ul className="followup-list">
            {gaps.slice(0, 5).map((g, i) => (
              <li key={i}>{typeof g === 'string' ? g : JSON.stringify(g)}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

const ConceptChips: React.FC<{ label: string; items: Array<Record<string, unknown>> }> = ({ label, items }) => (
  <div className="chip-group">
    <span className="chip-label">{label}</span>
    {items.slice(0, 6).map((it, i) => (
      <span key={i} className="chip">
        {String(it.name ?? it.concept ?? it.entity ?? JSON.stringify(it))}
      </span>
    ))}
  </div>
);

const InlineChart: React.FC<{ spec: Record<string, unknown> }> = ({ spec }) => {
  const type = String(spec.type || 'line');
  const data = (spec.data as Array<Record<string, unknown>>) || [];
  const xKey = String(spec.x_key || 'x');
  const yKey = String(spec.y_key || 'y');
  const title = String(spec.title || '');

  if (data.length === 0) {
    return <p className="muted small">chart_spec: 空数据</p>;
  }

  const PIE_COLORS = ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899'];

  return (
    <div className="inline-chart">
      {title && <div className="chart-title">{title}</div>}
      <ResponsiveContainer width="100%" height={220}>
        {type === 'bar' ? (
          <BarChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
            <XAxis dataKey={xKey} tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey={yKey} fill="#3b82f6" radius={[4, 4, 0, 0]} />
          </BarChart>
        ) : type === 'pie' ? (
          <PieChart>
            <Tooltip />
            <Pie data={data} dataKey={yKey} nameKey={xKey} outerRadius={80} label>
              {data.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
            </Pie>
          </PieChart>
        ) : type === 'area' ? (
          <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
            <XAxis dataKey={xKey} tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Area type="monotone" dataKey={yKey} stroke="#10b981" fill="#10b98133" />
          </AreaChart>
        ) : type === 'scatter' ? (
          <ScatterChart margin={{ top: 8, right: 12, bottom: 4, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
            <XAxis dataKey={xKey} tick={{ fontSize: 11 }} />
            <YAxis dataKey={yKey} tick={{ fontSize: 11 }} />
            <Tooltip />
            <Scatter data={data} fill="#8b5cf6" />
          </ScatterChart>
        ) : (
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
            <XAxis dataKey={xKey} tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Line type="monotone" dataKey={yKey} stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }} />
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  );
};

export default AgentRuntimePage;

/**
 * AgentFlowPanel — Live LangGraph topology + tool registry visualization (#80).
 *
 * Reads /api/v1/agent/runtime which introspects the actual compiled graph,
 * then renders a Mermaid flowchart and a tool-list grouped by category. The
 * backend is the source of truth — no hardcoded MD diagrams to drift.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import mermaid from 'mermaid';
import { getAgentRuntime, AgentRuntime, AgentTool } from '../../services/ragApi';
import { fmtTime } from '../../utils/dateUtils';

const CATEGORY_LABELS: Record<string, { label: string; color: string }> = {
  retrieval: { label: '检索', color: '#3b82f6' },
  price: { label: '价格', color: '#f59e0b' },
  data: { label: '数据骨干', color: '#0ea5e9' },
  graph: { label: '图谱穿透', color: '#8b5cf6' },
  cognition: { label: '主动认知', color: '#ec4899' },
  stats: { label: '数据科学', color: '#10b981' },
  compute: { label: '沙箱通用', color: '#6366f1' },
  other: { label: '其它', color: '#64748b' },
};

let _mermaidInited = false;
function initMermaid() {
  if (_mermaidInited) return;
  mermaid.initialize({
    startOnLoad: false,
    theme: 'dark',
    flowchart: { curve: 'basis', padding: 12, htmlLabels: true },
    securityLevel: 'loose',
  });
  _mermaidInited = true;
}

export const AgentFlowPanel: React.FC = () => {
  const [runtime, setRuntime] = useState<AgentRuntime | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [renderedSvg, setRenderedSvg] = useState<string>('');
  const [renderError, setRenderError] = useState<string>('');
  const renderIdRef = useRef(0);

  useEffect(() => {
    initMermaid();
    let alive = true;
    const fetchOnce = async () => {
      const r = await getAgentRuntime();
      if (!alive) return;
      setRuntime(r);
      setLoaded(true);
    };
    fetchOnce();
    const t = setInterval(fetchOnce, 60000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  useEffect(() => {
    const src = runtime?.graph?.mermaid;
    if (!src) return;
    const id = `agent-flow-${++renderIdRef.current}`;
    mermaid
      .render(id, src)
      .then(({ svg }) => {
        setRenderedSvg(svg);
        setRenderError('');
      })
      .catch((e) => {
        setRenderError(String(e?.message || e));
        setRenderedSvg('');
      });
  }, [runtime?.graph?.mermaid]);

  const grouped = useMemo(() => {
    const out: Record<string, AgentTool[]> = {};
    (runtime?.tools || []).forEach((t) => {
      (out[t.category] ||= []).push(t);
    });
    return out;
  }, [runtime?.tools]);

  if (!loaded) {
    return <div style={panelStyle}><h3 style={titleStyle}>Agent 运行时拓扑</h3>
      <p style={mutedStyle}>加载中…</p></div>;
  }
  if (!runtime) {
    return <div style={panelStyle}><h3 style={titleStyle}>Agent 运行时拓扑</h3>
      <p style={mutedStyle}>无法获取 Agent 运行时信息（检索服务可能未启动）</p></div>;
  }

  const nodeCount = runtime.graph.nodes.length;
  const edgeCount = runtime.graph.edges.length;
  const condEdges = runtime.graph.edges.filter((e) => e.conditional).length;

  return (
    <div style={panelStyle}>
      <div style={headerRowStyle}>
        <div>
          <h3 style={titleStyle}>Agent 运行时拓扑（实时反射 LangGraph）</h3>
          <p style={mutedStyle}>
            {nodeCount} 个节点 · {edgeCount} 条边（{condEdges} 条条件分支） ·
            {' '}{runtime.tool_count} 个工具 · 更新于 {fmtTime(runtime.generated_at)}
          </p>
        </div>
      </div>

      {/* 拓扑图区域：可纵向拖拽调整高度 */}
      <div style={{ marginTop: 16, padding: 12, background: '#0f172a',
                    borderRadius: 8, overflow: 'auto',
                    minHeight: 200, height: 520,
                    resize: 'vertical' }}>
        {renderError ? (
          <p style={{ color: '#fca5a5' }}>渲染失败：{renderError}</p>
        ) : (
          <div
            // eslint-disable-next-line react/no-danger
            dangerouslySetInnerHTML={{ __html: renderedSvg }}
            style={{ minHeight: 200 }}
          />
        )}
      </div>

      <div style={{ marginTop: 20 }}>
        <h4 style={{ margin: '0 0 8px', color: '#e2e8f0', fontSize: 14 }}>
          工具注册表（按用途分组）
        </h4>
        <div style={{ display: 'grid', gridTemplateColumns:
                      'repeat(auto-fill, minmax(260px, 1fr))', gap: 10 }}>
          {Object.entries(grouped).map(([cat, tools]) => {
            const meta = CATEGORY_LABELS[cat] || CATEGORY_LABELS.other;
            return (
              <div key={cat} style={{
                background: '#1e293b',
                borderRadius: 8,
                padding: 10,
                borderLeft: `3px solid ${meta.color}`,
              }}>
                <div style={{ display: 'flex', alignItems: 'center',
                              justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ color: meta.color, fontWeight: 600, fontSize: 13 }}>
                    {meta.label}
                  </span>
                  <span style={{ color: '#94a3b8', fontSize: 11 }}>
                    {tools.length}
                  </span>
                </div>
                <ul style={{ margin: 0, padding: 0, listStyle: 'none' }}>
                  {tools.map((t) => (
                    <li key={t.name} style={{ fontSize: 12, color: '#cbd5e1',
                                              padding: '2px 0' }}
                        title={t.desc}>
                      <code style={{ color: '#a5f3fc' }}>{t.name}</code>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

const panelStyle: React.CSSProperties = {
  background: '#1e293b',
  border: '1px solid #334155',
  borderRadius: 10,
  padding: 16,
  marginBottom: 16,
};
const titleStyle: React.CSSProperties = {
  margin: 0, color: '#e2e8f0', fontSize: 16, fontWeight: 600,
};
const headerRowStyle: React.CSSProperties = {
  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
};
const mutedStyle: React.CSSProperties = {
  margin: '4px 0 0', color: '#94a3b8', fontSize: 12,
};

/**
 * /agents — Agent 定义浏览器
 *
 * 单一职能：浏览 .agent/agents/*.md（只读）。
 * 数据源：
 *   - 列表：GET /api/v1/agents/registry
 *   - 详情：GET /api/v1/agents/registry/{id}（raw markdown + frontmatter + mtime）
 *
 * 已删除（和 /pipeline /runtime 的重合内容）：
 *   - Task Queue（→ /pipeline）
 *   - Active Agents 实时状态/runtimeSec/taskCount（→ /runtime）
 */

import { useEffect, useMemo, useState } from 'react';
import { PageHeader } from '../components/common/PageHeader';
import { getApiBaseUrl } from '../config/runtime';
import './AgentManagePage.css';

const API_BASE = getApiBaseUrl();

interface AgentSummary {
  id: string;
  name: string;
  role: string;
  model: string;
  trigger: string;
  description: string;
  file: string;
}

interface AgentDetail {
  id: string;
  name: string;
  frontmatter: Record<string, unknown>;
  body_markdown: string;
  raw_markdown: string;
  file: string;
  path: string;
  size_bytes: number;
  modified_ts: number;
}

const HTML_ESCAPE: Record<string, string> = {
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
};
const escapeHtml = (s: string): string => String(s).replace(/[&<>"']/g, (ch) => HTML_ESCAPE[ch] || ch);

/**
 * Render trusted repo markdown to HTML. Always escape first; only whitelisted
 * tags introduced AFTER escaping remain. Source files come from .agent/agents
 * which are version-controlled and authored by maintainers, but we still treat
 * them as if untrusted to keep XSS surface minimal.
 */
function renderMd(md: string): string {
  if (!md) return '';
  let s = escapeHtml(md);

  // Fenced code blocks ```lang ... ```
  s = s.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (_m, _lang, code) => {
    return `<pre class="md-pre"><code>${code}</code></pre>`;
  });

  // Headings (must be at start of line)
  s = s.replace(/^###### (.+)$/gm, '<h6>$1</h6>')
       .replace(/^##### (.+)$/gm, '<h5>$1</h5>')
       .replace(/^#### (.+)$/gm, '<h4>$1</h4>')
       .replace(/^### (.+)$/gm, '<h3>$1</h3>')
       .replace(/^## (.+)$/gm, '<h2>$1</h2>')
       .replace(/^# (.+)$/gm, '<h1>$1</h1>');

  // List items: leading `- ` or `* ` or `1. `
  s = s.replace(/^(?:- |\* )(.+)$/gm, '<li>$1</li>')
       .replace(/^\d+\.\s(.+)$/gm, '<li>$1</li>');
  s = s.replace(/(<li>.+<\/li>(?:\n|$))+/g, (m) => `<ul class="md-ul">${m.replace(/\n/g, '')}</ul>`);

  // Inline patterns
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
       .replace(/`([^`\n]+)`/g, '<code class="md-ic">$1</code>');

  // Markdown links [text](url) — only http(s)/relative paths
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_m, text, url) => {
    const safe = /^(https?:\/\/|\/|\.\/|\.\.\/|#)/.test(url) ? url : '#';
    return `<a href="${safe}" target="_blank" rel="noopener noreferrer">${text}</a>`;
  });

  // Paragraph breaks
  s = s.replace(/\n{2,}/g, '</p><p class="md-p">');
  s = `<p class="md-p">${s}</p>`;
  // Single newlines → <br/>
  s = s.replace(/\n/g, '<br/>');
  // Cleanup empty wrappers
  s = s.replace(/<p class="md-p">\s*<\/p>/g, '');

  return s;
}

const ROLE_GROUPS: Array<{ key: string; label: string; match: (role: string) => boolean }> = [
  { key: 'orchestrator', label: '总调度', match: (r) => /orchestrat/i.test(r) },
  { key: 'reviewer',     label: '审核者', match: (r) => /(review|qa|security|inspector)/i.test(r) },
  { key: 'specialist',   label: '专项助手', match: (r) => /(specialist|planner|debugger|devops|ops)/i.test(r) },
  { key: 'worker',       label: '执行者', match: (r) => /worker|engineer/i.test(r) },
];

function groupOf(role: string): string {
  for (const g of ROLE_GROUPS) if (g.match(role)) return g.key;
  return 'worker';
}

const ROLE_ICONS: Record<string, string> = {
  orchestrator: '🎭',
  reviewer: '🔍',
  specialist: '🛠️',
  worker: '⚙️',
};

// MODEL_BADGE kept for future power-user feature
const MODEL_BADGE: Record<string, string> = {
  SONNET: 'badge-sonnet',
  HAIKU:  'badge-haiku',
  OPUS:   'badge-opus',
};
void MODEL_BADGE;

// TRIGGER_LABEL kept for future detail panel use
const TRIGGER_LABEL: Record<string, string> = {
  always_on:      '常驻',
  model_decision: '模型决定',
  on_demand:      '按需',
  manual:         '手动',
};
void TRIGGER_LABEL;

const AgentManagePage: React.FC = () => {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [agentsErr, setAgentsErr] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [groupFilter, setGroupFilter] = useState<string>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AgentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailErr, setDetailErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/api/v1/agents/registry`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        const list: AgentSummary[] = data.agents || [];
        setAgents(list);
        if (list.length > 0 && !selectedId) setSelectedId(list[0].id);
      } catch (e) {
        setAgentsErr(e instanceof Error ? e.message : '加载失败');
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    let alive = true;
    setDetailLoading(true);
    setDetailErr(null);
    setDetail(null);
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/api/v1/agents/registry/${encodeURIComponent(selectedId)}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = (await r.json()) as AgentDetail;
        if (!alive) return;
        setDetail(d);
      } catch (e) {
        if (alive) setDetailErr(e instanceof Error ? e.message : '加载失败');
      } finally {
        if (alive) setDetailLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [selectedId]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return agents.filter((a) => {
      if (groupFilter !== 'all' && groupOf(a.role) !== groupFilter) return false;
      if (!q) return true;
      return (
        a.id.toLowerCase().includes(q) ||
        a.name.toLowerCase().includes(q) ||
        a.role.toLowerCase().includes(q) ||
        a.description.toLowerCase().includes(q)
      );
    });
  }, [agents, filter, groupFilter]);

  const byGroup = useMemo(() => {
    const m: Record<string, AgentSummary[]> = {};
    for (const a of filtered) {
      const g = groupOf(a.role);
      (m[g] ||= []).push(a);
    }
    return m;
  }, [filtered]);

  const detailHtml = useMemo(
    () => (detail ? renderMd(detail.body_markdown || detail.raw_markdown || '') : ''),
    [detail]
  );

  const groupCounts = useMemo(() => {
    const c: Record<string, number> = { all: agents.length };
    for (const a of agents) {
      const g = groupOf(a.role);
      c[g] = (c[g] || 0) + 1;
    }
    return c;
  }, [agents]);

  return (
    <div className="agent-manage-page">
      <PageHeader title="AI 助手列表" subtitle="查看系统中各 AI 助手的职责与配置（只读）" />

      {agentsErr && <div className="agm-error">加载 registry 失败：{agentsErr}</div>}

      <div className="agm-toolbar">
        <input
          type="search"
          className="agm-search"
          placeholder="搜索 id / 名称 / 角色 / 描述…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <div className="agm-filter-group">
          <button
            type="button"
            className={`agm-pill ${groupFilter === 'all' ? 'active' : ''}`}
            onClick={() => setGroupFilter('all')}
          >
            全部 <span className="agm-pill-num">{groupCounts.all || 0}</span>
          </button>
          {ROLE_GROUPS.map((g) => (
            <button
              key={g.key}
              type="button"
              className={`agm-pill ${groupFilter === g.key ? 'active' : ''}`}
              onClick={() => setGroupFilter(g.key)}
            >
              {g.label} <span className="agm-pill-num">{groupCounts[g.key] || 0}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="agm-layout">
        {/* Left: icon card grid */}
        <aside className="agm-list">
          {ROLE_GROUPS.map((g) => {
            const items = byGroup[g.key];
            if (!items || items.length === 0) return null;
            return (
              <div key={g.key} className="agm-group">
                <div className="agm-group-head">{g.label} <span>{items.length}</span></div>
                <div className="agm-card-grid">
                  {items.map((a) => (
                    <button
                      key={a.id}
                      type="button"
                      className={`agm-card ${selectedId === a.id ? 'active' : ''}`}
                      onClick={() => setSelectedId(a.id)}
                      title={a.description}
                    >
                      <span className="agm-card-icon">{ROLE_ICONS[groupOf(a.role)] || '🤖'}</span>
                      <span className="agm-card-name">{a.name}</span>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
          {filtered.length === 0 && agents.length > 0 && (
            <div className="agm-empty">无匹配项</div>
          )}
          {agents.length === 0 && !agentsErr && (
            <div className="agm-empty">加载中…</div>
          )}
        </aside>

        {/* Right detail */}
        <main className="agm-detail">
          {detailLoading && <div className="agm-empty">加载详情…</div>}
          {detailErr && <div className="agm-error">详情加载失败：{detailErr}</div>}
          {detail && !detailLoading && (
            <>
              <div className="agm-detail-head">
                <div>
                  <h1>{detail.name}</h1>
                  {typeof detail.frontmatter?.description === 'string' && (
                    <p className="agm-detail-desc muted">{detail.frontmatter.description}</p>
                  )}
                </div>
              </div>

              {/* Frontmatter table — collapsible */}
              {Object.keys(detail.frontmatter || {}).length > 0 && (
                <details className="agm-fm-details">
                  <summary className="agm-fm-summary">⚙️ 配置信息（{Object.keys(detail.frontmatter).length} 项）</summary>
                  <div className="agm-fm">
                    <table>
                      <tbody>
                        {Object.entries(detail.frontmatter).map(([k, v]) => (
                          <tr key={k}>
                            <td>{k}</td>
                            <td>
                              {typeof v === 'string'
                                ? v
                                : Array.isArray(v)
                                  ? v.join(', ')
                                  : JSON.stringify(v)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              )}

              {/* Full markdown — collapsed, for power users only */}
              <details className="agm-doc-details">
                <summary className="agm-doc-summary">📄 查看完整定义文档</summary>
                <div
                  className="agm-md"
                  // eslint-disable-next-line react/no-danger
                  dangerouslySetInnerHTML={{ __html: detailHtml }}
                />
              </details>
            </>
          )}
          {!detail && !detailLoading && !detailErr && (
            <div className="agm-empty">从左侧选择一个 Agent 查看定义</div>
          )}
        </main>
      </div>
    </div>
  );
};

export default AgentManagePage;
export { AgentManagePage };

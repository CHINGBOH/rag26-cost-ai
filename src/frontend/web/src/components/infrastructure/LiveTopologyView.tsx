/**
 * LiveTopologyView — SVG-based runtime topology (no external deps).
 *
 * Renders:
 *  - User → Retrieval Service (FastAPI :8002) → Six stores (PG / Qdrant / ES / Neo4j / Redis / Milvus)
 *  - Edge color & opacity driven by /api/v1/architecture/live store.available
 *  - Click node → show details panel
 *  - Auto-refresh every 30s (shared cadence with LiveArchitecturePanel)
 *
 * Why SVG, not react-flow: keep dep tree small; topology has fixed shape (6 stores
 * + 1 retrieval node + 1 user). Static layout is more readable than auto-layout for this.
 */

import { useEffect, useMemo, useState } from 'react';
import { getLiveArchitecture, type LiveArchitecture, type LiveStoreInfo } from '../../services/ragApi';

type StoreKey = 'postgresql' | 'qdrant' | 'elasticsearch' | 'neo4j' | 'redis' | 'milvus';

const STORE_META: Record<StoreKey, { label: string; icon: string; role: string }> = {
  postgresql: { label: 'PostgreSQL', icon: '🐘', role: '结构化 + BM25 兜底' },
  qdrant:     { label: 'Qdrant',     icon: '🧭', role: '向量 (主)' },
  elasticsearch: { label: 'Elasticsearch', icon: '🔎', role: '全文 (BM25 + IK)' },
  neo4j:      { label: 'Neo4j',      icon: '🕸️', role: '知识图谱' },
  redis:      { label: 'Redis',      icon: '⚡', role: '缓存' },
  milvus:     { label: 'Milvus',     icon: '📦', role: '向量 (备)' },
};

const STORE_ORDER: StoreKey[] = ['postgresql', 'qdrant', 'elasticsearch', 'neo4j', 'redis', 'milvus'];

function statusColor(info: LiveStoreInfo | undefined): string {
  if (!info) return '#9ca3af';
  if (info.available) return '#22c55e';
  if (info.configured === false) return '#9ca3af';
  return '#ef4444';
}

function edgeStyle(info: LiveStoreInfo | undefined): { stroke: string; opacity: number; dash: string | undefined } {
  if (!info) return { stroke: '#475569', opacity: 0.4, dash: '4 4' };
  if (info.available) return { stroke: '#22c55e', opacity: 0.85, dash: undefined };
  if (info.configured === false) return { stroke: '#64748b', opacity: 0.4, dash: '4 4' };
  return { stroke: '#ef4444', opacity: 0.85, dash: '6 3' };
}

export const LiveTopologyView: React.FC = () => {
  const [data, setData] = useState<LiveArchitecture | null>(null);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<StoreKey | null>(null);
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const r = await getLiveArchitecture();
      setData(r);
      setRefreshedAt(new Date());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 30_000);
    return () => clearInterval(t);
  }, []);

  const stores = data?.stores ?? {};

  // Layout constants
  const W = 880, H = 460;
  const userX = 60, userY = 230;
  const retrievalX = 260, retrievalY = 230;
  const storeBaseX = 540;
  const storeStepY = 60;
  const storeStartY = 50;

  const storePositions = useMemo(() => {
    const pos: Record<StoreKey, { x: number; y: number }> = {} as any;
    STORE_ORDER.forEach((k, i) => {
      pos[k] = { x: storeBaseX, y: storeStartY + i * storeStepY };
    });
    return pos;
  }, []);

  const summary = data?.summary;

  return (
    <section style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 8 }}>
        <h3 style={{ margin: 0, fontSize: 16 }}>🌊 活架构拓扑 — 数据流可视化</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12, color: '#94a3b8' }}>
          {summary && (
            <span>
              {summary.available}/{summary.total} 在线 · 边的颜色由实测健康驱动
            </span>
          )}
          {refreshedAt && <span>刷新于 {refreshedAt.toLocaleTimeString()}</span>}
          <button
            onClick={refresh}
            disabled={loading}
            style={{
              padding: '4px 10px', borderRadius: 6, border: '1px solid #334155',
              background: 'transparent', color: '#e2e8f0',
              cursor: loading ? 'wait' : 'pointer', fontSize: 12,
            }}
          >
            {loading ? '探测中…' : '重新探测'}
          </button>
        </div>
      </div>

      <div style={{
        background: 'linear-gradient(180deg, #0f172a 0%, #111827 100%)',
        border: '1px solid #1f2937', borderRadius: 10, padding: 10,
        position: 'relative',
      }}>
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }} role="img" aria-label="活架构拓扑">
          <defs>
            <marker id="lt-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
            </marker>
          </defs>

          {/* User -> Retrieval edge */}
          <line x1={userX + 50} y1={userY} x2={retrievalX - 80} y2={retrievalY}
                stroke="#94a3b8" strokeWidth={1.6} markerEnd="url(#lt-arrow)" />
          <text x={(userX + 50 + retrievalX - 80) / 2} y={userY - 8} textAnchor="middle"
                fontSize="11" fill="#cbd5e1">HTTPS · query</text>

          {/* Retrieval -> Stores edges */}
          {STORE_ORDER.map((k) => {
            const p = storePositions[k];
            const st = edgeStyle(stores[k]);
            return (
              <g key={`edge-${k}`}>
                <line
                  x1={retrievalX + 80} y1={retrievalY}
                  x2={p.x - 90} y2={p.y}
                  stroke={st.stroke}
                  strokeOpacity={st.opacity}
                  strokeWidth={selected === k ? 2.6 : 1.6}
                  strokeDasharray={st.dash}
                  markerEnd="url(#lt-arrow)"
                />
              </g>
            );
          })}

          {/* User node */}
          <g transform={`translate(${userX - 40} ${userY - 28})`}>
            <rect width={80} height={56} rx={10} fill="#1e293b" stroke="#475569" />
            <text x={40} y={26} textAnchor="middle" fontSize="22">👤</text>
            <text x={40} y={48} textAnchor="middle" fontSize="11" fill="#cbd5e1">用户/前端</text>
          </g>

          {/* Retrieval Service node */}
          <g transform={`translate(${retrievalX - 80} ${retrievalY - 36})`}>
            <rect width={160} height={72} rx={10} fill="#1e293b" stroke="#3b82f6" strokeWidth={1.6} />
            <text x={80} y={26} textAnchor="middle" fontSize="13" fill="#e2e8f0" fontWeight={600}>retrieval-service</text>
            <text x={80} y={45} textAnchor="middle" fontSize="11" fill="#94a3b8">FastAPI · :8002</text>
            <text x={80} y={60} textAnchor="middle" fontSize="10" fill="#64748b">hybrid_search · agent</text>
          </g>

          {/* Store nodes */}
          {STORE_ORDER.map((k) => {
            const info = stores[k];
            const meta = STORE_META[k];
            const p = storePositions[k];
            const color = statusColor(info);
            const isSel = selected === k;
            return (
              <g
                key={`node-${k}`}
                transform={`translate(${p.x - 90} ${p.y - 22})`}
                style={{ cursor: 'pointer' }}
                onClick={() => setSelected(isSel ? null : k)}
              >
                <rect width={180} height={44} rx={8}
                      fill="#0b1220" stroke={color} strokeWidth={isSel ? 2.4 : 1.4} />
                <circle cx={14} cy={22} r={5} fill={color} />
                <text x={28} y={20} fontSize="13" fill="#e2e8f0" fontWeight={500}>
                  {meta.icon} {meta.label}
                </text>
                <text x={28} y={36} fontSize="10" fill="#94a3b8">{meta.role}</text>
              </g>
            );
          })}
        </svg>

        {/* Selection details */}
        {selected && stores[selected] && (
          <DetailPanel storeKey={selected} info={stores[selected]} onClose={() => setSelected(null)} />
        )}

        {/* Legend */}
        <div style={{
          marginTop: 8, display: 'flex', gap: 16, fontSize: 11, color: '#94a3b8', flexWrap: 'wrap',
        }}>
          <LegendDot color="#22c55e" label="在线 · 实线" />
          <LegendDot color="#ef4444" label="不可用 · 红色虚线" />
          <LegendDot color="#9ca3af" label="未配置 · 灰色虚线" />
          <span style={{ marginLeft: 'auto' }}>提示：点击存储节点查看详情</span>
        </div>
      </div>
    </section>
  );
};

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span style={{ width: 10, height: 10, borderRadius: 5, background: color, display: 'inline-block' }} />
      {label}
    </span>
  );
}

function DetailPanel({
  storeKey, info, onClose,
}: { storeKey: StoreKey; info: LiveStoreInfo; onClose: () => void }) {
  const meta = STORE_META[storeKey];
  const facts: Array<[string, string]> = [];
  if (info.version) facts.push(['版本', info.version]);
  if (info.cluster_status) facts.push(['集群状态', info.cluster_status]);
  if (typeof info.chunk_count === 'number') facts.push(['chunk 数', info.chunk_count.toLocaleString()]);
  if (typeof info.doc_count === 'number') facts.push(['索引文档', info.doc_count.toLocaleString()]);
  if (typeof (info as any).row_count === 'number') facts.push(['行数', (info as any).row_count.toLocaleString()]);
  if (typeof info.collection_count === 'number') facts.push(['集合数', String(info.collection_count)]);
  if (info.collections?.length) facts.push(['集合', info.collections.join(', ')]);
  if (info.index) facts.push(['索引名', info.index]);
  if (info.extensions?.pgvector) facts.push(['pgvector', '已启用']);
  if (info.note) facts.push(['说明', info.note]);
  if (info.error) facts.push(['错误', info.error.slice(0, 200)]);
  if (typeof (info as any).active === 'boolean') facts.push(['激活', (info as any).active ? '是' : '否（备用）']);

  return (
    <div style={{
      position: 'absolute', top: 16, right: 16, width: 280,
      background: '#0f172a', border: `1px solid ${statusColor(info)}`, borderRadius: 8,
      padding: 12, boxShadow: '0 6px 20px rgba(0,0,0,0.5)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <strong style={{ color: '#e2e8f0', fontSize: 13 }}>{meta.icon} {meta.label}</strong>
        <button onClick={onClose} style={{
          background: 'transparent', border: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: 16,
        }} aria-label="关闭">×</button>
      </div>
      <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 8 }}>{meta.role}</div>
      <table style={{ width: '100%', fontSize: 12, color: '#cbd5e1', borderCollapse: 'collapse' }}>
        <tbody>
          {facts.length === 0 ? (
            <tr><td style={{ color: '#64748b' }}>无补充信息</td></tr>
          ) : facts.map(([k, v]) => (
            <tr key={k}>
              <td style={{ padding: '3px 6px 3px 0', color: '#94a3b8', whiteSpace: 'nowrap', verticalAlign: 'top' }}>{k}</td>
              <td style={{ padding: '3px 0', wordBreak: 'break-all' }}>{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default LiveTopologyView;

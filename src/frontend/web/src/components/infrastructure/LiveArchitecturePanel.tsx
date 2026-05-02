/**
 * LiveArchitecturePanel — 真四库连通性看板（#81 / #87）
 *
 * 直接调用 /api/v1/architecture/live，每次刷新都做真实探测，不读硬编码。
 * 替代 InfrastructurePanel 中由 store 缓存的可能失真状态。
 */

import { useEffect, useState } from 'react';
import {
  getLiveArchitecture,
  type LiveArchitecture,
  type LiveStoreInfo,
} from '../../services/ragApi';

const STORE_LABELS: Record<string, string> = {
  postgresql: 'PostgreSQL',
  qdrant: 'Qdrant',
  elasticsearch: 'Elasticsearch',
  neo4j: 'Neo4j',
  redis: 'Redis',
  milvus: 'Milvus',
};

const STORE_ICONS: Record<string, string> = {
  postgresql: '🐘',
  qdrant: '🧭',
  elasticsearch: '🔎',
  neo4j: '🕸️',
  redis: '⚡',
  milvus: '📦',
};

function statusColor(s: LiveStoreInfo): string {
  if (s.available) return '#22c55e';
  if (s.configured === false) return '#9ca3af'; // not configured = neutral grey
  return '#ef4444';
}

function statusLabel(s: LiveStoreInfo): string {
  if (s.available) return '在线';
  if (s.configured === false) return '未配置';
  return '不可用';
}

function StoreCard({ name, info }: { name: string; info: LiveStoreInfo }) {
  const label = STORE_LABELS[name] ?? name;
  const icon = STORE_ICONS[name] ?? '💾';
  const color = statusColor(info);

  const facts: Array<[string, string | number]> = [];
  if (info.version) facts.push(['版本', info.version]);
  if (info.cluster_status) facts.push(['集群', info.cluster_status]);
  if (typeof info.chunk_count === 'number') facts.push(['chunk 数', info.chunk_count.toLocaleString()]);
  if (typeof info.doc_count === 'number') facts.push(['索引文档', info.doc_count.toLocaleString()]);
  if (typeof info.collection_count === 'number') facts.push(['集合数', info.collection_count]);
  if (info.collections?.length) facts.push(['集合', info.collections.join(', ')]);
  if (info.extensions?.pgvector) facts.push(['pgvector', '已启用']);
  if (info.index) facts.push(['索引', info.index]);
  if (info.note) facts.push(['说明', info.note]);
  if (info.error) facts.push(['错误', info.error.slice(0, 80)]);
  if (info.reason) facts.push(['原因', info.reason.slice(0, 80)]);

  return (
    <div
      style={{
        border: `1px solid ${color}33`,
        borderLeft: `4px solid ${color}`,
        borderRadius: 8,
        padding: '12px 14px',
        background: 'rgba(255,255,255,0.03)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <span style={{ fontWeight: 600, fontSize: 14 }}>
          {icon} {label}
        </span>
        <span
          style={{
            fontSize: 12,
            padding: '2px 8px',
            borderRadius: 999,
            background: `${color}22`,
            color,
          }}
        >
          {statusLabel(info)}
        </span>
      </div>
      {info.role && (
        <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 6 }}>{info.role}</div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 12 }}>
        {facts.map(([k, v]) => (
          <div key={k} style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: '#94a3b8' }}>{k}</span>
            <span style={{ color: '#e2e8f0', fontFamily: 'ui-monospace, monospace' }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export const LiveArchitecturePanel: React.FC = () => {
  const [data, setData] = useState<LiveArchitecture | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null);

  const refresh = async () => {
    setLoading(true);
    const r = await getLiveArchitecture();
    setData(r);
    setRefreshedAt(new Date());
    setLoading(false);
  };

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 30_000); // 每 30s 自动刷新
    return () => clearInterval(t);
  }, []);

  return (
    <section style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 16 }}>🩺 活架构 — 真四库连通性</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12, color: '#94a3b8' }}>
          {data && (
            <span>
              {data.summary.available}/{data.summary.total} 在线 · {data.summary.degraded} 未配置 · {data.summary.down} 故障
            </span>
          )}
          {refreshedAt && <span>刷新于 {refreshedAt.toLocaleTimeString()}</span>}
          <button
            onClick={refresh}
            disabled={loading}
            style={{
              padding: '4px 10px',
              borderRadius: 6,
              border: '1px solid #334155',
              background: 'transparent',
              color: '#e2e8f0',
              cursor: loading ? 'wait' : 'pointer',
              fontSize: 12,
            }}
          >
            {loading ? '探测中…' : '重新探测'}
          </button>
        </div>
      </div>
      {!data ? (
        <div style={{ fontSize: 13, color: '#94a3b8' }}>无法连接 retrieval-service /api/v1/architecture/live</div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
            gap: 12,
          }}
        >
          {Object.entries(data.stores).map(([name, info]) => (
            <StoreCard key={name} name={name} info={info} />
          ))}
        </div>
      )}
    </section>
  );
};

export default LiveArchitecturePanel;

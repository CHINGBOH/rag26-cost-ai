/**
 * /system — 系统配置 / 版本 / 真实架构 元数据看板
 *
 * 单一职能：展示 /ops（健康监控）和 /pro（实时问答）都不提供的、运维真正需要的元数据视图：
 *  1. 架构总览（来自 /api/v1/architecture/live）— 6 库实时反射
 *  2. 配置树（/api/v1/system/config）
 *  3. KB 资产（/api/v1/system/kb）
 *  4. 版本与构建（/api/v1/system/version）
 *
 * 已删除：health 卡片（→ /ops）、实时测试输入（→ /pro）。
 */

import { useEffect, useMemo, useState } from 'react';
import {
  getSystemConfig,
  getSystemKb,
  getSystemVersion,
  getArchitectureLive,
  SystemConfig,
  SystemKb,
  SystemVersion,
  ArchitectureLive,
  ArchitectureStore,
} from '../services/metricsApi';
import { PageHeader } from '../components/common/PageHeader';
import './SystemPage.css';
import { fmtUnixDateTime } from '../utils/dateUtils';

const STORE_DISPLAY: Record<string, { label: string; emoji: string }> = {
  postgresql: { label: 'PostgreSQL', emoji: '🐘' },
  postgres: { label: 'PostgreSQL', emoji: '🐘' },
  qdrant: { label: 'Qdrant', emoji: '🧭' },
  elasticsearch: { label: 'Elasticsearch', emoji: '🔎' },
  neo4j: { label: 'Neo4j', emoji: '🕸️' },
  redis: { label: 'Redis', emoji: '⚡' },
  milvus: { label: 'Milvus', emoji: '📡' },
};

function StoreCard({ name, store }: { name: string; store: ArchitectureStore }) {
  const meta = STORE_DISPLAY[name] ?? { label: name, emoji: '📦' };
  const detailRows: Array<[string, string]> = [];
  if (store.version) detailRows.push(['版本', String(store.version)]);
  if (store.role) detailRows.push(['角色', store.role]);
  if (typeof store.chunk_count === 'number') detailRows.push(['chunks', store.chunk_count.toLocaleString()]);
  if (typeof store.collection_count === 'number') detailRows.push(['collections', String(store.collection_count)]);
  if (Array.isArray(store.collections) && store.collections.length > 0) {
    detailRows.push(['集合列表', store.collections.slice(0, 4).join(', ')]);
  }
  if (store.cluster_status) detailRows.push(['集群', String(store.cluster_status)]);
  if (typeof store.nodes === 'number') detailRows.push(['节点', String(store.nodes)]);
  if (store.index) detailRows.push(['索引', String(store.index)]);
  if (typeof store.index_exists === 'boolean') detailRows.push(['索引存在', store.index_exists ? '✅' : '❌']);
  if (store.extensions) {
    const exts = Object.entries(store.extensions)
      .filter(([, v]) => v)
      .map(([k]) => k);
    if (exts.length > 0) detailRows.push(['扩展', exts.join(', ')]);
  }
  if (store.error) detailRows.push(['错误', String(store.error)]);

  return (
    <div className={`store-card ${store.available ? 'is-up' : 'is-down'}`}>
      <div className="store-card-head">
        <span className="store-emoji" aria-hidden>{meta.emoji}</span>
        <span className="store-name">{meta.label}</span>
        <span className={`store-status ${store.available ? 'up' : 'down'}`}>
          {store.available ? 'ONLINE' : 'OFFLINE'}
        </span>
      </div>
      <dl className="store-dl">
        {detailRows.length === 0 ? (
          <div className="store-empty">无元数据</div>
        ) : (
          detailRows.map(([k, v]) => (
            <div key={k} className="store-row">
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))
        )}
      </dl>
    </div>
  );
}

function ConfigGroup({ title, data }: { title: string; data: Record<string, unknown> | undefined }) {
  const [open, setOpen] = useState(true);
  if (!data || Object.keys(data).length === 0) return null;
  return (
    <div className="cfg-group">
      <button type="button" className="cfg-group-head" onClick={() => setOpen((p) => !p)}>
        <span className={`cfg-arrow ${open ? 'open' : ''}`}>▶</span>
        <span className="cfg-group-title">{title}</span>
        <span className="cfg-group-count">{Object.keys(data).length}</span>
      </button>
      {open && (
        <table className="cfg-table">
          <tbody>
            {Object.entries(data).map(([k, v]) => (
              <tr key={k}>
                <td className="cfg-k">{k}</td>
                <td className="cfg-v">
                  {typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v ?? '—')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export const SystemPage: React.FC = () => {
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const [kb, setKb] = useState<SystemKb | null>(null);
  const [version, setVersion] = useState<SystemVersion | null>(null);
  const [arch, setArch] = useState<ArchitectureLive | null>(null);
  const [archLoading, setArchLoading] = useState(false);
  const [lastArchAt, setLastArchAt] = useState<number | null>(null);

  useEffect(() => {
    (async () => {
      const [c, k, v] = await Promise.all([getSystemConfig(), getSystemKb(), getSystemVersion()]);
      setConfig(c);
      setKb(k);
      setVersion(v);
    })();
  }, []);

  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      setArchLoading(true);
      const a = await getArchitectureLive();
      if (!alive) return;
      setArch(a);
      setLastArchAt(Date.now());
      setArchLoading(false);
    };
    refresh();
    const t = setInterval(refresh, 10000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const archSummary = useMemo(() => {
    if (!arch) return null;
    const stores = Object.values(arch.stores || {});
    const up = stores.filter((s) => s.available).length;
    return { up, total: stores.length };
  }, [arch]);

  const uptimeStr = useMemo(() => {
    if (!version?.service_start_ts) return '—';
    const sec = Math.floor(Date.now() / 1000 - version.service_start_ts);
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    return `${d}d ${h}h ${m}m`;
  }, [version]);

  return (
    <div className="system-page">
      <PageHeader title="系统配置" subtitle="架构 · 配置 · KB · 版本（元数据，非健康监控）" />

      {/* 1. 架构总览 ─────────────────────────────────────── */}
      <section className="sys-section">
        <div className="sys-section-head">
          <h2>实时架构（6 库反射）</h2>
          <div className="sys-section-meta">
            {archSummary ? (
              <span className={archSummary.up === archSummary.total ? 'meta-ok' : 'meta-warn'}>
                {archSummary.up}/{archSummary.total} 在线
              </span>
            ) : null}
            <span className="meta-mute">
              {lastArchAt ? `更新于 ${new Date(lastArchAt).toLocaleTimeString()}` : ''}
              {archLoading ? '（刷新中…）' : ''}
            </span>
          </div>
        </div>
        {arch ? (
          <div className="store-grid">
            {Object.entries(arch.stores || {}).map(([name, store]) => (
              <StoreCard key={name} name={name} store={store} />
            ))}
          </div>
        ) : (
          <div className="sys-empty">加载架构数据中…（来源 /api/v1/architecture/live）</div>
        )}
      </section>

      {/* 2. 配置树 ────────────────────────────────────────── */}
      <section className="sys-section">
        <div className="sys-section-head">
          <h2>系统配置</h2>
          <div className="sys-section-meta">
            <span className="meta-mute">来源 /api/v1/system/config</span>
          </div>
        </div>
        {config ? (
          <div className="cfg-grid">
            <ConfigGroup title="LLM" data={config.llm as Record<string, unknown>} />
            <ConfigGroup title="Embedding" data={config.embedding as Record<string, unknown>} />
            <ConfigGroup title="Retrieval" data={config.retrieval as Record<string, unknown>} />
            <ConfigGroup title="Stores" data={config.stores as Record<string, unknown>} />
          </div>
        ) : (
          <div className="sys-empty">加载配置中…</div>
        )}
      </section>

      {/* 3. KB 资产 ───────────────────────────────────────── */}
      <section className="sys-section">
        <div className="sys-section-head">
          <h2>知识库资产</h2>
          <div className="sys-section-meta">
            <span className="meta-mute">
              最近写入：{kb?.latest_chunk_ts ? new Date(kb.latest_chunk_ts).toLocaleString() : '—'}
            </span>
          </div>
        </div>
        {kb ? (
          <div className="kb-stats">
            <div className="kb-stat">
              <div className="kb-num">{(kb.chunks_total ?? 0).toLocaleString()}</div>
              <div className="kb-lbl">chunks</div>
            </div>
            <div className="kb-stat">
              <div className="kb-num">{(kb.documents_total ?? 0).toLocaleString()}</div>
              <div className="kb-lbl">documents</div>
            </div>
            <div className="kb-stat">
              <div className="kb-num">{(kb.concepts_total ?? 0).toLocaleString()}</div>
              <div className="kb-lbl">concepts</div>
            </div>
            <div className="kb-stat">
              <div className="kb-num">{(kb.relations_total ?? 0).toLocaleString()}</div>
              <div className="kb-lbl">relations</div>
            </div>
            <div className="kb-stat">
              <div className="kb-num">{(kb.price_records_total ?? 0).toLocaleString()}</div>
              <div className="kb-lbl">price records</div>
            </div>
          </div>
        ) : (
          <div className="sys-empty">加载 KB 中…</div>
        )}
        {kb && kb.chunks_by_source && kb.chunks_by_source.length > 0 && (
          <table className="kb-source-table">
            <thead>
              <tr>
                <th>chunk 来源</th>
                <th style={{ textAlign: 'right' }}>数量</th>
              </tr>
            </thead>
            <tbody>
              {kb.chunks_by_source.map((row) => (
                <tr key={row.source}>
                  <td>{row.source || '(unknown)'}</td>
                  <td style={{ textAlign: 'right' }}>{row.count.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* 4. 版本 ──────────────────────────────────────────── */}
      <section className="sys-section">
        <div className="sys-section-head">
          <h2>构建与运行时</h2>
          <div className="sys-section-meta">
            <span className="meta-mute">来源 /api/v1/system/version</span>
          </div>
        </div>
        {version ? (
          <table className="ver-table">
            <tbody>
              <tr>
                <td>git commit</td>
                <td><code>{version.git_sha}</code></td>
              </tr>
              <tr>
                <td>分支</td>
                <td>{version.git_branch}</td>
              </tr>
              <tr>
                <td>Python</td>
                <td>{version.python_version}</td>
              </tr>
              <tr>
                <td>平台</td>
                <td>{version.platform}</td>
              </tr>
              <tr>
                <td>启动时间</td>
                <td>{version.service_start_ts ? fmtUnixDateTime(version.service_start_ts) : '—'}</td>
              </tr>
              <tr>
                <td>运行时长</td>
                <td>{uptimeStr}</td>
              </tr>
            </tbody>
          </table>
        ) : (
          <div className="sys-empty">加载版本中…</div>
        )}
      </section>
    </div>
  );
};

export default SystemPage;

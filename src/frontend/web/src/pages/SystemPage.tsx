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
  getLearningEngine,
  SystemConfig,
  SystemKb,
  SystemVersion,
  ArchitectureLive,
  ArchitectureStore,
  LearningEngineStatus,
} from '../services/metricsApi';
import { PageHeader } from '../components/common/PageHeader';
import { SystemDiagnosticsDrawer } from '../components/learning/SystemDiagnosticsDrawer';
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
  const detailParts: string[] = [];
  if (store.version) detailParts.push(`v${store.version}`);
  if (store.role) detailParts.push(store.role);
  if (typeof store.chunk_count === 'number') detailParts.push(`${store.chunk_count.toLocaleString()} 片段`);
  if (typeof store.collection_count === 'number') detailParts.push(`${store.collection_count} 集合`);
  if (store.cluster_status) detailParts.push(store.cluster_status);
  if (store.error) detailParts.push(`⚠ ${store.error}`);

  return (
    <div
      className={`store-icon-card ${store.available ? 'is-up' : 'is-down'}`}
      title={[meta.label, store.available ? '在线' : '离线', ...detailParts].join(' · ')}
    >
      <span className="store-ring">
        <span className="store-emoji" aria-hidden>{meta.emoji}</span>
      </span>
      <span className="store-icon-name">{meta.label}</span>
      <span className={`store-icon-dot ${store.available ? 'up' : 'down'}`} />
    </div>
  );
}

function ConfigGroup({ title, data }: { title: string; data: Record<string, unknown> | undefined }) {
  const [open, setOpen] = useState(false);
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
  const [engine, setEngine] = useState<LearningEngineStatus | null>(null);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);

  useEffect(() => {
    (async () => {
      const [c, k, v, eng] = await Promise.all([
        getSystemConfig(), getSystemKb(), getSystemVersion(), getLearningEngine(),
      ]);
      setConfig(c);
      setKb(k);
      setVersion(v);
      setEngine(eng);
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

  const driftCount = engine?.projection_drift?.total_drift_count ?? 0;

  return (
    <div className="system-page">
      <PageHeader
        title="系统配置"
        subtitle="架构 · 配置 · KB · 版本（元数据，非健康监控）"
        actions={
          <button
            className={`sys-diag-btn${driftCount > 0 ? ' has-drift' : ''}`}
            onClick={() => setDiagnosticsOpen(true)}
            title="系统自检（投影一致性、reconcile 工具）"
          >
            🔧 系统自检{driftCount > 0 ? ` (${driftCount})` : ''}
          </button>
        }
      />
      <SystemDiagnosticsDrawer
        open={diagnosticsOpen}
        onClose={() => setDiagnosticsOpen(false)}
        globalDrift={engine?.projection_drift}
        lastReconcile={engine?.last_projection_reconcile}
        onAfterReconcile={async () => { const eng = await getLearningEngine(); setEngine(eng); }}
      />

      {/* 1. 架构总览 ─────────────────────────────────────── */}
      <section className="sys-section">
        <div className="sys-section-head">
          <h2>各数据库实时状态</h2>
          <div className="sys-section-meta">
            {archSummary ? (
              <span className={archSummary.up === archSummary.total ? 'meta-ok' : 'meta-warn'}>
                {archSummary.up}/{archSummary.total} 在线
              </span>
            ) : null}
            <span className="meta-mute">
              {lastArchAt ? `更新于 ${new Date(lastArchAt).toLocaleTimeString()}` : ''}
              {archLoading ? ' 刷新中…' : ''}
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
            <span className="meta-mute">运行时配置参数</span>
          </div>
        </div>
        {config ? (
          <div className="cfg-grid">
            <ConfigGroup title="语言模型" data={config.llm as Record<string, unknown>} />
            <ConfigGroup title="向量嵌入" data={config.embedding as Record<string, unknown>} />
            <ConfigGroup title="检索配置" data={config.retrieval as Record<string, unknown>} />
            <ConfigGroup title="数据存储" data={config.stores as Record<string, unknown>} />
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
              <div className="kb-icon">🧩</div>
              <div className="kb-num">{(kb.chunks_total ?? 0).toLocaleString()}</div>
              <div className="kb-lbl">片段</div>
            </div>
            <div className="kb-stat">
              <div className="kb-icon">📄</div>
              <div className="kb-num">{(kb.documents_total ?? 0).toLocaleString()}</div>
              <div className="kb-lbl">文档</div>
            </div>
            <div className="kb-stat">
              <div className="kb-icon">💡</div>
              <div className="kb-num">{(kb.concepts_total ?? 0).toLocaleString()}</div>
              <div className="kb-lbl">概念</div>
            </div>
            <div className="kb-stat">
              <div className="kb-icon">🔗</div>
              <div className="kb-num">{(kb.relations_total ?? 0).toLocaleString()}</div>
              <div className="kb-lbl">关联</div>
            </div>
            <div className="kb-stat">
              <div className="kb-icon">💰</div>
              <div className="kb-num">{(kb.price_records_total ?? 0).toLocaleString()}</div>
              <div className="kb-lbl">价格记录</div>
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
            <span className="meta-mute">服务版本与运行信息</span>
          </div>
        </div>
        {version ? (
          <div className="ver-oneline">
            <details className="ver-detail">
              <summary className="ver-summary">
                <span className="ver-uptime">⏱ {uptimeStr}</span>
                <span className="ver-sep">·</span>
                <span title={version.git_sha ?? ''}>🌿 {version.git_branch ?? '—'}</span>
                <span className="ver-sep">·</span>
                <span>🐍 Python {version.python_version ?? '—'}</span>
                <span className="ver-sep">·</span>
                <span>{version.platform ?? '—'}</span>
              </summary>
              <div className="ver-expanded">
                <span><strong>启动：</strong>{version.service_start_ts ? fmtUnixDateTime(version.service_start_ts) : '—'}</span>
                <span><strong>提交：</strong><code>{version.git_sha?.slice(0, 8) ?? '—'}</code></span>
              </div>
            </details>
          </div>
        ) : (
          <div className="sys-empty">加载版本中…</div>
        )}
      </section>
    </div>
  );
};

export default SystemPage;

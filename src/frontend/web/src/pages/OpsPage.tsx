/**
 * 运维看板 — 服务健康 + 实时请求指标（QPS、延迟分位数）
 */

import { useState, useEffect, useRef } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import {
  getHealthDetail, getLlmMetrics, getOpsMetrics,
  getLatestSignals, getSignalsSummary, getFeedbackStats,
  HealthDetailResponse, OpsMetricsResponse, SignalAggregation, SignalSummary, FeedbackStats,
} from '../services/metricsApi';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  AreaChart, Area,
} from 'recharts';
import { PageHeader } from '../components/common/PageHeader';
import { StatusDot } from '../components/common/StatusDot';
import './OpsPage.css';
import { fmtTime } from '../utils/dateUtils';

const SERVICE_LABELS: Record<string, { label: string; port: number }> = {
  go_gateway:    { label: 'Go 网关',    port: 8080 },
  retrieval:     { label: '检索服务',    port: 8002 },
  python_legacy: { label: 'Python (旧)', port: 8000 },
  nodejs:        { label: 'Node 编排',   port: 3001 },
  ocr:           { label: 'OCR',         port: 8001 },
  llama_server:  { label: 'LLM',         port: 11434 },
  postgresql:    { label: 'PgSQL',       port: 5432 },
  qdrant:        { label: 'Qdrant',      port: 6333 },
  elasticsearch: { label: 'Elasticsearch', port: 9200 },
  neo4j:         { label: 'Neo4j',       port: 7474 },
  redis:         { label: 'Redis',       port: 6379 },
};

export const OpsPage: React.FC = () => {
  const [healthDetail, setHealthDetail] = useState<HealthDetailResponse | null>(null);
  const [llmStatus, setLlmStatus] = useState<string>('—');
  const [ops, setOps] = useState<OpsMetricsResponse | null>(null);
  const [signals, setSignals] = useState<SignalAggregation | null>(null);
  const [signalsSummary, setSignalsSummary] = useState<SignalSummary | null>(null);
  const [feedbackStats, setFeedbackStats] = useState<FeedbackStats | null>(null);
  const { isConnected } = useWebSocket('dashboard');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchAll = async () => {
    const [hd, llm, m, sig, sigSum, fb] = await Promise.allSettled([
      getHealthDetail(), getLlmMetrics(), getOpsMetrics(60),
      getLatestSignals(100), getSignalsSummary(), getFeedbackStats(100),
    ]);
    if (hd.status === 'fulfilled') setHealthDetail(hd.value);
    if (llm.status === 'fulfilled')
      setLlmStatus(llm.value.status === 'ok' ? '在线' : llm.value.message ?? '离线');
    if (m.status === 'fulfilled' && m.value) setOps(m.value);
    if (sig.status === 'fulfilled') setSignals(sig.value);
    if (sigSum.status === 'fulfilled') setSignalsSummary(sigSum.value);
    if (fb.status === 'fulfilled') setFeedbackStats(fb.value);
  };

  useEffect(() => {
    fetchAll();
    pollRef.current = setInterval(fetchAll, 5000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const getStatus = (key: string) =>
    healthDetail?.services[key] ?? { status: 'unknown' as const, latency_ms: -1 };

  // Build service list from server response (no hardcoded list).
  // Critical services first, then optional ones; falls back to defaults if no data.
  const serviceEntries = (() => {
    const services = healthDetail?.services || {};
    const keys = Object.keys(services);
    if (keys.length === 0) return Object.keys(SERVICE_LABELS).map(k => ({ key: k }));
    return keys.sort((a, b) => {
      const ca = services[a].critical ? 0 : 1;
      const cb = services[b].critical ? 0 : 1;
      if (ca !== cb) return ca - cb;
      return a.localeCompare(b);
    }).map(k => ({ key: k }));
  })();

  const latencyBarData = serviceEntries
    .map(({ key }) => {
      const svc = getStatus(key);
      const meta = SERVICE_LABELS[key] || { label: key, port: 0 };
      return {
        name: meta.label,
        latency: svc.latency_ms > 0 ? svc.latency_ms : 0,
        status: svc.status,
      };
    })
    .filter(d => d.latency > 0);

  // QPS sparkline data (1-second buckets, last 60s)
  const qpsData = (ops?.qps_buckets || []).map((v, i) => ({
    t: i - (ops?.qps_buckets?.length || 0),
    qps: v,
  }));

  return (
    <div className="ops-page">
      <PageHeader
        title="运维看板"
        subtitle="服务健康 · 实时请求指标"
        actions={
          <span className="ops-ws-badge">
            <span className={`ws-pulse ${isConnected ? 'on' : 'off'}`} />
            <span>{isConnected ? '实时连接' : '连接断开'}</span>
          </span>
        }
      />

      <div className="service-grid">
        {serviceEntries.map(({ key }) => {
          const svc = getStatus(key);
          const meta = SERVICE_LABELS[key] || { label: key, port: 0 };
          return (
            <ServiceCard
              key={key}
              label={meta.label}
              port={meta.port}
              status={svc.status}
              latency={svc.latency_ms}
              critical={(svc as any).critical}
              role={(svc as any).role}
            />
          );
        })}
      </div>

      {/* 系统资源 */}
      {healthDetail?.system && (
        <div className="ops-metrics-row">
          {healthDetail.summary && (
            <MetricCard
              label="核心服务"
              value={`${healthDetail.summary.critical_healthy}/${healthDetail.summary.critical_total}`}
              hint={
                healthDetail.summary.overall === 'ok' ? '全部就绪' :
                healthDetail.summary.overall === 'degraded' ? '部分降级' : '严重异常'
              }
              tone={
                healthDetail.summary.overall === 'ok' ? 'good' :
                healthDetail.summary.overall === 'degraded' ? 'warn' : 'bad'
              }
            />
          )}
          {healthDetail.system.load_1m !== undefined && (
            <MetricCard
              label="系统负载"
              value={healthDetail.system.load_1m.toFixed(2)}
              hint={`CPU x${healthDetail.system.cpu_count ?? '?'}`}
              tone={
                healthDetail.system.cpu_count && healthDetail.system.load_1m > healthDetail.system.cpu_count
                  ? 'warn' : undefined
              }
            />
          )}
          {healthDetail.system.mem_used_pct !== undefined && (
            <MetricCard
              label="内存使用"
              value={`${healthDetail.system.mem_used_pct}%`}
              hint={`${Math.round((healthDetail.system.mem_total_mb! - healthDetail.system.mem_available_mb!) / 1024)}G / ${Math.round(healthDetail.system.mem_total_mb! / 1024)}G`}
              tone={healthDetail.system.mem_used_pct > 85 ? 'bad' : healthDetail.system.mem_used_pct > 70 ? 'warn' : undefined}
            />
          )}
        </div>
      )}

      {/* 实时请求指标 */}
      {ops && (
        <div className="ops-metrics-row">
          <MetricCard label="每秒请求" value={ops.qps.toFixed(2)} hint={`${ops.requests} 次请求`} />
          <MetricCard label="中位延迟" value={`${ops.p50_ms} 毫秒`} />
          <MetricCard label="95%延迟" value={`${ops.p95_ms} 毫秒`} tone={ops.p95_ms > 1000 ? 'warn' : undefined} />
          <MetricCard label="99%延迟" value={`${ops.p99_ms} 毫秒`} tone={ops.p99_ms > 3000 ? 'warn' : undefined} />
          <MetricCard
            label="错误率"
            value={`${(ops.error_rate * 100).toFixed(2)}%`}
            tone={ops.error_rate > 0.05 ? 'bad' : ops.error_rate > 0.01 ? 'warn' : 'good'}
          />
        </div>
      )}

      <div className="ops-charts">
        <div className="ops-chart-card">
          <h3>请求量 · 最近 60 秒</h3>
          {qpsData.length > 0 ? (
            <ResponsiveContainer width="100%" height={180}>
              <AreaChart data={qpsData} margin={{ top: 12, right: 12, bottom: 4, left: -12 }}>
                <defs>
                  <linearGradient id="qpsGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--color-primary)" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="var(--color-primary)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
                <XAxis dataKey="t" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} />
                <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ background: 'var(--bg-elevated)', border: '1px solid var(--border-default)', borderRadius: 6, fontSize: 11 }}
                  labelFormatter={(t) => `${t}s`}
                />
                <Area type="monotone" dataKey="qps" stroke="var(--color-primary)" fill="url(#qpsGrad)" strokeWidth={1.5} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <p className="ops-empty">无请求数据</p>
          )}
        </div>

        <div className="ops-chart-card">
          <h3>服务延迟</h3>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={latencyBarData} margin={{ top: 12, right: 12, bottom: 4, left: -12 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
              <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
              <Tooltip contentStyle={{ background: 'var(--bg-elevated)', border: '1px solid var(--border-default)', borderRadius: 6, fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="latency" name="延迟 (ms)" fill="var(--color-primary)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {ops && ops.top_paths.length > 0 && (
        <div className="ops-paths-card">
          <h3>请求量 TOP 路径 (60s)</h3>
          <ul className="paths-list">
            {ops.top_paths.map((p) => (
              <li key={p.path}>
                <code className="path-name">{p.path}</code>
                <span className="path-count">{p.count}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="ops-info-row">
        <div className="ops-info-card">
          <span className="ops-info-label">LLM 服务</span>
          <span className="ops-info-value">{llmStatus}</span>
        </div>
        <div className="ops-info-card">
          <span className="ops-info-label">最后刷新</span>
          <span className="ops-info-value">
            {healthDetail?.timestamp ? fmtTime(healthDetail.timestamp) : '—'}
          </span>
        </div>
      </div>

      {/* 信号监控（来自学习模块） */}
      {signalsSummary && (
        <details className="ops-signals-section">
          <summary className="ops-signals-summary">
            <span>📡 信号监控</span>
            <span className={`ops-signals-health ops-signals-health--${signalsSummary.health_status}`}>
              {signalsSummary.health_status === 'good' ? '✅ 正常' : signalsSummary.health_status === 'warning' ? '⚠️ 注意' : '🚨 告警'}
            </span>
            <span className="ops-muted">展开看采集统计</span>
          </summary>
          <div className="ops-signals-grid">
            {([
              ['用户反馈', signalsSummary.signal_counts.feedback],
              ['失败信号', signalsSummary.signal_counts.failures],
              ['重复问题', signalsSummary.signal_counts.repeats],
              ['合约违规', signalsSummary.signal_counts.violations],
              ['拓扑异常', signalsSummary.signal_counts.topo],
            ] as [string, number][]).map(([label, count]) => (
              <div key={label} className="ops-signal-chip">
                <span className="ops-signal-count">{count}</span>
                <span className="ops-signal-label">{label}</span>
              </div>
            ))}
          </div>
          {signals && (
            <div className="ops-severity-row">
              <span className="ops-muted">严重度指数</span>
              <div className="ops-severity-bar">
                <div className="ops-severity-fill" style={{ width: `${Math.min(signals.severity_score, 100)}%` }} />
              </div>
              <span className="ops-severity-value">{signals.severity_score.toFixed(1)}/100</span>
            </div>
          )}
        </details>
      )}

      {/* 反馈统计（来自学习模块） */}
      {feedbackStats && (feedbackStats.summary.total > 0) && (
        <details className="ops-signals-section">
          <summary className="ops-signals-summary">
            <span>💬 用户反馈统计</span>
            <span className="ops-muted">展开查看分布</span>
          </summary>
          <div className="ops-signals-grid">
            <div className="ops-signal-chip">
              <span className="ops-signal-count">{feedbackStats.summary.positive}</span>
              <span className="ops-signal-label">点赞</span>
            </div>
            <div className="ops-signal-chip">
              <span className="ops-signal-count">{feedbackStats.summary.negative}</span>
              <span className="ops-signal-label">差评</span>
            </div>
            <div className="ops-signal-chip">
              <span className="ops-signal-count">{feedbackStats.summary.total}</span>
              <span className="ops-signal-label">合计</span>
            </div>
          </div>
        </details>
      )}
    </div>
  );
};

interface MetricCardProps { label: string; value: string; hint?: string; tone?: 'good' | 'warn' | 'bad' }
const MetricCard: React.FC<MetricCardProps> = ({ label, value, hint, tone }) => (
  <div className={`ops-metric-card ${tone || ''}`}>
    <div className="ops-metric-label">{label}</div>
    <div className="ops-metric-value">{value}</div>
    {hint && <div className="ops-metric-hint">{hint}</div>}
  </div>
);

interface ServiceCardProps {
  label: string;
  port: number;
  status: string;
  latency: number;
  critical?: boolean;
  role?: string;
}

const ServiceCard: React.FC<ServiceCardProps> = ({ label, port, status, latency, critical, role }) => {
  const klass =
    status === 'healthy' ? 'healthy' :
    status === 'degraded' ? 'degraded' :
    status === 'not_running' ? 'not-running' :
    status === 'unknown' ? 'unknown' : 'unhealthy';
  const statusLabel =
    status === 'healthy' ? '正常' :
    status === 'degraded' ? '降级' :
    status === 'not_running' ? '未启用' :
    status === 'unknown' ? '未知' : '异常';
  return (
    <div className={`svc-card ${klass}`} title={role || ''}>
      <div className="svc-card-top">
        <StatusDot status={status} />
        <span className="svc-port">:{port}</span>
        {critical === false && <span className="svc-optional-tag">可选</span>}
      </div>
      <div className="svc-name">{label}</div>
      {role && <div className="svc-role">{role}</div>}
      <div className="svc-meta">
        <span className={`svc-status-label ${klass}`}>{statusLabel}</span>
        {latency > 0 && <span className="svc-latency">{latency}ms</span>}
      </div>
    </div>
  );
};


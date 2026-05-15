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
import './OpsPage.css';
import { fmtTime } from '../utils/dateUtils';
// 后端英文 key → 中文标签/图标的集中翻译层，组件不内联硬编码
import { SVC_ICONS, SERVICE_LABELS, translateStatus, statusClass } from '../locales/services';

export const OpsPage: React.FC = () => {
  const [healthDetail, setHealthDetail] = useState<HealthDetailResponse | null>(null);
  const [, setLlmStatus] = useState<string>('—');
  const [ops, setOps] = useState<OpsMetricsResponse | null>(null);
  const [, setSignals] = useState<SignalAggregation | null>(null);
  const [, setSignalsSummary] = useState<SignalSummary | null>(null);
  const [, setFeedbackStats] = useState<FeedbackStats | null>(null);
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

      <div className="svc-strip">
        {serviceEntries.map(({ key }) => {
          const svc = getStatus(key);
          const meta = SERVICE_LABELS[key] || { label: key, port: 0 };
          // 后端返回英文 status → locale 层统一翻译为中文和 CSS 类名
          const klass   = statusClass(svc.status);
          const statusTip = translateStatus(svc.status);
          return (
            <div key={key} className={`svc-chip ${klass}`}
              title={`${meta.label}${svc.latency_ms > 0 ? ' · ' + svc.latency_ms + '毫秒' : ''} · ${statusTip}`}>
              <span className="svc-chip-icon">{SVC_ICONS[key] || '⬡'}</span>
              <span className="svc-chip-name">{meta.label}</span>
              <span className="svc-chip-dot" />
            </div>
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

      {/* 实时请求指标 — 技术细节折叠 */}
      {ops && (
        <details className="ops-metrics-details">
          <summary className="ops-metrics-summary">
            📊 性能指标
            <span className="ops-metrics-peek">
              {ops.error_rate > 0.01
                ? <span className="tone-bad">错误率 {(ops.error_rate * 100).toFixed(1)}%</span>
                : <span className="tone-good">错误率正常</span>}
              · {ops.qps.toFixed(1)} QPS
            </span>
          </summary>
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
        </details>
      )}

      <details className="ops-accordion">
        <summary className="ops-accordion-sum">📊 图表 <span className="ops-acc-hint">请求量 · 服务延迟 · 热门接口</span></summary>
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
              <Bar dataKey="latency" name="延迟（毫秒）" fill="var(--color-primary)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {ops && ops.top_paths.length > 0 && (
          <div className="ops-paths-card">
            <ul className="paths-list">
              {ops.top_paths.slice(0, 5).map((p) => (
                <li key={p.path}>
                  <code className="path-name">{p.path}</code>
                  <span className="path-count">{p.count}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </details>

      {/* 底部状态栏 — 只保留连接状态和更新时间 */}
      <div className="ops-footer-bar">
        <span className="ops-footer-ws">
          <span className={`ws-pulse ${isConnected ? 'on' : 'off'}`} />
          {isConnected ? '实时' : '断线'}
        </span>
        <span className="ops-footer-sep">·</span>
        <span className="ops-footer-time">
          {healthDetail?.timestamp ? `更新 ${fmtTime(healthDetail.timestamp)}` : '—'}
        </span>
      </div>
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



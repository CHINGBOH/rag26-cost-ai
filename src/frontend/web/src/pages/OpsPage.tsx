/**
 * 运维看板 — 服务健康 + 实时请求指标（QPS、延迟分位数）
 */

import { useState, useEffect, useRef } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import {
  getHealthDetail, getLlmMetrics, getOpsMetrics,
  HealthDetailResponse, OpsMetricsResponse,
} from '../services/metricsApi';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  AreaChart, Area,
} from 'recharts';
import { PageHeader } from '../components/common/PageHeader';
import { StatusDot } from '../components/common/StatusDot';
import './OpsPage.css';
import { fmtTime } from '../utils/dateUtils';

interface ServiceDef {
  name: string;
  label: string;
  port: number;
  key: string;
}

const SERVICES: ServiceDef[] = [
  { name: 'Go Gateway',    label: 'Go 网关',    port: 8080, key: 'go_gateway' },
  { name: 'Python Legacy', label: 'Python',      port: 8000, key: 'python_legacy' },
  { name: 'Retrieval',     label: '检索服务',    port: 8002, key: 'retrieval' },
  { name: 'LLM 推理',      label: 'LLM',         port: 11434, key: 'llama_server' },
  { name: 'OCR',           label: 'OCR',         port: 8001, key: 'ocr' },
  { name: 'PostgreSQL',    label: 'PgSQL',       port: 5432, key: 'postgresql' },
  { name: 'Qdrant',        label: 'Qdrant',      port: 6333, key: 'qdrant' },
];

export const OpsPage: React.FC = () => {
  const [healthDetail, setHealthDetail] = useState<HealthDetailResponse | null>(null);
  const [llmStatus, setLlmStatus] = useState<string>('—');
  const [ops, setOps] = useState<OpsMetricsResponse | null>(null);
  const { isConnected } = useWebSocket('dashboard');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchAll = async () => {
    const [hd, llm, m] = await Promise.allSettled([getHealthDetail(), getLlmMetrics(), getOpsMetrics(60)]);
    if (hd.status === 'fulfilled') setHealthDetail(hd.value);
    if (llm.status === 'fulfilled')
      setLlmStatus(llm.value.status === 'ok' ? '在线' : llm.value.message ?? '离线');
    if (m.status === 'fulfilled' && m.value) setOps(m.value);
  };

  useEffect(() => {
    fetchAll();
    pollRef.current = setInterval(fetchAll, 5000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const getStatus = (key: string) =>
    healthDetail?.services[key] ?? { status: 'unknown', latency_ms: -1 };

  const latencyBarData = SERVICES.map((s) => {
    const svc = getStatus(s.key);
    return {
      name: s.label,
      latency: svc.latency_ms > 0 ? svc.latency_ms : 0,
      status: svc.status,
    };
  });

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
        {SERVICES.map((s) => {
          const svc = getStatus(s.key);
          return (
            <ServiceCard
              key={s.key}
              label={s.label}
              port={s.port}
              status={svc.status}
              latency={svc.latency_ms}
            />
          );
        })}
      </div>

      {/* 实时请求指标 */}
      {ops && (
        <div className="ops-metrics-row">
          <MetricCard label="QPS (60s)" value={ops.qps.toFixed(2)} hint={`${ops.requests} 请求`} />
          <MetricCard label="P50 延迟" value={`${ops.p50_ms} ms`} />
          <MetricCard label="P95 延迟" value={`${ops.p95_ms} ms`} tone={ops.p95_ms > 1000 ? 'warn' : undefined} />
          <MetricCard label="P99 延迟" value={`${ops.p99_ms} ms`} tone={ops.p99_ms > 3000 ? 'warn' : undefined} />
          <MetricCard
            label="错误率"
            value={`${(ops.error_rate * 100).toFixed(2)}%`}
            tone={ops.error_rate > 0.05 ? 'bad' : ops.error_rate > 0.01 ? 'warn' : 'good'}
          />
        </div>
      )}

      <div className="ops-charts">
        <div className="ops-chart-card">
          <h3>QPS · 最近 60 秒</h3>
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
            {healthDetail?.timestamp
              ? fmtTime(healthDetail.timestamp)
              : '—'}
          </span>
        </div>
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

interface ServiceCardProps {
  label: string;
  port: number;
  status: string;
  latency: number;
}

const ServiceCard: React.FC<ServiceCardProps> = ({ label, port, status, latency }) => {
  const klass =
    status === 'healthy' ? 'healthy' : status === 'degraded' ? 'degraded' : 'unhealthy';
  const statusLabel =
    status === 'healthy' ? '正常' : status === 'degraded' ? '降级' : status === 'unknown' ? '未知' : '异常';
  return (
    <div className={`svc-card ${klass}`}>
      <div className="svc-card-top">
        <StatusDot status={status} />
        <span className="svc-port">:{port}</span>
      </div>
      <div className="svc-name">{label}</div>
      <div className="svc-meta">
        <span className={`svc-status-label ${klass}`}>{statusLabel}</span>
        {latency > 0 && <span className="svc-latency">{latency}ms</span>}
      </div>
    </div>
  );
};


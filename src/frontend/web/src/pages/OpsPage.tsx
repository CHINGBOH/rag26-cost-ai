/**
 * Ops Dashboard — service health grid + metrics charts
 */

import { useState, useEffect, useRef } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { getHealthDetail, getLlmMetrics, HealthDetailResponse } from '../services/metricsApi';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Legend,
} from 'recharts';
import './OpsPage.css';

/* ── Service definitions ─────────────────────────────── */

interface ServiceDef {
  name: string;
  label: string;
  port: number;
  key: string;
}

const SERVICES: ServiceDef[] = [
  { name: 'Go Gateway', label: 'Go GW', port: 8090, key: 'go_gateway' },
  { name: 'Python Legacy', label: 'Python', port: 8000, key: 'python_legacy' },
  { name: 'Retrieval', label: 'Retrieval', port: 8002, key: 'retrieval' },
  { name: 'llama-server', label: 'LLM', port: 8080, key: 'llama_server' },
  { name: 'OCR', label: 'OCR', port: 8001, key: 'ocr' },
  { name: 'PostgreSQL', label: 'PgSQL', port: 5432, key: 'postgresql' },
  { name: 'Qdrant', label: 'Qdrant', port: 6333, key: 'qdrant' },
  { name: 'Node.js', label: 'Node', port: 3001, key: 'nodejs' },
];

/* ── Mock QPS time series ────────────────────────────── */

function generateQpsData() {
  const now = Date.now();
  return Array.from({ length: 20 }, (_, i) => ({
    time: new Date(now - (19 - i) * 15000).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }),
    qps: Math.max(0, Math.round(Math.random() * 8 + 2)),
  }));
}

/* ── Component ───────────────────────────────────────── */

export const OpsPage: React.FC = () => {
  const [healthDetail, setHealthDetail] = useState<HealthDetailResponse | null>(null);
  const [llmStatus, setLlmStatus] = useState<string>('—');
  const [qpsData, setQpsData] = useState(generateQpsData());
  const { isConnected } = useWebSocket('dashboard');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchAll = async () => {
    const [hd, llm] = await Promise.allSettled([getHealthDetail(), getLlmMetrics()]);
    if (hd.status === 'fulfilled') setHealthDetail(hd.value);
    if (llm.status === 'fulfilled')
      setLlmStatus(llm.value.status === 'ok' ? '在线' : llm.value.message ?? '离线');
  };

  useEffect(() => {
    fetchAll();
    pollRef.current = setInterval(() => {
      fetchAll();
      setQpsData((prev) => [
        ...prev.slice(1),
        {
          time: new Date().toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
          }),
          qps: Math.max(0, Math.round(Math.random() * 8 + 2)),
        },
      ]);
    }, 5000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const getStatus = (key: string): { status: string; latency_ms: number } => {
    return healthDetail?.services[key] ?? { status: 'unknown', latency_ms: -1 };
  };

  const latencyBarData = SERVICES.map((s) => {
    const svc = getStatus(s.key);
    return {
      name: s.label,
      latency: svc.latency_ms > 0 ? svc.latency_ms : 0,
      status: svc.status,
    };
  });

  return (
    <div className="ops-page">
      <div className="ops-header">
        <h1>运维看板</h1>
        <div className="ops-ws-badge">
          WS: <span className={isConnected ? 'ws-ok' : 'ws-off'}>{isConnected ? '已连接' : '断开'}</span>
        </div>
      </div>

      {/* Service health grid */}
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

      {/* Charts row */}
      <div className="ops-charts">
        <div className="ops-chart-card">
          <h3>QPS（实时，15s 采样）</h3>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={qpsData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
              <XAxis dataKey="time" tick={{ fontSize: 10 }} interval={4} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Line
                type="monotone"
                dataKey="qps"
                stroke="var(--color-primary)"
                dot={false}
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="ops-chart-card">
          <h3>服务延迟（ms）</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={latencyBarData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
              <XAxis dataKey="name" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="latency" name="延迟(ms)" fill="var(--color-primary)" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* LLM status */}
      <div className="ops-info-row">
        <div className="ops-info-card">
          <span className="ops-info-label">LLM 服务</span>
          <span className="ops-info-value">{llmStatus}</span>
        </div>
        <div className="ops-info-card">
          <span className="ops-info-label">最后刷新</span>
          <span className="ops-info-value">
            {healthDetail?.timestamp
              ? new Date(healthDetail.timestamp).toLocaleTimeString('zh-CN')
              : '—'}
          </span>
        </div>
      </div>
    </div>
  );
};

/* ── Service Card ────────────────────────────────────── */

interface ServiceCardProps {
  label: string;
  port: number;
  status: string;
  latency: number;
}

const ServiceCard: React.FC<ServiceCardProps> = ({ label, port, status, latency }) => {
  const statusClass =
    status === 'healthy' ? 'healthy' : status === 'degraded' ? 'degraded' : 'unhealthy';
  const statusIcon = statusClass === 'healthy' ? '🟢' : statusClass === 'degraded' ? '🟡' : '🔴';

  return (
    <div className={`svc-card ${statusClass}`}>
      <div className="svc-icon">{statusIcon}</div>
      <div className="svc-name">{label}</div>
      <div className="svc-port">:{port}</div>
      <div className={`svc-status-label ${statusClass}`}>{status}</div>
      {latency > 0 && <div className="svc-latency">{latency}ms</div>}
    </div>
  );
};

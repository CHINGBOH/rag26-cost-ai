/**
 * 运维看板 — 服务健康网格 + 真实延迟柱状图
 * QPS 折线已移除：缺少真实指标接口，不再 mock random
 */

import { useState, useEffect, useRef } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { getHealthDetail, getLlmMetrics, HealthDetailResponse } from '../services/metricsApi';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { PageHeader } from '../components/common/PageHeader';
import { StatusDot } from '../components/common/StatusDot';
import './OpsPage.css';

interface ServiceDef {
  name: string;
  label: string;
  port: number;
  key: string;
}

const SERVICES: ServiceDef[] = [
  { name: 'Go Gateway',    label: 'Go GW',    port: 8090, key: 'go_gateway' },
  { name: 'Python Legacy', label: 'Python',   port: 8000, key: 'python_legacy' },
  { name: 'Retrieval',     label: 'Retrieval',port: 8002, key: 'retrieval' },
  { name: 'llama-server',  label: 'LLM',      port: 8080, key: 'llama_server' },
  { name: 'OCR',           label: 'OCR',      port: 8001, key: 'ocr' },
  { name: 'PostgreSQL',    label: 'PgSQL',    port: 5432, key: 'postgresql' },
  { name: 'Qdrant',        label: 'Qdrant',   port: 6333, key: 'qdrant' },
];

export const OpsPage: React.FC = () => {
  const [healthDetail, setHealthDetail] = useState<HealthDetailResponse | null>(null);
  const [llmStatus, setLlmStatus] = useState<string>('—');
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

  return (
    <div className="ops-page">
      <PageHeader
        title="运维看板"
        subtitle="服务健康与延迟监控"
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

      <div className="ops-charts">
        <div className="ops-chart-card">
          <h3>服务延迟</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={latencyBarData} margin={{ top: 12, right: 12, bottom: 4, left: -12 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
              <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
              <Tooltip
                contentStyle={{
                  background: 'var(--bg-elevated)',
                  border: '1px solid var(--border-default)',
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar
                dataKey="latency"
                name="延迟 (ms)"
                fill="var(--color-primary)"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

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

interface ServiceCardProps {
  label: string;
  port: number;
  status: string;
  latency: number;
}

const ServiceCard: React.FC<ServiceCardProps> = ({ label, port, status, latency }) => {
  const klass =
    status === 'healthy' ? 'healthy' : status === 'degraded' ? 'degraded' : 'unhealthy';
  return (
    <div className={`svc-card ${klass}`}>
      <div className="svc-card-top">
        <StatusDot status={status} />
        <span className="svc-port">:{port}</span>
      </div>
      <div className="svc-name">{label}</div>
      <div className="svc-meta">
        <span className={`svc-status-label ${klass}`}>{status}</span>
        {latency > 0 && <span className="svc-latency">{latency}ms</span>}
      </div>
    </div>
  );
};

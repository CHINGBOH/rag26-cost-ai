/**
 * 系统看板 — RAG Agent 运行状态 + 实时测试
 */

import { useState, useEffect, useCallback } from 'react';
import { checkHealth, askAgent, HealthResponse } from '../services/agentApi';
import { getSystemConfig, getSystemKb, getSystemVersion, SystemConfig, SystemKb, SystemVersion } from '../services/metricsApi';
import { PageHeader } from '../components/common/PageHeader';
import { StatusDot } from '../components/common/StatusDot';
import './SystemPage.css';
import { fmtDateTime, fmtUnixDateTime } from '../utils/dateUtils';

interface TestRecord {
  id: number;
  query: string;
  passed: boolean;
  confidence: number;
  iterations: number;
  chunks: number;
  latencyMs: number;
  timestamp: number;
}

const SERVICE_LABELS: Record<string, string> = {
  postgres: 'PostgreSQL',
  postgresql: 'PostgreSQL',
  qdrant: 'Qdrant',
  cache: '缓存',
  redis: 'Redis',
};

export const SystemPage: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const [kb, setKb] = useState<SystemKb | null>(null);
  const [version, setVersion] = useState<SystemVersion | null>(null);
  const [testQuery, setTestQuery] = useState('');
  const [testRecords, setTestRecords] = useState<TestRecord[]>([]);
  const [testing, setTesting] = useState(false);
  const [maxIterations, setMaxIterations] = useState(3);

  useEffect(() => {
    const fetch = async () => {
      try { setHealth(await checkHealth()); } catch {}
    };
    fetch();
    const t = setInterval(fetch, 15000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    (async () => {
      const [c, k, v] = await Promise.all([getSystemConfig(), getSystemKb(), getSystemVersion()]);
      setConfig(c); setKb(k); setVersion(v);
    })();
    const t = setInterval(async () => { setKb(await getSystemKb()); }, 30000);
    return () => clearInterval(t);
  }, []);

  const stats = (() => {
    if (testRecords.length === 0) return null;
    const passed = testRecords.filter((r) => r.passed).length;
    const avgConf = testRecords.reduce((s, r) => s + r.confidence, 0) / testRecords.length;
    const avgIter = testRecords.reduce((s, r) => s + r.iterations, 0) / testRecords.length;
    const avgLatency = testRecords.reduce((s, r) => s + r.latencyMs, 0) / testRecords.length;
    return {
      passRate: ((passed / testRecords.length) * 100).toFixed(0),
      avgConfidence: avgConf.toFixed(2),
      avgIterations: avgIter.toFixed(1),
      avgLatency: (avgLatency / 1000).toFixed(1),
      total: testRecords.length,
    };
  })();

  const runTest = useCallback(async () => {
    if (!testQuery.trim() || testing) return;
    setTesting(true);
    const start = Date.now();
    const q = testQuery.trim();

    try {
      const res = await askAgent(q, { maxIterations });
      setTestRecords((prev) => [{
        id: Date.now(),
        query: q,
        passed: res.evaluation?.passed ?? false,
        confidence: res.evaluation?.confidence ?? 0,
        iterations: res.iterations ?? 1,
        chunks: res.chunks?.length ?? 0,
        latencyMs: Date.now() - start,
        timestamp: Date.now(),
      }, ...prev]);
    } catch {
      setTestRecords((prev) => [{
        id: Date.now(),
        query: q,
        passed: false,
        confidence: 0,
        iterations: 0,
        chunks: 0,
        latencyMs: Date.now() - start,
        timestamp: Date.now(),
      }, ...prev]);
    } finally {
      setTesting(false);
      setTestQuery('');
    }
  }, [testQuery, testing, maxIterations]);

  return (
    <div className="system-page">
      <PageHeader title="系统看板" subtitle="RAG Agent 运行状态与实时测试" />

      <div className="system-grid">
        <div className="sys-card">
          <h2>知识库连通性</h2>
          {health ? (
            <div className="sys-health-list">
              {Object.entries(health.services || {}).map(([k, v]) => (
                <div key={k} className="sys-health-row">
                  <StatusDot status={String(v)} />
                  <span className="sys-health-name">{SERVICE_LABELS[k] || k}</span>
                  <span className="sys-health-val">{String(v)}</span>
                </div>
              ))}
              <div className="sys-health-overall">
                整体 <strong>{health.status}</strong>
              </div>
            </div>
          ) : (
            <p className="loading-text">连接中…</p>
          )}
        </div>

        <div className="sys-card">
          <h2>知识库统计</h2>
          {kb ? (
            <div className="sys-stats-grid">
              <div className="stat-item"><div className="stat-value">{kb.documents_total ?? '—'}</div><div className="stat-label">文档</div></div>
              <div className="stat-item"><div className="stat-value">{kb.chunks_total ?? '—'}</div><div className="stat-label">Chunks</div></div>
              <div className="stat-item"><div className="stat-value">{kb.concepts_total ?? '—'}</div><div className="stat-label">概念/目录</div></div>
              <div className="stat-item"><div className="stat-value">{kb.price_records_total ?? '—'}</div><div className="stat-label">价格记录</div></div>
            </div>
          ) : <p className="loading-text">加载中…</p>}
          {kb?.latest_chunk_ts && (
            <p className="empty-hint" style={{ marginTop: 8 }}>
              最近入库：{fmtDateTime(kb.latest_chunk_ts)}
            </p>
          )}
        </div>

        <div className="sys-card">
          <h2>运行时配置</h2>
          {config ? (
            <div className="sys-health-list">
              <div className="sys-health-row"><span className="sys-health-name">LLM 模型</span><span className="sys-health-val">{config.llm.provider} / {config.llm.model}</span></div>
              <div className="sys-health-row"><span className="sys-health-name">向量模型</span><span className="sys-health-val">{config.embedding.model} ({config.embedding.dim}维)</span></div>
              <div className="sys-health-row"><span className="sys-health-name">Top-K</span><span className="sys-health-val">{config.retrieval.default_top_k} · 阈值 {config.retrieval.score_threshold}</span></div>
              <div className="sys-health-row"><span className="sys-health-name">最大迭代</span><span className="sys-health-val">{config.retrieval.max_iterations}</span></div>
            </div>
          ) : <p className="loading-text">加载中…</p>}
        </div>

        <div className="sys-card">
          <h2>Agent 概览</h2>
          {stats ? (
            <div className="sys-stats-grid">
              <div className="stat-item">
                <div className="stat-value">{stats.passRate}%</div>
                <div className="stat-label">通过率（{stats.total} 次）</div>
              </div>
              <div className="stat-item">
                <div className="stat-value">{stats.avgConfidence}</div>
                <div className="stat-label">平均置信度</div>
              </div>
              <div className="stat-item">
                <div className="stat-value">{stats.avgIterations}</div>
                <div className="stat-label">平均迭代轮数</div>
              </div>
              <div className="stat-item">
                <div className="stat-value">{stats.avgLatency}s</div>
                <div className="stat-label">平均耗时</div>
              </div>
            </div>
          ) : (
            <p className="empty-hint">运行测试后显示统计指标</p>
          )}
        </div>
      </div>

      <div className="sys-card full-width">
        <h2>实时测试</h2>
        <div className="test-bar">
          <input
            className="test-input"
            value={testQuery}
            onChange={(e) => setTestQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && runTest()}
            placeholder="输入测试查询…"
            disabled={testing}
          />
          <button className="test-btn" onClick={runTest} disabled={testing || !testQuery.trim()}>
            {testing ? '测试中…' : '测试'}
          </button>
          {testRecords.length > 0 && (
            <button className="clear-records-btn" onClick={() => setTestRecords([])}>
              清除记录
            </button>
          )}
        </div>

        {testRecords.length > 0 && (
          <div className="test-records">
            {testRecords.map((r, i) => (
              <div key={r.id} className={`test-record ${r.passed ? 'passed' : 'failed'}`}>
                <span className="record-num">#{testRecords.length - i}</span>
                <span className={`record-status ${r.passed ? 'pass' : 'fail'}`}>
                  {r.passed ? '通过' : '未通过'}
                </span>
                <span className="record-query">
                  {r.query.slice(0, 40)}{r.query.length > 40 ? '…' : ''}
                </span>
                <span className="record-meta">
                  conf {r.confidence.toFixed(2)} · iter {r.iterations} · chunks {r.chunks} ·
                  {' '}{(r.latencyMs / 1000).toFixed(1)}s
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="sys-card full-width">
        <h2>Agent 参数</h2>
        <div className="param-row">
          <label className="param-label">最大迭代次数</label>
          <input
            type="range"
            min={1}
            max={5}
            value={maxIterations}
            onChange={(e) => setMaxIterations(Number(e.target.value))}
            className="param-slider"
          />
          <span className="param-value">{maxIterations}</span>
          <span className="param-hint">Agent 最大 ReAct 轮次（调整后在上方测试区验证效果）</span>
        </div>
      </div>

      {version && (
        <div className="sys-card full-width" style={{ fontSize: 12, opacity: 0.75 }}>
          <span>版本 <code>{version.git_sha}</code> · 分支 <code>{version.git_branch}</code> · Python {version.python_version} · 启动 {fmtUnixDateTime(version.service_start_ts)}</span>
        </div>
      )}
    </div>
  );
};

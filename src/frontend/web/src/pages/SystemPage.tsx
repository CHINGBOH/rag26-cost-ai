/**
 * 系统看板 — RAG Agent 运行状态 + 实时测试
 */

import { useState, useEffect, useCallback } from 'react';
import { checkHealth, askAgent, HealthResponse } from '../services/agentApi';
import { PageHeader } from '../components/common/PageHeader';
import { StatusDot } from '../components/common/StatusDot';
import './SystemPage.css';

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
          <label className="param-label">max_iterations</label>
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
    </div>
  );
};

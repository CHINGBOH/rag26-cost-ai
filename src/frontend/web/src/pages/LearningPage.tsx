/**
 * 自学习看板 (#138) — 普通用户视图
 * 只展示三件事：系统状态、需要你批准的、最近做好了什么
 */

import React, { useEffect, useState, useRef } from 'react';
import {
  getLearningDashboard,
  getImprovementHistory,
  approveFix,
  rejectFix,
  LearningDashboard,
  LearningDashboardTrend,
  ImprovementEvent,
} from '../services/metricsApi';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import './LearningPage.css';

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

function timeAgo(ts: number | null | undefined): string {
  if (!ts) return '从未';
  const diff = Date.now() - (ts > 1e12 ? ts : ts * 1000);
  const m = Math.floor(diff / 60000);
  if (m < 1) return '刚刚';
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.floor(h / 24)} 天前`;
}

function deltaLabel(delta: number): string {
  if (!delta) return '';
  const pct = Math.round(delta * 100);
  return pct > 0 ? `提升了 ${pct}%` : `下降了 ${Math.abs(pct)}%`;
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export const LearningPage: React.FC = () => {
  const [dashboard, setDashboard] = useState<LearningDashboard | null>(null);
  const [events, setEvents] = useState<ImprovementEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [rejectInput, setRejectInput] = useState<Record<number, string>>({});
  const [acting, setActing] = useState<number | null>(null);

  const refresh = async () => {
    setLoading(true);
    const [dash, hist] = await Promise.all([
      getLearningDashboard(),
      getImprovementHistory(30),
    ]);
    setDashboard(dash);
    setEvents(hist.events ?? []);
    setLoading(false);
  };

  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  useEffect(() => {
    const t = setInterval(() => refreshRef.current(), 30000);
    return () => clearInterval(t);
  }, []);

  const pending = events.filter((e) => e.status === 'pending_review');
  const done = events.filter((e) => ['verified', 'applied', 'rejected', 'reverted'].includes(e.status));

  const health = dashboard?.health;
  const trend = dashboard?.improvement_trend ?? [];
  const alerts = dashboard?.alerts ?? [];
  const lastRun = dashboard?.key_metrics?.last_run;

  const handleApprove = async (id: number) => {
    setActing(id);
    await approveFix(id);
    await refresh();
    setActing(null);
  };

  const handleReject = async (id: number) => {
    setActing(id);
    await rejectFix(id, rejectInput[id] || '用户拒绝');
    await refresh();
    setActing(null);
  };

  // ── 渲染 ────────────────────────────────────────────────────────────────────
  return (
    <div className="lp-page">

      {/* ① 顶部状态横幅 */}
      <StatusBanner health={health} lastRun={lastRun} alerts={alerts} loading={loading} onRefresh={refresh} />

      {/* ② 趋势图 */}
      {trend.length > 0 && <TrendCard trend={trend} />}

      {/* ③ 等你拍板 */}
      <section className="lp-section">
        <h2 className="lp-section-title">
          {pending.length > 0
            ? `📋 有 ${pending.length} 条改进建议需要你来拍板`
            : '✅ 目前没有需要你决定的事'}
        </h2>
        {pending.length > 0 && (
          <div className="lp-cards">
            {pending.map((e) => (
              <div key={e.event_id} className="lp-review-card">
                <p className="lp-review-desc">
                  {e.action || '系统检测到可以改进的地方，想做一次调整'}
                </p>
                {e.delta > 0 && (
                  <p className="lp-review-impact">
                    预计能让答题准确率 <strong className="lp-good">{deltaLabel(e.delta)}</strong>
                  </p>
                )}
                <div className="lp-review-actions">
                  <button
                    className="lp-btn-approve"
                    disabled={acting === e.event_id}
                    onClick={() => handleApprove(e.event_id)}
                  >
                    {acting === e.event_id ? '处理中…' : '👍 同意，让它去做'}
                  </button>
                  <div className="lp-reject-row">
                    <input
                      className="lp-reject-input"
                      placeholder="不同意的原因（可不填）"
                      value={rejectInput[e.event_id] ?? ''}
                      onChange={(ev) => setRejectInput((p) => ({ ...p, [e.event_id]: ev.target.value }))}
                    />
                    <button
                      className="lp-btn-reject"
                      disabled={acting === e.event_id}
                      onClick={() => handleReject(e.event_id)}
                    >
                      不用了
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ④ 最近做好的事（折叠） */}
      {done.length > 0 && (
        <details className="lp-section lp-history">
          <summary className="lp-history-summary">
            🕐 最近做好的事（{done.length} 条）
          </summary>
          <ol className="lp-timeline">
            {done.slice(0, 20).map((e) => (
              <li key={e.event_id} className={`lp-tl-item lp-tl-${e.status}`}>
                <span className="lp-tl-dot" />
                <div className="lp-tl-body">
                  <span className="lp-tl-status">{STATUS_EMOJI[e.status] ?? '📝'}</span>
                  <span className="lp-tl-text">
                    {e.action || '系统做了一次调整'}
                    {e.delta > 0 && <span className="lp-tl-delta">&nbsp;· {deltaLabel(e.delta)}</span>}
                  </span>
                  <span className="lp-tl-time">{timeAgo(e.timestamp)}</span>
                </div>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
};

// ─── 子组件 ───────────────────────────────────────────────────────────────────

const STATUS_EMOJI: Record<string, string> = {
  verified: '✅', applied: '📝', rejected: '🚫', reverted: '↩️', failed: '❌',
};

interface StatusBannerProps {
  health: LearningDashboard['health'] | undefined;
  lastRun: number | null | undefined;
  alerts: LearningDashboard['alerts'];
  loading: boolean;
  onRefresh: () => void;
}

const StatusBanner: React.FC<StatusBannerProps> = ({ health, lastRun, alerts, loading, onRefresh }) => {
  const status = health?.status;
  const cfg = {
    good:     { emoji: '😊', text: '系统状态良好，正常运转中', cls: 'lp-banner--good' },
    warning:  { emoji: '🤔', text: '系统有点状况，正在处理', cls: 'lp-banner--warn' },
    critical: { emoji: '😣', text: '系统遇到了困难，需要关注', cls: 'lp-banner--bad' },
  }[status ?? 'good'] ?? { emoji: '⏳', text: '加载中…', cls: '' };

  return (
    <div className={`lp-banner ${cfg.cls}`}>
      <span className="lp-banner-emoji">{cfg.emoji}</span>
      <div className="lp-banner-body">
        <p className="lp-banner-title">{cfg.text}</p>
        {lastRun && (
          <p className="lp-banner-sub">上次自我检查：{timeAgo(lastRun)}</p>
        )}
        {alerts.filter((a) => !a.acknowledged).map((a, i) => (
          <p key={i} className={`lp-banner-alert lp-banner-alert--${a.severity}`}>
            {a.severity === 'critical' ? '🚨' : '⚠️'} {a.message}
          </p>
        ))}
      </div>
      <button className="lp-refresh" onClick={onRefresh} disabled={loading}>
        {loading ? '…' : '刷新'}
      </button>
    </div>
  );
};

const TrendCard: React.FC<{ trend: LearningDashboardTrend[] }> = ({ trend }) => {
  const latest = trend[trend.length - 1]?.rate ?? 0;
  const earliest = trend[0]?.rate ?? 0;
  const improved = latest > earliest;

  return (
    <section className="lp-section lp-trend-card">
      <div className="lp-trend-header">
        <div>
          <h2 className="lp-section-title">📈 答题准确率趋势</h2>
          <p className="lp-trend-sub">
            近 {trend.length} 天·当前
            <strong className={improved ? ' lp-good' : ' lp-bad'}> {Math.round(latest * 100)}%</strong>
            {improved
              ? `，比最初提升了 ${Math.round((latest - earliest) * 100)}%`
              : latest < earliest
              ? `，比最初下降了 ${Math.round((earliest - latest) * 100)}%`
              : '，保持稳定'}
          </p>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={trend} margin={{ top: 8, right: 16, bottom: 4, left: -16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
          <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
          <YAxis
            tickFormatter={(v) => `${Math.round(v * 100)}%`}
            domain={[0, 1]}
            tick={{ fontSize: 11, fill: 'var(--text-muted)' }}
          />
          <Tooltip
            formatter={(v: number) => [`${Math.round(v * 100)}%`, '准确率']}
            contentStyle={{ fontSize: 12, borderRadius: 6 }}
          />
          <Line
            type="monotone"
            dataKey="rate"
            stroke="var(--color-primary, #3b82f6)"
            strokeWidth={2}
            dot={{ r: 3 }}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </section>
  );
};

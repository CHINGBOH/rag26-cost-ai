/**
 * 学习看板 (#133 重构) — 三标签：概览 / 异常诊断 / 改进记录
 * 去技术化：术语黑名单已应用，Drift 折叠到系统自检
 */

import React, { useEffect, useState, useRef } from 'react';
import {
  getLearningDashboard,
  getImprovementHistory,
  getLearningEngine,
  getDetectedProblems,
  getFeedbackStats,
  getConversations,
  getLatestSignals,
  getSignalsSummary,
  approveFix,
  rejectFix,
  LearningDashboard,
  LearningDashboardTrend,
  ImprovementEvent,
  LearningEngineStatus,
  ProblemReport,
  FeedbackStats,
  ConversationTurn,
  SignalAggregation,
  SignalSummary,
} from '../services/metricsApi';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import './LearningPage.css';
import { translateAlert, translateAction } from '../locales/learning';
import { IssuesTab } from './learning/IssuesTab';
import { ImprovementsTab } from './learning/ImprovementsTab';

// ─── 标签定义 ─────────────────────────────────────────────────────────────────
type TabKey = 'overview' | 'issues' | 'history';
const TABS: { key: TabKey; label: string; emoji: string }[] = [
  { key: 'overview', label: '系统概览', emoji: '📊' },
  { key: 'issues', label: '异常诊断', emoji: '🔍' },
  { key: 'history', label: '改进记录', emoji: '📋' },
];

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

// ─── 主页面：3 标签 + 数据驱动 ───────────────────────────────────────────────

export const LearningPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const [dashboard, setDashboard] = useState<LearningDashboard | null>(null);
  const [events, setEvents] = useState<ImprovementEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [rejectInput, setRejectInput] = useState<Record<number, string>>({});
  const [acting, setActing] = useState<number | null>(null);

  // 标签所需附加数据
  const [engine, setEngine] = useState<LearningEngineStatus | null>(null);
  const [signals, setSignals] = useState<SignalAggregation | null>(null);
  const [signalsSummary, setSignalsSummary] = useState<SignalSummary | null>(null);
  const [problems, setProblems] = useState<ProblemReport[]>([]);
  const [conversations, setConversations] = useState<ConversationTurn[]>([]);
  const [feedbackStats, setFeedbackStats] = useState<FeedbackStats | null>(null);
  const [qualityFilter, setQualityFilter] = useState<string>('all');
  const [historySummary, setHistorySummary] = useState<any>(null);

  // ── 数据加载（核心 8 次 API 调用）─────────────────────────────────────
  const refresh = async () => {
    setLoading(true);
    // 第1批：核心数据（所有标签共用）
    const [dash, hist, eng] = await Promise.all([
      getLearningDashboard(),         // API #1: 仪表盘
      getImprovementHistory(30),      // API #2: 改进历史
      getLearningEngine(),            // API #3: 引擎状态（供 drift 自检）
    ]);
    setDashboard(dash);
    setEvents(hist.events ?? []);
    setHistorySummary(hist.summary ?? null);
    setEngine(eng);

    // 第2批：概览标签额外数据 + 异常标签数据
    const [sig, sigSum, probs, fbStats] = await Promise.all([
      getLatestSignals(100),          // API #4: 信号
      getSignalsSummary(),            // API #5: 信号摘要
      getDetectedProblems(undefined, 50), // API #6: 问题
      getFeedbackStats(100),          // API #7: 反馈统计
    ]);
    setSignals(sig);
    setSignalsSummary(sigSum);
    setProblems(probs.problems ?? []);
    setFeedbackStats(fbStats);

    // 第3批：对话记录
    const convs = await getConversations(50); // API #8: 对话
    setConversations(convs);

    setLoading(false);
  };

  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  useEffect(() => {
    const t = setInterval(() => refreshRef.current(), 30000);
    return () => clearInterval(t);
  }, []);

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

  // ── 渲染 ────────────────────────────────────────────────────────────────
  return (
    <div className="lp-page">
      {/* 顶部状态横幅（所有标签共用） */}
      <StatusBanner
        health={dashboard?.health}
        lastRun={dashboard?.key_metrics?.last_run}
        alerts={dashboard?.alerts ?? []}
        loading={loading}
        onRefresh={refresh}
      />

      {/* 三标签导航 */}
      <nav className="lp-tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`lp-tab ${activeTab === t.key ? 'active' : ''}`}
            onClick={() => setActiveTab(t.key)}
          >
            <span className="lp-tab-emoji">{t.emoji}</span>
            <span>{t.label}</span>
          </button>
        ))}
      </nav>

      {/* 标签内容 */}
      <div className="lp-tab-content">
        {activeTab === 'overview' && (
          <OverviewTab
            dashboard={dashboard}
            engine={engine}
            events={events}
            acting={acting}
            rejectInput={rejectInput}
            onApprove={handleApprove}
            onReject={handleReject}
            setRejectInput={setRejectInput}
          />
        )}

        {activeTab === 'issues' && (
          <IssuesTab
            problems={problems}
            interactionRuns={[]}
            learningLoopRuns={[]}
            conversations={conversations}
            feedbackStats={feedbackStats}
            filter={qualityFilter as any}
            onFilterChange={setQualityFilter as any}
          />
        )}

        {activeTab === 'history' && (
          <ImprovementsTab
            historyEvents={events}
            historySummary={historySummary}
            onApprove={handleApprove}
            onReject={handleReject}
          />
        )}
      </div>
    </div>
  );
};

// ─── 概览 Tab ─────────────────────────────────────────────────────────────────

interface OverviewTabProps {
  dashboard: LearningDashboard | null;
  engine: LearningEngineStatus | null;
  events: ImprovementEvent[];
  acting: number | null;
  rejectInput: Record<number, string>;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
  setRejectInput: React.Dispatch<React.SetStateAction<Record<number, string>>>;
}

const OverviewTab: React.FC<OverviewTabProps> = ({
  dashboard, engine, events, acting, rejectInput, onApprove, onReject, setRejectInput,
}) => {
  const trend = dashboard?.improvement_trend ?? [];
  const pending = events.filter((e) => e.status === 'pending_review');
  const done = events.filter((e) =>
    ['verified', 'applied', 'rejected', 'reverted'].includes(e.status),
  );
  const driftCount = engine?.projection_drift?.total_drift_count ?? 0;

  return (
    <>
      {/* KPI 小卡片 */}
      <div className="lp-kpi-row">
        <div className={`lp-kpi ${(dashboard?.health?.score ?? 100) >= 70 ? 'good' : 'warn'}`}>
          <span className="lp-kpi-num">{dashboard?.health?.score ?? '—'}</span>
          <span className="lp-kpi-label">健康评分</span>
        </div>
        <div className="lp-kpi">
          <span className="lp-kpi-num">{pending.length}</span>
          <span className="lp-kpi-label">待处理建议</span>
        </div>
        <div className="lp-kpi">
          <span className="lp-kpi-num">{done.length}</span>
          <span className="lp-kpi-label">已完成操作</span>
        </div>
        <div className={`lp-kpi ${driftCount > 0 ? 'warn' : 'good'}`}>
          <span className="lp-kpi-num">{driftCount}</span>
          <span className="lp-kpi-label">数据同步偏差</span>
        </div>
      </div>

      {/* 趋势图 */}
      {trend.length > 0 && <TrendCard trend={trend} />}

      {/* 系统自检（Drift 折叠到这里） */}
      {engine && (
        <details className="lp-selfcheck">
          <summary className="lp-selfcheck-summary">
            🔧 系统自检
            {driftCount > 0 && <span className="lp-selfcheck-badge">{driftCount}</span>}
            <span className="lp-selfcheck-hint">
              上次检查：{timeAgo(engine.last_run?.ts as number ?? null)}
            </span>
          </summary>
          <div className="lp-selfcheck-body">
            <div className="lp-selfcheck-row">
              <span className="lp-selfcheck-label">运行模式</span>
              <span>{engine.trigger_description ?? '—'}</span>
            </div>
            <div className="lp-selfcheck-row">
              <span className="lp-selfcheck-label">近24h异常运行</span>
              <span className={engine.signals_24h?.weak_or_failed_runs > 0 ? 'lp-warn' : ''}>
                {engine.signals_24h?.weak_or_failed_runs ?? 0} 次
              </span>
            </div>
            <div className="lp-selfcheck-row">
              <span className="lp-selfcheck-label">近24h差评反馈</span>
              <span className={engine.signals_24h?.pending_negative_feedback_with_text > 0 ? 'lp-warn' : ''}>
                {engine.signals_24h?.pending_negative_feedback_with_text ?? 0} 条
              </span>
            </div>
            {driftCount > 0 && (
              <div className="lp-selfcheck-drift">
                ⚠️ 检测到 {driftCount} 处数据同步偏差，建议到系统配置页运行全局修复。
              </div>
            )}
          </div>
        </details>
      )}

      {/* 等待你拍板 */}
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
                <p className="lp-review-desc">{translateAction(e.action)}</p>
                {e.delta > 0 && (
                  <p className="lp-review-impact">
                    预计能让答题准确率 <strong className="lp-good">{deltaLabel(e.delta)}</strong>
                  </p>
                )}
                <div className="lp-review-actions">
                  <button
                    className="lp-btn-approve"
                    disabled={acting === e.event_id}
                    onClick={() => onApprove(e.event_id)}
                  >
                    {acting === e.event_id ? '处理中…' : '👍 同意，让它去做'}
                  </button>
                  <div className="lp-reject-row">
                    <input
                      className="lp-reject-input"
                      placeholder="不同意的原因（可不填）"
                      value={rejectInput[e.event_id] ?? ''}
                      onChange={(ev) =>
                        setRejectInput((p) => ({ ...p, [e.event_id]: ev.target.value }))
                      }
                    />
                    <button
                      className="lp-btn-reject"
                      disabled={acting === e.event_id}
                      onClick={() => onReject(e.event_id)}
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

      {/* 最近做好的事（折叠） */}
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
                    {translateAction(e.action)}
                    {e.delta > 0 && <span className="lp-tl-delta">&nbsp;· {deltaLabel(e.delta)}</span>}
                  </span>
                  <span className="lp-tl-time">{timeAgo(e.timestamp)}</span>
                </div>
              </li>
            ))}
          </ol>
        </details>
      )}
    </>
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
    good:     { emoji: '😊', text: '一切正常，系统运转良好', cls: 'lp-banner--good' },
    warning:  { emoji: '🤔', text: '有些小问题，系统正在自动修复', cls: 'lp-banner--warn' },
    critical: { emoji: '😣', text: '遇到了一些困难，建议关注一下', cls: 'lp-banner--bad' },
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
            {a.severity === 'critical' ? '🚨' : '⚠️'} {translateAlert(a.message)}
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

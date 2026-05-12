/**
 * 自学习看板 (#138)
 * 精简为无 Tab 的线性页面：KPI → 系统状态 → 问题列表 → 知识缺口 → 改进记录
 *
 * 搬出去的功能：
 *   信号监控 / 交互统计  → OpsPage
 *   系统自检抽屉         → SystemPage
 *   高级数据抽屉         → AgentRuntimePage
 */

import React, { useEffect, useState, useRef } from 'react';
import { PageHeader } from '../components/common/PageHeader';
import {
  getLearningSummary,
  getLearningDashboard,
  getLearningGapWorkbench,
  getLearningEngine,
  getDetectedProblems,
  getImprovementHistory,
  triageGaps,
  retestGap,
  transitionGap,
  approveFix,
  rejectFix,
  LearningSummary,
  LearningDashboard,
  LearningGapWorkbench,
  LearningGapWorkbenchItem,
  LearningEngineStatus,
  ImprovementEvent,
} from '../services/metricsApi';
import { DashboardPanel } from '../components/learning/DashboardPanel';
import { ProblemsPanel } from '../components/learning/ProblemsPanel';
import { ReviewsPanel } from '../components/learning/ReviewsPanel';
import { ImprovementHistoryPanel } from '../components/learning/ImprovementHistoryPanel';
import './LearningPage.css';
import { fmtDateTime } from '../utils/dateUtils';
import {
  QUALITY_ZH,
  OUTCOME_FAMILY_ZH,
  GAP_SCOPE_ZH,
  CAUSE_TYPE_ZH,
  GAP_ACTION_ZH,
  GAP_BUCKETS,
  renderGapStatusBadge,
} from './learning-i18n';

export const LearningPage: React.FC = () => {
  const [summary, setSummary] = useState<LearningSummary | null>(null);
  const [dashboard, setDashboard] = useState<LearningDashboard | null>(null);
  const [gapWorkbench, setGapWorkbench] = useState<LearningGapWorkbench | null>(null);
  const [engine, setEngine] = useState<LearningEngineStatus | null>(null);
  const [problems, setProblems] = useState<any[]>([]);
  const [historyEvents, setHistoryEvents] = useState<ImprovementEvent[]>([]);
  const [historySummary, setHistorySummary] = useState<any>(null);
  const [triagePending, setTriagePending] = useState(false);
  const [triageNote, setTriageNote] = useState<string | null>(null);
  const [retestingGaps, setRetestingGaps] = useState<Set<string>>(new Set());
  const [transitioning, setTransitioning] = useState<Set<string>>(new Set());
  const [liveRetestOn, setLiveRetestOn] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    const [s, dash, gapWb, eng, probData, histData] = await Promise.all([
      getLearningSummary(),
      getLearningDashboard(),
      getLearningGapWorkbench(200, false),
      getLearningEngine(),
      getDetectedProblems(),
      getImprovementHistory(30),
    ]);
    setSummary(s);
    setDashboard(dash);
    setGapWorkbench(gapWb);
    setEngine(eng);
    setProblems(probData.problems);
    setHistoryEvents(histData.events);
    setHistorySummary(histData.summary);
    setLoading(false);
  };

  const handleTriageAll = async (liveRetest: boolean) => {
    setTriagePending(true);
    setTriageNote(null);
    const result = await triageGaps({ liveRetest, maxLiveRetests: 5, dryRun: false });
    if (!result) {
      setTriageNote('分类请求失败，请检查 retrieval-service 日志。');
    } else {
      const parts = Object.entries(result.counts)
        .filter(([, v]) => v > 0)
        .map(([k, v]) => `${k}:${v}`)
        .join(' · ');
      setTriageNote(
        `处理 ${result.processed} 条，实时复测 ${result.live_retests_used} 次。` +
          (parts ? ` 分类：${parts}` : ''),
      );
      await getLearningGapWorkbench().then((d) => d && setGapWorkbench(d));
    }
    setTriagePending(false);
  };

  const handleRetestGap = async (gapKey: string) => {
    setRetestingGaps((prev) => new Set([...prev, gapKey]));
    const result = await retestGap(gapKey);
    if (result) {
      const wb = await getLearningGapWorkbench();
      if (wb) setGapWorkbench(wb);
    }
    setRetestingGaps((prev) => {
      const next = new Set(prev);
      next.delete(gapKey);
      return next;
    });
  };

  const handleTransitionGap = async (gapKey: string, action: string) => {
    const key = `${gapKey}:${action}`;
    setTransitioning((prev) => new Set([...prev, key]));
    await transitionGap(gapKey, action);
    const wb = await getLearningGapWorkbench();
    if (wb) setGapWorkbench(wb);
    setTransitioning((prev) => {
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
  };

  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  useEffect(() => {
    const t = setInterval(() => refreshRef.current(), 30000);
    return () => clearInterval(t);
  }, []);

  // ── 派生数据 ──────────────────────────────────────────
  const qual = summary?.by_quality || { good: 0, weak: 0, failure: 0 };
  const total = summary?.total_runs || 0;
  const errorCount = (qual.weak || 0) + (qual.failure || 0);
  const errorRate = total > 0 ? Math.round((errorCount / total) * 100) : 0;

  const gapCounts = gapWorkbench?.counts ?? { total: 0, active: 0, observing: 0, blocked: 0, resolved: 0, by_status: {} };
  const unresolvedGapCount = (gapCounts.active ?? 0) + (gapCounts.observing ?? 0);
  const observingCount = gapCounts.observing ?? 0;
  const pendingReviewCount = historyEvents.filter((e) => e.status === 'pending_review').length;

  const listenerLastRunTs = engine?.last_run?.ts;
  const listenerStaleMinutes = (() => {
    if (!listenerLastRunTs) return null;
    const ts = typeof listenerLastRunTs === 'string' ? Date.parse(listenerLastRunTs) : Number(listenerLastRunTs);
    if (!Number.isFinite(ts)) return null;
    return Math.floor((Date.now() - ts) / 60000);
  })();
  const listenerStale = listenerStaleMinutes !== null && listenerStaleMinutes > 15;

  const healthStatus = dashboard?.health.status;
  const healthTone: 'good' | 'warn' | 'bad' | undefined =
    healthStatus === 'good' ? 'good' : healthStatus === 'warning' ? 'warn' : healthStatus === 'critical' ? 'bad' : undefined;

  const feedbackPositive = summary?.feedback.positive ?? 0;
  const feedbackNegative = summary?.feedback.negative ?? 0;
  const feedbackTotal = summary?.feedback.total ?? 0;

  // ── Gap 单项渲染 ──────────────────────────────────────
  const renderGapItem = (item: LearningGapWorkbenchItem, index: number) => {
    const g = item.gap;
    const latestEvidence = item.latest_evidence;
    const repairTask = item.repair_task;
    const presentation = item.presentation ?? {
      quality: g.quality, refused: g.refused,
      chunks_count: g.chunks_count, confidence: g.confidence,
      badge: g.quality, reason: 'Current gap state',
    };
    const qualityClass = presentation.quality || g.quality;
    const badgeLabel = QUALITY_ZH[presentation.badge] ?? QUALITY_ZH[presentation.quality] ?? presentation.quality;
    const causeText = g.cause_type ? CAUSE_TYPE_ZH[g.cause_type] ?? g.cause_type : null;
    const queryShort = g.query.length > 70 ? g.query.slice(0, 70) + '…' : g.query;
    return (
      <li key={g.gap_key ?? g.problem_id ?? `${g.query}-${index}`} className={`gap-item q-${qualityClass}`}>
        <div className="gap-q" title={g.query.length > 70 ? g.query : undefined}>{queryShort}</div>
        <div className="gap-meta">
          {renderGapStatusBadge(g.status)}
          {presentation.refused && <span className="badge refused">系统答不出</span>}
          {causeText && <span className="muted small">{causeText}</span>}
          <span className="muted small gap-time">{fmtDateTime(g.ts)}</span>
        </div>
        {g.resolution_plan && (
          <p className="gap-preview"><strong>处理方案：</strong>{g.resolution_plan}</p>
        )}
        {item.allowed_actions.length > 0 && (
          <div className="gap-actions">
            {item.allowed_actions.includes('live_retest') && (
              <button
                className="learn-refresh gap-action-btn"
                disabled={retestingGaps.has(g.gap_key ?? '')}
                onClick={() => g.gap_key && handleRetestGap(g.gap_key)}
                title="让系统重新回答一次，看现在能不能答好"
              >
                {retestingGaps.has(g.gap_key ?? '') ? '复测中…' : '🔄 再试一次'}
              </button>
            )}
            {item.allowed_actions
              .filter((a) => a !== 'live_retest')
              .map((action) => {
                const tKey = `${g.gap_key}:${action}`;
                return (
                  <button
                    key={action}
                    className="learn-refresh gap-action-btn"
                    disabled={transitioning.has(tKey)}
                    onClick={() => g.gap_key && handleTransitionGap(g.gap_key, action)}
                  >
                    {transitioning.has(tKey) ? '…' : GAP_ACTION_ZH[action] ?? action}
                  </button>
                );
              })}
          </div>
        )}
        {(latestEvidence?.answer_preview || g.answer_preview) && (
          <details className="gap-detail">
            <summary>看看系统答的什么</summary>
            <p className="gap-preview">{latestEvidence?.answer_preview || g.answer_preview}</p>
          </details>
        )}
        {g.sample_queries && g.sample_queries.length > 1 && (
          <details className="gap-detail">
            <summary>类似问题（共 {g.sample_queries.length} 个）</summary>
            <ul className="gap-sample-list">
              {g.sample_queries.map((sample, sampleIndex) => (
                <li key={`${g.gap_key ?? g.query}-${sampleIndex}`}>{sample}</li>
              ))}
            </ul>
          </details>
        )}
        <details className="gap-detail gap-detail-tech">
          <summary>技术细节（开发用）</summary>
          <ul className="gap-tech-list">
            <span className={`badge q-${qualityClass}`} title={presentation.reason}>{badgeLabel}</span>
            <li>片段 {presentation.chunks_count} · 置信 {presentation.confidence.toFixed(2)}</li>
            {typeof g.priority === 'number' && <li>优先级 {g.priority}</li>}
            {g.scope_type && <li>范围 {GAP_SCOPE_ZH[g.scope_type] ?? g.scope_type}{g.scope_id ? ` · 对象 ${g.scope_id}` : ''}</li>}
            {g.affected_route && <li>路径 <code>{g.affected_route}</code></li>}
            {typeof g.frequency === 'number' && <li>出现频次 {g.frequency}</li>}
            {!!g.reopen_count && <li>复发次数 {g.reopen_count}</li>}
            {g.source && <li>来源 {g.source}</li>}
            {g.cluster_id && <li>问题簇 <code>{g.cluster_id.slice(0, 12)}</code></li>}
            {g.linked_event_id != null && <li>关联事件 <code>#{g.linked_event_id}</code></li>}
            {g.owner && <li>负责人 {g.owner}</li>}
            {g.first_seen_at && <li>首次 {fmtDateTime(g.first_seen_at)}</li>}
            {g.last_seen_at && <li>最近 {fmtDateTime(g.last_seen_at)}</li>}
            {g.verified_at && <li>验证 {fmtDateTime(g.verified_at)}</li>}
            {g.observation_until && <li>观察截止 {fmtDateTime(g.observation_until)}</li>}
            {g.last_reopened_at && <li>最近重开 {fmtDateTime(g.last_reopened_at)}</li>}
            {latestEvidence && (
              <li title={latestEvidence.outcome_code ? `outcome_code：${latestEvidence.outcome_code}` : undefined}>
                最新证据：{OUTCOME_FAMILY_ZH[latestEvidence.outcome_code ?? ''] ?? latestEvidence.quality ?? latestEvidence.evidence_type}
                {typeof latestEvidence.chunks_count === 'number' ? ` · 片段 ${latestEvidence.chunks_count}` : ''}
                {typeof latestEvidence.http_status === 'number' ? ` · HTTP ${latestEvidence.http_status}` : ''}
              </li>
            )}
            {repairTask && (
              <li>
                修复任务 #{repairTask.id} · {repairTask.task_type} · {repairTask.status}
                {repairTask.issue_url && (
                  <> · <a href={repairTask.issue_url} target="_blank" rel="noreferrer">issue #{repairTask.issue_number ?? ''}</a></>
                )}
              </li>
            )}
          </ul>
        </details>
      </li>
    );
  };

  // ── 渲染 ──────────────────────────────────────────────
  return (
    <div className="learning-page">
      <PageHeader
        title="自学习看板"
        subtitle="系统自我改进的进度与状态"
        actions={
          <button className="learn-refresh" onClick={refresh} disabled={loading}>
            {loading ? '刷新中…' : '刷新'}
          </button>
        }
      />

      {/* ① KPI 卡片 */}
      <div className="learn-kpi-grid">
        <KpiCard
          label="今天表现"
          value={
            healthStatus === 'good' ? '😊 状态不错'
            : healthStatus === 'warning' ? '🤔 有点问题'
            : healthStatus === 'critical' ? '😣 需要照顾'
            : '⏳ 加载中…'
          }
          hint={
            healthStatus === 'good' ? '系统在正常工作'
            : healthStatus === 'warning' ? '请看下方「当前问题」'
            : healthStatus === 'critical' ? '请马上处理下方问题'
            : ''
          }
          tone={healthTone}
        />
        <KpiCard
          label="最近答题"
          value={total > 0 ? `回答了 ${total} 个问题` : '还没人来问'}
          hint={total > 0 ? (errorCount > 0 ? `其中 ${errorCount} 个回答得不太好` : '全部回答都不错 👍') : ''}
          tone={total === 0 ? undefined : errorRate <= 30 ? 'good' : errorRate <= 60 ? 'warn' : 'bad'}
        />
        <KpiCard
          label="待解决问题"
          value={unresolvedGapCount === 0 ? '✅ 全清了' : `还有 ${unresolvedGapCount} 个问题`}
          hint={
            listenerStale ? `⚠️ 自动复测器已 ${listenerStaleMinutes} 分钟没跑了`
            : unresolvedGapCount === 0 ? '没有未解决的问题'
            : observingCount > 0 ? `其中 ${observingCount} 个观察期满会自动结案`
            : '系统正在想办法'
          }
          tone={listenerStale ? 'bad' : unresolvedGapCount === 0 ? 'good' : unresolvedGapCount <= 5 ? 'warn' : 'bad'}
        />
        <KpiCard
          label="等你拍板"
          value={pendingReviewCount === 0 ? '✅ 没有积压' : `${pendingReviewCount} 个建议`}
          hint={pendingReviewCount === 0 ? '系统暂时不需要你做决定' : '在下方「待审批」里批准或拒绝'}
          tone={pendingReviewCount === 0 ? 'good' : 'warn'}
        />
        <KpiCard
          label="用户评价"
          value={feedbackTotal === 0 ? '还没人评价' : `${feedbackPositive} 人点赞 · ${feedbackNegative} 人吐槽`}
          hint={feedbackTotal === 0 ? '可以让朋友试用一下' : `共收到 ${feedbackTotal} 条反馈`}
        />
      </div>

      {/* ② 系统健康看板 */}
      <DashboardPanel dashboard={dashboard} />

      {/* ③ 当前问题 */}
      <ProblemsPanel problems={problems} />

      {/* ④ 知识缺口生命周期 */}
      <section className="learn-card learn-gaps">
        <div className="learn-card-head">
          <h3>知识缺口 <span className="muted">({gapCounts.total})</span></h3>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <label className="learn-checkbox" title="勾选后对 poor/refused 缺口发起真实查询复测（最多 5 个）">
              <input type="checkbox" checked={liveRetestOn} onChange={(e) => setLiveRetestOn(e.target.checked)} />
              <span>同时实时复测可疑缺口</span>
            </label>
            <button
              className="learn-refresh"
              onClick={() => handleTriageAll(liveRetestOn)}
              disabled={triagePending}
            >
              {triagePending ? '复检中…' : '🔄 复检全部'}
            </button>
          </div>
        </div>
        {triageNote && <p className="muted small" style={{ marginBottom: 8 }}>{triageNote}</p>}
        {!gapWorkbench || gapCounts.total === 0 ? (
          <p className="empty">没有未解决的问题 — 系统目前表现良好。</p>
        ) : (
          <div className="gap-workbench">
            {GAP_BUCKETS.map((bucket) => {
              const items = gapWorkbench.buckets[bucket.key] || [];
              if (items.length === 0) return null;
              return (
                <details key={bucket.key} className="gap-bucket" open={bucket.key !== 'resolved'}>
                  <summary className="gap-bucket-summary">
                    <span className="gap-bucket-title">{bucket.title}</span>
                    <span className="gap-bucket-count">{items.length}</span>
                  </summary>
                  <ul className="gap-list">{items.map(renderGapItem)}</ul>
                </details>
              );
            })}
          </div>
        )}
      </section>

      {/* ⑤ 待审批 + 改进历史 */}
      <ReviewsPanel
        reviews={historyEvents.filter((e) => e.status === 'pending_review')}
        onApprove={async (eventId) => { await approveFix(eventId); refresh(); }}
        onReject={async (eventId, reason) => { await rejectFix(eventId, reason); refresh(); }}
      />
      <ImprovementHistoryPanel
        events={historyEvents}
        stats={{ summary: historySummary, effectiveness: historySummary }}
      />
    </div>
  );
};

interface KpiProps { label: string; value: number | string; hint?: string; tone?: 'good' | 'warn' | 'bad' }
const KpiCard: React.FC<KpiProps> = ({ label, value, hint, tone }) => (
  <div className={`kpi-card ${tone || ''}`}>
    <div className="kpi-label">{label}</div>
    <div className="kpi-value">{value}</div>
    {hint && <div className="kpi-hint">{hint}</div>}
  </div>
);

/**
 * 自学习看板 — 真实数据
 * 数据源：
 *   GET /api/v1/learning/summary   — 总览统计
 *   GET /api/v1/learning/runs      — 最近 agent run 明细
 *   GET /api/v1/learning/gaps/workbench — DB 驱动知识缺口生命周期看板
 */

import { useEffect, useState } from 'react';
import { PageHeader } from '../components/common/PageHeader';
import {
  getLearningSummary,
  getLearningDashboard,
  getLearningRuns,
  getLearningGapWorkbench,
  getLearningBlindspots,
  getConversations,
  getFeedbackStats,
  getLearningEngine,
  getLatestSignals,
  getSignalsSummary,
  getDetectedProblems,
  getImprovementHistory,
  triageGaps,
  retestGap,
  transitionGap,
  LearningSummary,
  LearningDashboard,
  LearningRun,
  LearningGapWorkbench,
  LearningGapWorkbenchItem,
  BlindspotCluster,
  ConversationTurn,
  FeedbackStats,
  LearningEngineStatus,
  SignalAggregation,
  SignalSummary,
  ProblemReport,
  ImprovementEvent,
} from '../services/metricsApi';
import { SystemDiagnosticsDrawer } from '../components/learning/SystemDiagnosticsDrawer';
import { AdvancedDataDrawer } from '../components/learning/AdvancedDataDrawer';
import { StatusTab } from './learning/StatusTab';
import { IssuesTab } from './learning/IssuesTab';
import { ImprovementsTab } from './learning/ImprovementsTab';
import './LearningPage.css';
import { fmtDateTime } from '../utils/dateUtils';
import {
  QualityFilter,
  MainTab,
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
  const [interactionRuns, setInteractionRuns] = useState<LearningRun[]>([]);
  const [learningLoopRuns, setLearningLoopRuns] = useState<LearningRun[]>([]);
  const [gapWorkbench, setGapWorkbench] = useState<LearningGapWorkbench | null>(null);
  const [blindspots, setBlindspots] = useState<BlindspotCluster[]>([]);
  const [conversations, setConversations] = useState<ConversationTurn[]>([]);
  const [feedbackStats, setFeedbackStats] = useState<FeedbackStats | null>(null);
  const [engine, setEngine] = useState<LearningEngineStatus | null>(null);
  const [signals, setSignals] = useState<SignalAggregation | null>(null);
  const [signalsSummary, setSignalsSummary] = useState<SignalSummary | null>(null);
  const [problems, setProblems] = useState<ProblemReport[]>([]);
  const [historyEvents, setHistoryEvents] = useState<ImprovementEvent[]>([]);
  const [historySummary, setHistorySummary] = useState<any>(null);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [triagePending, setTriagePending] = useState(false);
  const [triageNote, setTriageNote] = useState<string | null>(null);
  const [retestingGaps, setRetestingGaps] = useState<Set<string>>(new Set());
  const [transitioning, setTransitioning] = useState<Set<string>>(new Set());
  const [liveRetestOn, setLiveRetestOn] = useState(false);
  const [filter, setFilter] = useState<QualityFilter>('all');
  const [mainTab, setMainTab] = useState<MainTab>('status');
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    const [s, dash, interactionData, learningLoopData, gapWorkbenchData, b, convs, fb, eng, sig, sigSum, probData, histData] = await Promise.all([
      getLearningSummary(),
      getLearningDashboard(),
      getLearningRuns(50, filter === 'all' ? undefined : filter, 'interaction'),
      getLearningRuns(30, undefined, 'learning_loop'),
      getLearningGapWorkbench(200, false),
      getLearningBlindspots(2),
      getConversations(50),
      getFeedbackStats(100),
      getLearningEngine(),
      getLatestSignals(100),
      getSignalsSummary(),
      getDetectedProblems(),
      getImprovementHistory(30),
    ]);
    setSummary(s);
    setDashboard(dash);
    setInteractionRuns(interactionData);
    setLearningLoopRuns(learningLoopData);
    setGapWorkbench(gapWorkbenchData);
    setBlindspots(b?.clusters || []);
    setConversations(convs);
    setFeedbackStats(fb);
    setEngine(eng);
    setSignals(sig);
    setSignalsSummary(sigSum);
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

  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [filter]);
  useEffect(() => {
    const t = setInterval(refresh, 30000);
    return () => clearInterval(t);
    /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, []);

  const qual = summary?.by_quality || { good: 0, weak: 0, failure: 0 };
  const total = summary?.total_runs || 0;
  const errorCount = (qual.weak || 0) + (qual.failure || 0);
  const errorRate = total > 0 ? Math.round((errorCount / total) * 100) : 0;

  const unresolvedGapCount =
    (gapWorkbench?.counts.active ?? 0) + (gapWorkbench?.counts.observing ?? 0);
  const observingCount = gapWorkbench?.counts.observing ?? 0;
  const pendingReviewCount = historyEvents.filter((e) => e.status === 'pending_review').length;

  const healthStatus = dashboard?.health.status;
  const healthTone: 'good' | 'warn' | 'bad' | undefined =
    healthStatus === 'good' ? 'good' : healthStatus === 'warning' ? 'warn' : healthStatus === 'critical' ? 'bad' : undefined;

  const feedbackPositive = summary?.feedback.positive ?? 0;
  const feedbackNegative = summary?.feedback.negative ?? 0;
  const feedbackTotal = summary?.feedback.total ?? 0;

  const topTools = Object.entries(summary?.tool_frequency || {}).slice(0, 8);
  const topTypes = Object.entries(summary?.type_frequency || {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);
  const gapCounts = gapWorkbench?.counts ?? {
    total: 0,
    active: 0,
    observing: 0,
    blocked: 0,
    resolved: 0,
    by_status: {},
  };

  const renderGapItem = (item: LearningGapWorkbenchItem, index: number) => {
    const g = item.gap;
    const latestEvidence = item.latest_evidence;
    const repairTask = item.repair_task;
    const presentation = item.presentation ?? {
      quality: g.quality,
      refused: g.refused,
      chunks_count: g.chunks_count,
      confidence: g.confidence,
      badge: g.quality,
      reason: 'Current gap state',
    };
    const qualityClass = presentation.quality || g.quality;
    const badgeLabel = QUALITY_ZH[presentation.badge] ?? QUALITY_ZH[presentation.quality] ?? presentation.quality;
    const causeText = g.cause_type ? CAUSE_TYPE_ZH[g.cause_type] ?? g.cause_type : null;
    return (
      <li key={g.gap_key ?? g.problem_id ?? `${g.query}-${index}`} className={`gap-item q-${qualityClass}`}>
        <div className="gap-q">{g.query}</div>
        <div className="gap-meta">
          {renderGapStatusBadge(g.status)}
          {presentation.refused && <span className="badge refused">系统答不出</span>}
          {causeText && <span className="muted small">{causeText}</span>}
          <span className="muted small">{fmtDateTime(g.ts)}</span>
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
                const label = GAP_ACTION_ZH[action] ?? action;
                return (
                  <button
                    key={action}
                    className="learn-refresh gap-action-btn"
                    disabled={transitioning.has(tKey)}
                    onClick={() => g.gap_key && handleTransitionGap(g.gap_key, action)}
                    title={`后端动作：${action}`}
                  >
                    {transitioning.has(tKey) ? '…' : label}
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

  const driftCount = engine?.projection_drift?.total_drift_count ?? 0;

  return (
    <div className="learning-page">
      <PageHeader
        title="自学习看板"
        subtitle="agent 运行记录 · 知识缺口 · 反馈分布"
        actions={
          <>
            <button
              className="learn-diagnostics-btn"
              onClick={() => setAdvancedOpen(true)}
              title="盲点聚类、工具频率、问题类型分布、学习引擎"
            >
              📊 高级数据
            </button>
            <button
              className={`learn-diagnostics-btn${driftCount > 0 ? ' has-drift' : ''}`}
              onClick={() => setDiagnosticsOpen(true)}
              title="系统自检（投影一致性、reconcile 工具）"
            >
              🔧 系统自检
              {driftCount > 0 && <span className="learn-diagnostics-dot" aria-hidden />}
            </button>
            <button className="learn-refresh" onClick={refresh} disabled={loading}>
              {loading ? '刷新中…' : '刷新'}
            </button>
          </>
        }
      />

      <SystemDiagnosticsDrawer
        open={diagnosticsOpen}
        onClose={() => setDiagnosticsOpen(false)}
        globalDrift={engine?.projection_drift}
        lastReconcile={engine?.last_projection_reconcile}
        onAfterReconcile={refresh}
      />

      <AdvancedDataDrawer
        open={advancedOpen}
        onClose={() => setAdvancedOpen(false)}
        blindspots={blindspots}
        topTools={topTools}
        topTypes={topTypes}
        engine={engine}
      />

      {/* KPI 卡片 — 大白话视角 */}
      <div className="learn-kpi-grid">
        <KpiCard
          label="今天表现"
          value={
            healthStatus === 'good'
              ? '😊 状态不错'
              : healthStatus === 'warning'
              ? '🤔 有点问题'
              : healthStatus === 'critical'
              ? '😣 需要照顾'
              : '⏳ 加载中…'
          }
          hint={
            healthStatus === 'good'
              ? '系统在正常工作'
              : healthStatus === 'warning'
              ? '建议看一下下面的「问题」标签'
              : healthStatus === 'critical'
              ? '请马上去看「问题」标签'
              : ''
          }
          tone={healthTone}
        />
        <KpiCard
          label="最近答题"
          value={total > 0 ? `回答了 ${total} 个问题` : '还没人来问'}
          hint={
            total > 0
              ? errorCount > 0
                ? `其中 ${errorCount} 个回答得不太好`
                : '全部回答都不错 👍'
              : ''
          }
          tone={total === 0 ? undefined : errorRate <= 30 ? 'good' : errorRate <= 60 ? 'warn' : 'bad'}
        />
        <KpiCard
          label="待解决问题"
          value={
            unresolvedGapCount === 0
              ? '✅ 全清了'
              : `还有 ${unresolvedGapCount} 个问题`
          }
          hint={
            unresolvedGapCount === 0
              ? '没有未解决的问题'
              : observingCount > 0
              ? `其中 ${observingCount} 个先观察一阵子`
              : '系统正在想办法'
          }
          tone={unresolvedGapCount === 0 ? 'good' : unresolvedGapCount <= 5 ? 'warn' : 'bad'}
        />
        <KpiCard
          label="等你拍板"
          value={
            pendingReviewCount === 0
              ? '✅ 没有积压'
              : `${pendingReviewCount} 个建议`
          }
          hint={
            pendingReviewCount === 0
              ? '系统暂时不需要你做决定'
              : '去「改进队列」标签批准或拒绝'
          }
          tone={pendingReviewCount === 0 ? 'good' : 'warn'}
        />
        <KpiCard
          label="用户评价"
          value={
            feedbackTotal === 0
              ? '还没人评价'
              : `${feedbackPositive} 人点赞 · ${feedbackNegative} 人吐槽`
          }
          hint={feedbackTotal === 0 ? '可以让朋友试用一下' : `共收到 ${feedbackTotal} 条反馈`}
        />
      </div>

      <div className="learn-grid">
        {/* DB 驱动知识缺口生命周期 */}
        <section className="learn-card learn-gaps">
          <div className="learn-card-head">
            <h3>知识缺口生命周期 <span className="muted">({gapCounts.total})</span></h3>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
              <label className="learn-checkbox" title="勾选后对 poor/refused 缺口发起真实查询复测（最多 5 个）">
                <input
                  type="checkbox"
                  checked={liveRetestOn}
                  onChange={(e) => setLiveRetestOn(e.target.checked)}
                />
                <span>同时实时复测可疑缺口</span>
              </label>
              <button
                className="learn-refresh"
                onClick={() => handleTriageAll(liveRetestOn)}
                disabled={triagePending}
                title="对所有活跃缺口执行策略复检"
              >
                {triagePending ? '复检中…' : '🔄 复检全部缺口'}
              </button>
            </div>
          </div>
          {triageNote && <p className="muted small" style={{ marginBottom: 8 }}>{triageNote}</p>}
          {!gapWorkbench || gapCounts.total === 0 ? (
            <p className="empty">暂无识别到的知识缺口 — 当前所有运行均良好。</p>
          ) : (
            <div className="gap-workbench">
              {GAP_BUCKETS.map((bucket) => {
                const items = gapWorkbench.buckets[bucket.key] || [];
                return (
                  <div key={bucket.key} className="gap-bucket">
                    <div className="learn-card-head">
                      <h4>{bucket.title} <span className="muted">({items.length})</span></h4>
                      <span className="muted small">{bucket.hint}</span>
                    </div>
                    {items.length === 0 ? (
                      <p className="empty">暂无{bucket.title}问题。</p>
                    ) : (
                      <ul className="gap-list">
                        {items.map(renderGapItem)}
                      </ul>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>

      </div>

      {/* 主 Tab 导航 */}
      <div className="learn-main-tabs">
        {(
          [
            ['status', '📊 现状'],
            ['qa-issues', '🔍 问答与问题'],
            [
              'improvements',
              `🛠 改进队列${pendingReviewCount > 0 ? ` (${pendingReviewCount})` : ''}`,
            ],
          ] as [MainTab, string][]
        ).map(([t, label]) => (
          <button key={t} className={mainTab === t ? 'active' : ''} onClick={() => setMainTab(t)}>
            {label}
          </button>
        ))}
      </div>

      {/* Tab 简介 */}
      <p className="muted small" style={{ marginTop: -4, marginBottom: 12 }}>
        {mainTab === 'status' && '系统在干什么 — 健康度、改进趋势、实时信号、最近事件。'}
        {mainTab === 'qa-issues' && '它做错了什么 — 自动检测的问题、最近问答、对话记录、用户反馈。'}
        {mainTab === 'improvements' && '它在怎么改进 — 待审核的修复建议、历史成功率趋势。'}
      </p>

      {mainTab === 'status' && (
        <StatusTab signals={signals} signalsSummary={signalsSummary} />
      )}

      {mainTab === 'qa-issues' && (
        <IssuesTab
          problems={problems}
          interactionRuns={interactionRuns}
          learningLoopRuns={learningLoopRuns}
          conversations={conversations}
          feedbackStats={feedbackStats}
          filter={filter}
          onFilterChange={setFilter}
        />
      )}

      {mainTab === 'improvements' && (
        <ImprovementsTab
          historyEvents={historyEvents}
          historySummary={historySummary}
          onApprove={(eventId) => {
            console.log('Approved:', eventId);
            refresh();
          }}
          onReject={(eventId, reason) => {
            console.log('Rejected:', eventId, reason);
            refresh();
          }}
        />
      )}

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

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
import { StatusTab } from './learning/StatusTab';
import { IssuesTab } from './learning/IssuesTab';
import { ImprovementsTab } from './learning/ImprovementsTab';
import './LearningPage.css';
import { fmtDateTime } from '../utils/dateUtils';
import {
  QualityFilter,
  MainTab,
  QUALITY_ZH,
  TYPE_ZH,
  OUTCOME_FAMILY_ZH,
  ENGINE_TRIGGER_MODE_ZH,
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
  const refusedCount = summary?.refused_count ?? 0;
  const errorRate = total > 0 ? Math.round((errorCount / total) * 100) : 0;

  const unresolvedGapCount =
    (gapWorkbench?.counts.active ?? 0) + (gapWorkbench?.counts.observing ?? 0);
  const observingCount = gapWorkbench?.counts.observing ?? 0;
  const pendingReviewCount = historyEvents.filter((e) => e.status === 'pending_review').length;

  const healthScore = dashboard?.health.score;
  const healthStatus = dashboard?.health.status;
  const healthEmoji =
    healthStatus === 'good' ? '✅' : healthStatus === 'warning' ? '⚠️' : healthStatus === 'critical' ? '🚨' : '—';
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
    return (
      <li key={g.gap_key ?? g.problem_id ?? `${g.query}-${index}`} className={`gap-item q-${qualityClass}`}>
        <div className="gap-q">{g.query}</div>
        <div className="gap-meta">
          <span className={`badge q-${qualityClass}`} title={presentation.reason}>{badgeLabel}</span>
          {renderGapStatusBadge(g.status)}
          {presentation.refused && <span className="badge refused">拒答</span>}
          <span className="muted small">片段 {presentation.chunks_count}</span>
          <span className="muted small">置信 {presentation.confidence.toFixed(2)}</span>
          {typeof g.priority === 'number' && <span className="muted small">优先级 {g.priority}</span>}
          {g.scope_type && <span className="muted small">范围 {GAP_SCOPE_ZH[g.scope_type] ?? g.scope_type}</span>}
          {g.scope_id && <span className="muted small">对象 {g.scope_id}</span>}
          {g.affected_route && <span className="muted small">路径 {g.affected_route}</span>}
          {g.cause_type && (
            <span className="muted small" title={`后端字段：${g.cause_type}`}>
              成因 {CAUSE_TYPE_ZH[g.cause_type] ?? g.cause_type}
            </span>
          )}
          {typeof g.frequency === 'number' && <span className="muted small">频次 {g.frequency}</span>}
          {!!g.reopen_count && <span className="muted small">复发 {g.reopen_count}</span>}
          {g.source && <span className="muted small">来源 {g.source}</span>}
          <span className="muted small">{fmtDateTime(g.ts)}</span>
        </div>
        {(g.cluster_id || g.linked_event_id || g.owner || item.allowed_actions.length > 0) && (
          <div className="gap-meta">
            {g.cluster_id && (
              <span className="muted small" title={`完整簇 ID：${g.cluster_id}`}>
                所属问题簇 <code>{g.cluster_id.slice(0, 8)}…</code>
              </span>
            )}
            {g.linked_event_id != null && (
              <span className="muted small">关联事件 <code>#{g.linked_event_id}</code></span>
            )}
            {g.owner && <span className="muted small">负责人 {g.owner}</span>}
            {g.first_seen_at && <span className="muted small">首次 {fmtDateTime(g.first_seen_at)}</span>}
            {g.last_seen_at && <span className="muted small">最近 {fmtDateTime(g.last_seen_at)}</span>}
            {g.verified_at && <span className="muted small">验证 {fmtDateTime(g.verified_at)}</span>}
            {g.observation_until && <span className="muted small">观察截止 {fmtDateTime(g.observation_until)}</span>}
            {g.last_reopened_at && <span className="muted small">最近重开 {fmtDateTime(g.last_reopened_at)}</span>}
            {item.allowed_actions.length > 0 && (
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
                  {item.allowed_actions.includes('live_retest') && (
                    <button
                      className="learn-refresh"
                      style={{ fontSize: '0.75rem', padding: '2px 8px' }}
                      disabled={retestingGaps.has(g.gap_key ?? '')}
                      onClick={() => g.gap_key && handleRetestGap(g.gap_key)}
                      title="通过真实查询端点实时复测此缺口"
                    >
                      {retestingGaps.has(g.gap_key ?? '') ? '复测中…' : '🔄 实时复测'}
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
                          className="learn-refresh"
                          style={{ fontSize: '0.75rem', padding: '2px 8px' }}
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
          </div>
        )}
        {latestEvidence && (
          <p
            className="gap-preview"
            title={
              latestEvidence.outcome_code
                ? `后端 outcome_code：${latestEvidence.outcome_code}`
                : undefined
            }
          >
            <strong>最新证据：</strong>
            {OUTCOME_FAMILY_ZH[latestEvidence.outcome_code ?? ''] ??
              QUALITY_ZH[latestEvidence.quality ?? ''] ??
              latestEvidence.quality ??
              latestEvidence.evidence_type}
            {typeof latestEvidence.chunks_count === 'number' ? ` · 片段 ${latestEvidence.chunks_count}` : ''}
            {typeof latestEvidence.http_status === 'number' ? ` · HTTP ${latestEvidence.http_status}` : ''}
            {latestEvidence.recorded_at ? ` · ${fmtDateTime(latestEvidence.recorded_at)}` : ''}
          </p>
        )}
        {repairTask && (
          <p className="gap-preview">
            <strong>修复任务：</strong>
            #{repairTask.id} · {repairTask.task_type} · {repairTask.status}
            {repairTask.issue_url ? (
              <>
                {' · '}
                <a href={repairTask.issue_url} target="_blank" rel="noreferrer">
                  issue #{repairTask.issue_number ?? repairTask.issue_url}
                </a>
              </>
            ) : null}
            {repairTask.updated_at ? ` · ${fmtDateTime(repairTask.updated_at)}` : ''}
          </p>
        )}
        {g.resolution_plan && (
          <p className="gap-preview"><strong>处置摘要：</strong>{g.resolution_plan}</p>
        )}
        {(latestEvidence?.answer_preview || g.answer_preview) && (
          <details>
            <summary className="muted small">查看答案预览</summary>
            <p className="gap-preview">{latestEvidence?.answer_preview || g.answer_preview}</p>
          </details>
        )}
        {g.sample_queries && g.sample_queries.length > 1 && (
          <details>
            <summary className="muted small">查看同簇问题（{g.sample_queries.length}）</summary>
            <ul style={{ marginTop: 6, paddingLeft: 18 }}>
              {g.sample_queries.map((sample, sampleIndex) => (
                <li key={`${g.gap_key ?? g.query}-${sampleIndex}`} className="muted small" style={{ listStyle: 'disc' }}>
                  {sample}
                </li>
              ))}
            </ul>
          </details>
        )}
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

      {/* KPI 卡片 */}
      <div className="learn-kpi-grid">
        <KpiCard
          label="系统健康度"
          value={healthScore != null ? `${healthEmoji} ${healthScore}` : '—'}
          hint={
            healthStatus === 'good'
              ? '运行正常'
              : healthStatus === 'warning'
              ? '需要关注'
              : healthStatus === 'critical'
              ? '需要紧急处理'
              : '加载中…'
          }
          tone={healthTone}
        />
        <KpiCard
          label="回答 / 错误"
          value={`${total} / ${errorCount}`}
          hint={
            total > 0
              ? `错误率 ${errorRate}%${refusedCount > 0 ? ` · 拒答 ${refusedCount}` : ''}`
              : '暂无样本'
          }
          tone={errorRate <= 30 ? 'good' : errorRate <= 60 ? 'warn' : 'bad'}
        />
        <KpiCard
          label="未解决缺口"
          value={unresolvedGapCount}
          hint={observingCount > 0 ? `其中观察期 ${observingCount}` : '处理中 + 观察期'}
          tone={unresolvedGapCount === 0 ? 'good' : unresolvedGapCount <= 5 ? 'warn' : 'bad'}
        />
        <KpiCard
          label="待审核改进"
          value={pendingReviewCount}
          hint={pendingReviewCount > 0 ? '需要人工决策' : '当前无积压'}
          tone={pendingReviewCount === 0 ? 'good' : 'warn'}
        />
        <KpiCard
          label="用户反馈"
          value={`+${feedbackPositive} / -${feedbackNegative}`}
          hint={feedbackTotal > 0 ? `共 ${feedbackTotal} 条` : '暂无反馈'}
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

        {/* 盲点聚类 */}
        <section className="learn-card learn-gaps">
          <div className="learn-card-head">
            <h3>盲点聚类 <span className="muted">({blindspots.length})</span></h3>
            <span className="muted small">语义相近的失败问题分组，提示批量短板</span>
          </div>
          {blindspots.length === 0 ? (
            <p className="empty">尚未形成可聚合的盲点（需 ≥ 2 个相近失败问题）。</p>
          ) : (
            <ul className="gap-list">
              {blindspots.map((c, i) => (
                <li key={i} className="gap-item q-failure">
                  <div className="gap-q">代表问题：{c.representative}</div>
                  <div className="gap-meta">
                    <span className="badge q-failure">规模 {c.size}</span>
                    <span className="muted small">{c.diagnosis}</span>
                  </div>
                  <details>
                    <summary className="muted small">展开相似问题（{c.queries?.length ?? 0}个）</summary>
                    <ul style={{ marginTop: 6, paddingLeft: 18 }}>
                      {(c.queries || []).map((q, j) => (
                        <li key={j} className="muted small" style={{ listStyle: 'disc' }}>
                          {q}
                        </li>
                      ))}
                    </ul>
                  </details>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* 工具使用频率 */}
        <section className="learn-card">
          <div className="learn-card-head">
            <h3>工具使用频率</h3>
          </div>
          {topTools.length === 0 ? (
            <p className="empty">暂无工具调用记录。</p>
          ) : (
            <ul className="bar-list">
              {topTools.map(([tool, count]) => {
                const max = topTools[0][1];
                const pct = Math.max(2, Math.round((count / max) * 100));
                return (
                  <li key={tool}>
                    <div className="bar-label">
                      <code>{tool}</code>
                      <span className="muted small">{count}</span>
                    </div>
                    <div className="bar-track"><div className="bar-fill" style={{ width: `${pct}%` }} /></div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* 问题类型分布 */}
        <section className="learn-card">
          <div className="learn-card-head">
            <h3>问题类型分布</h3>
          </div>
          {topTypes.length === 0 ? (
            <p className="empty">暂无类型数据。</p>
          ) : (
            <ul className="bar-list">
              {topTypes.map(([type, count]) => {
                const max = topTypes[0][1];
                const pct = Math.max(2, Math.round((count / max) * 100));
                return (
                  <li key={type}>
                    <div className="bar-label">
                      <code>{TYPE_ZH[type] ?? type}</code>
                      <span className="muted small">{count}</span>
                    </div>
                    <div className="bar-track"><div className="bar-fill alt" style={{ width: `${pct}%` }} /></div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>

      {/* 学习引擎 — 触发条件透明化 */}
      <section className="learn-card learn-engine-card" style={{ marginTop: 16 }}>
        <div className="learn-card-head">
          <h3>🧠 学习引擎</h3>
          <span className="muted small">
            {engine ? `触发模式：${ENGINE_TRIGGER_MODE_ZH[engine.trigger_mode] ?? engine.trigger_mode}` : '加载中…'}
          </span>
        </div>
        {engine ? (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <div>
              <p className="muted small" style={{ marginTop: 0 }}>{engine.trigger_description}</p>
              <table className="learn-runs-table" style={{ marginTop: 8 }}>
                <thead><tr><th>触发条件</th><th>状态</th><th>说明</th></tr></thead>
                <tbody>
                  {engine.trigger_conditions.map((c, i) => (
                    <tr key={i}>
                      <td>{c.name}</td>
                      <td><span className={`badge q-${c.active ? 'good' : 'weak'}`}>{c.active ? '已启用' : '未启用'}</span></td>
                      <td className="muted small">{c.command ? <code>{c.command}</code> : (c.note || '—')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div>
              <h4 style={{ marginTop: 0 }}>上次回归</h4>
              {engine.last_run.summary ? (
                <ul className="learn-engine-stats">
                  <li>时间：<code>{engine.last_run.ts ? fmtDateTime(engine.last_run.ts) : '—'}</code></li>
                  <li>金标题数：<b>{engine.last_run.summary.total ?? '—'}</b></li>
                  <li>通过：<b>{engine.last_run.summary.passed ?? '—'}</b></li>
                  <li>平均置信：<b>{engine.last_run.summary.avg_confidence?.toFixed(2) ?? '—'}</b></li>
                </ul>
              ) : (
                <p className="muted small">无历史回归记录。运行 <code>python tests/test_agent_16.py</code> 生成。</p>
              )}
              <h4>近 24h 信号</h4>
              <ul className="learn-engine-stats">
                <li>弱/失败运行：<b>{engine.signals_24h.weak_or_failed_runs}</b></li>
                <li>带评论的负面反馈：<b>{engine.signals_24h.pending_negative_feedback_with_text}</b></li>
              </ul>
              {engine.next_actions.length > 0 && (
                <>
                  <h4>建议下一步</h4>
                  <ul className="learn-engine-stats">
                    {engine.next_actions.map((a, i) => <li key={i}>{a}</li>)}
                  </ul>
                </>
              )}
            </div>
          </div>
        ) : (
          <p className="muted">加载中…</p>
        )}
      </section>

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

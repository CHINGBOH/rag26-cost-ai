/**
 * 自学习看板 — 真实数据
 * 数据源：
 *   GET /api/v1/learning/summary   — 总览统计
 *   GET /api/v1/learning/runs      — 最近 agent run 明细
 *   GET /api/v1/learning/gaps/workbench — DB 驱动知识缺口生命周期看板
 */

import { useEffect, useState } from 'react';
import { PageHeader } from '../components/common/PageHeader';
import { ProblemsPanel } from '../components/learning/ProblemsPanel';
import { ReviewsPanel } from '../components/learning/ReviewsPanel';
import { ImprovementHistoryPanel } from '../components/learning/ImprovementHistoryPanel';
import { DashboardPanel } from '../components/learning/DashboardPanel';
import {
  getLearningSummary,
  getLearningProjectionDrift,
  reconcileLearningProjections,
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
  getLearningStats,
  LearningSummary,
  LearningProjectionDriftSummary,
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
import './LearningPage.css';
import { fmtDateTime } from '../utils/dateUtils';
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

type QualityFilter = 'all' | 'good' | 'weak' | 'failure';
type MainTab = 'dashboard' | 'runs' | 'conversations' | 'feedback' | 'signals' | 'problems' | 'reviews' | 'history';

const QUALITY_ZH: Record<string, string> = {
  good: '优质', weak: '弱', failure: '失败', non_task: '非任务', validated: '已验证',
};
const TYPE_ZH: Record<string, string> = {
  standard_ref: '标准查询', price: '价格查询', trend_chart: '趋势图表',
  comparison: '对比分析', calculation: '计算推理', semantic: '语义检索',
};
const OUTCOME_FAMILY_ZH: Record<string, string> = {
  answered: '已回答',
  refused: '拒答',
  failed: '失败',
  non_task: '非任务',
  early_exit: '早停',
  cancelled: '取消',
};
const RUN_TYPE_ZH: Record<string, string> = {
  manual: '手动',
  scheduled: '定时',
  auto_threshold: '阈值触发',
  feedback_analysis: '反馈分析',
};
const ENGINE_TRIGGER_MODE_ZH: Record<string, string> = {
  manual: '手动',
  hybrid: '手动 + 运行态监控',
  scheduled: '定时',
  automated: '自动',
};
const GAP_SCOPE_ZH: Record<string, string> = {
  user: '用户',
  agent: 'Agent',
  project: '项目',
  global: '全局',
};
const GAP_BUCKETS: Array<{ key: 'active' | 'observing' | 'blocked' | 'resolved'; title: string; hint: string }> = [
  { key: 'active', title: '待处理', hint: 'open / in_progress，监听器会实际调用咨询端口复测' },
  { key: 'observing', title: '观察期', hint: '已被真实回答验证，等待观察窗口结束' },
  { key: 'blocked', title: '已阻塞', hint: '政策/越界/伪造类问题，不再当普通知识缺口占位' },
  { key: 'resolved', title: '已解决', hint: '后端生命周期已关闭的问题' },
];

function renderGapStatusBadge(status?: string) {
  if (status === 'resolved') return <span className="badge status-resolved">✅ 已解决</span>;
  if (status === 'observing') return <span className="badge status-observing">👀 观察期</span>;
  if (status === 'in_progress') return <span className="badge status-in-progress">🔄 处理中</span>;
  if (status === 'open') return <span className="badge status-open">❌ 未开始</span>;
  if (status === 'blocked') return <span className="badge status-blocked">🚫 被阻止</span>;
  return null;
}

function renderLearningRunStatusBadge(status?: string) {
  if (status === 'completed') return <span className="badge status-resolved">完成</span>;
  if (status === 'running') return <span className="badge status-in-progress">运行中</span>;
  if (status === 'failed') return <span className="badge status-open">失败</span>;
  if (status === 'blocked') return <span className="badge status-blocked">阻塞</span>;
  return status ? <span className="badge status-neutral">{status}</span> : null;
}

export const LearningPage: React.FC = () => {
  const [summary, setSummary] = useState<LearningSummary | null>(null);
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
  const [learningStats, setLearningStats] = useState<any>(null);
  const [selectedRunDrift, setSelectedRunDrift] = useState<LearningProjectionDriftSummary | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [driftLoading, setDriftLoading] = useState(false);
  const [driftReconciling, setDriftReconciling] = useState(false);
  const [driftNote, setDriftNote] = useState<string | null>(null);
  const [filter, setFilter] = useState<QualityFilter>('all');
  const [mainTab, setMainTab] = useState<MainTab>('dashboard');
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    const [s, interactionData, learningLoopData, gapWorkbenchData, b, convs, fb, eng, sig, sigSum, probData, histData, statsData] = await Promise.all([
      getLearningSummary(),
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
      getLearningStats(),
    ]);
    setSummary(s);
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
    setLearningStats(statsData);
    setLoading(false);
  };

  const inspectRunDrift = async (runId?: string, clearNote = true) => {
    if (!runId) return;
    setDriftLoading(true);
    setSelectedRunId(runId);
    if (clearNote) {
      setDriftNote(null);
    }
    const drift = await getLearningProjectionDrift(runId);
    setSelectedRunDrift(drift);
    setDriftLoading(false);
  };

  const reconcileRunDrift = async () => {
    if (!selectedRunId) return;
    setDriftReconciling(true);
    const result = await reconcileLearningProjections(selectedRunId);
    if (!result) {
      setDriftNote('该 run 的 reconcile 请求失败。');
      setDriftReconciling(false);
      return;
    }
    setDriftNote(`已重建 ${result.rebuilt_total} 条记录，剩余 drift ${result.remaining_drift_count}。`);
    await inspectRunDrift(selectedRunId, false);
    setDriftReconciling(false);
  };

  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [filter]);
  useEffect(() => {
    const t = setInterval(refresh, 30000);
    return () => clearInterval(t);
    /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, []);

  const qual = summary?.by_quality || { good: 0, weak: 0, failure: 0 };
  const total = summary?.total_runs || 0;
  const successRate = total > 0 ? Math.round(((qual.good || 0) / total) * 100) : 0;

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
          {g.cause_type && <span className="muted small">成因 {g.cause_type}</span>}
          {typeof g.frequency === 'number' && <span className="muted small">频次 {g.frequency}</span>}
          {!!g.reopen_count && <span className="muted small">复发 {g.reopen_count}</span>}
          {g.source && <span className="muted small">来源 {g.source}</span>}
          <span className="muted small">{fmtDateTime(g.ts)}</span>
        </div>
        {(g.cluster_id || g.linked_event_id || g.owner || item.allowed_actions.length > 0) && (
          <div className="gap-meta">
            {g.cluster_id && <span className="muted small">簇 {g.cluster_id.slice(0, 12)}</span>}
            {g.linked_event_id != null && <span className="muted small">事件 #{g.linked_event_id}</span>}
            {g.owner && <span className="muted small">负责人 {g.owner}</span>}
            {g.first_seen_at && <span className="muted small">首次 {fmtDateTime(g.first_seen_at)}</span>}
            {g.last_seen_at && <span className="muted small">最近 {fmtDateTime(g.last_seen_at)}</span>}
            {g.verified_at && <span className="muted small">验证 {fmtDateTime(g.verified_at)}</span>}
            {g.observation_until && <span className="muted small">观察截止 {fmtDateTime(g.observation_until)}</span>}
            {g.last_reopened_at && <span className="muted small">最近重开 {fmtDateTime(g.last_reopened_at)}</span>}
            {item.allowed_actions.length > 0 && (
              <span className="muted small">后端动作 {item.allowed_actions.join(' / ')}</span>
            )}
          </div>
        )}
        {latestEvidence && (
          <p className="gap-preview">
            <strong>最新证据：</strong>
            {latestEvidence.outcome_code ?? latestEvidence.quality ?? latestEvidence.evidence_type}
            {typeof latestEvidence.chunks_count === 'number' ? ` · chunks ${latestEvidence.chunks_count}` : ''}
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

  return (
    <div className="learning-page">
      <PageHeader
        title="自学习看板"
        subtitle="agent 运行记录 · 知识缺口 · 反馈分布"
        actions={
          <button className="learn-refresh" onClick={refresh} disabled={loading}>
            {loading ? '刷新中…' : '刷新'}
          </button>
        }
      />

      {/* KPI 卡片 */}
      <div className="learn-kpi-grid">
        <KpiCard label="总 agent 运行" value={total} hint="最近 500 条窗口" />
        <KpiCard
          label="成功率"
          value={`${successRate}%`}
          hint={`${qual.good || 0} 优质 / ${qual.weak || 0} 弱 / ${qual.failure || 0} 失败`}
          tone={successRate >= 70 ? 'good' : successRate >= 40 ? 'warn' : 'bad'}
        />
        <KpiCard
          label="平均置信度"
          value={summary ? summary.avg_confidence.toFixed(2) : '—'}
          hint="LLM 自评"
        />
        <KpiCard
          label="拒答数"
          value={summary?.refused_count ?? 0}
          hint="检测到拒绝模式"
          tone={(summary?.refused_count || 0) > 0 ? 'warn' : 'good'}
        />
        <KpiCard
          label="用户反馈"
          value={`+${summary?.feedback.positive ?? 0} / -${summary?.feedback.negative ?? 0}`}
          hint={`共 ${summary?.feedback.total ?? 0} 条`}
        />
      </div>

      <div className="learn-grid">
        {/* DB 驱动知识缺口生命周期 */}
        <section className="learn-card learn-gaps">
          <div className="learn-card-head">
            <h3>知识缺口生命周期 <span className="muted">({gapCounts.total})</span></h3>
            <span className="muted small">后端 DB workbench 分桶；前端只呈现状态、证据和允许动作</span>
          </div>
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
              <h4>Projection 漂移</h4>
              {engine.projection_drift ? (
                <div className="run-drift-panel">
                  <div className="run-drift-summary">
                    <span className={`badge q-${engine.projection_drift.total_drift_count === 0 ? 'good' : 'weak'}`}>
                      {engine.projection_drift.total_drift_count === 0
                        ? '已对齐'
                        : `${engine.projection_drift.total_drift_count} 处漂移`}
                    </span>
                    <span className="muted small">
                      {engine.projection_drift.drifted_projections.length > 0
                        ? engine.projection_drift.drifted_projections.join(', ')
                        : '三张核心 projection 当前与 canonical ledger 对齐'}
                    </span>
                  </div>
                  {Object.entries(engine.projection_drift.projections)
                    .filter(([, projection]) => (projection?.drift_count ?? 0) > 0)
                    .length > 0 && (
                    <div className="run-drift-grid">
                      {Object.entries(engine.projection_drift.projections)
                        .filter(([, projection]) => (projection?.drift_count ?? 0) > 0)
                        .map(([projectionName, projection]) => (
                          <div
                            key={projectionName}
                            className={`run-drift-card ${(projection?.drift_count ?? 0) > 0 ? 'has-drift' : ''}`}
                          >
                            <div className="run-drift-card-title">{projectionName}</div>
                            <div className="run-drift-card-count">{projection?.drift_count ?? 0}</div>
                            <div className="run-drift-card-meta">
                              <span>ledger: {projection?.ledger_count ?? '—'}</span>
                              <span>projection: {projection?.projection_count ?? '—'}</span>
                            </div>
                          </div>
                        ))}
                    </div>
                  )}
                </div>
              ) : (
                <p className="muted small">当前未能读取 projection drift 摘要。</p>
              )}
              <h4>最近一次 Reconcile</h4>
              {engine.last_projection_reconcile ? (
                <ul className="learn-engine-stats">
                  <li>
                    时间：<code>{engine.last_projection_reconcile.occurred_at ? fmtDateTime(engine.last_projection_reconcile.occurred_at) : '—'}</code>
                  </li>
                  <li>
                    范围：<b>{engine.last_projection_reconcile.scope === 'run'
                      ? `Run ${engine.last_projection_reconcile.run_id ?? '—'}`
                      : '全局'}</b>
                  </li>
                  <li>重建条目：<b>{engine.last_projection_reconcile.rebuilt_total}</b></li>
                  <li>剩余 drift：<b>{engine.last_projection_reconcile.remaining_drift_count}</b></li>
                </ul>
              ) : (
                <p className="muted small">暂无 projection reconcile 审计记录。</p>
              )}
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
        {([['dashboard', '📊 监控看板'], ['runs', 'Agent 运行轨迹'], ['conversations', '问答记录'], ['feedback', '反馈与趋势'], ['signals', '📡 信号监控'], ['problems', '🔍 问题诊断'], ['reviews', `📋 待审核 (${historyEvents.filter(e => e.status === 'pending_review').length})`], ['history', '📊 迭代历史']] as [MainTab, string][]).map(([t, label]) => (
          <button key={t} className={mainTab === t ? 'active' : ''} onClick={() => setMainTab(t)}>
            {label}
          </button>
        ))}
      </div>

      {/* Tab 简介 */}
      <p className="muted small" style={{ marginTop: -4, marginBottom: 12 }}>
        {mainTab === 'dashboard' && '📊 学习系统健康度实时监控 — 系统得分、告警、改进趋势、最近事件一览。'}
        {mainTab === 'runs' && '🔍 分开展示 interaction runs 与 learning-loop runs，分别查看问答终态语义和学习回路执行状态。'}
        {mainTab === 'conversations' && '💬 用户每一轮 Q&A 原始记录（conversation_turns 表），是迭代的第一手素材。'}
        {mainTab === 'feedback' && '⭐ 用户的 👍👎 + 1-5 星评分 + 文字点评（rag_feedback 表），驱动模型/检索改进。'}
        {mainTab === 'signals' && '📡 实时信号采集面板 — 反馈、失败、重复问题、合约违规、拓扑异常的综合展示。'}
        {mainTab === 'problems' && '🔍 系统自动检测到的问题 — 提示、工具失败、路由错误、低质量、多样性不足，附带根因分析和修复建议。'}
        {mainTab === 'reviews' && '📋 待人工审核的修复建议 — 中风险修复、已应用待验证的改进，支持批准或拒绝。'}
        {mainTab === 'history' && '📊 迭代历史 — 所有修复的成功率变化趋势、详细日志，追踪系统改进进展。'}
      </p>

      {/* 监控看板 */}
      {mainTab === 'dashboard' && (
        <DashboardPanel />
      )}

      {/* 运行明细 */}
      {mainTab === 'runs' && (
      <section className="learn-card learn-runs-card">
        <div className="learn-card-head">
          <h3>最近 agent 运行</h3>
          <div className="filter-tabs">
            {(['all', 'good', 'weak', 'failure'] as QualityFilter[]).map((f) => (
              <button
                key={f}
                className={filter === f ? 'active' : ''}
                onClick={() => setFilter(f)}
              >
                {f === 'all' ? '全部' : f === 'good' ? '优质' : f === 'weak' ? '弱' : '失败'}
              </button>
            ))}
          </div>
        </div>
        {selectedRunId && (
          <div className="run-drift-panel">
            <div className="learn-card-head">
              <h3>Run Drift Diagnostic</h3>
              <div className="run-drift-actions">
                <code>{selectedRunId}</code>
                <button className="learn-refresh" onClick={() => inspectRunDrift(selectedRunId)} disabled={driftLoading}>
                  {driftLoading ? '加载中…' : '刷新'}
                </button>
                <button className="learn-refresh" onClick={reconcileRunDrift} disabled={driftReconciling || driftLoading}>
                  {driftReconciling ? '修复中…' : 'Reconcile this run'}
                </button>
                <button className="learn-refresh" onClick={() => { setSelectedRunId(null); setSelectedRunDrift(null); }}>
                  关闭
                </button>
              </div>
            </div>
            {driftNote && <p className="muted small" style={{ marginTop: 0, marginBottom: 10 }}>{driftNote}</p>}
            {!selectedRunDrift ? (
              <p className="empty">{driftLoading ? '正在加载 drift 诊断…' : '未能获取该 run 的 drift 诊断。'}</p>
            ) : (
              <>
                <div className="run-drift-summary">
                  <span className={`badge ${selectedRunDrift.total_drift_count > 0 ? 'q-weak' : 'q-good'}`}>
                    drift {selectedRunDrift.total_drift_count}
                  </span>
                  <span className="muted small">
                    受影响读面：{selectedRunDrift.drifted_projections.length > 0 ? selectedRunDrift.drifted_projections.join(', ') : '无'}
                  </span>
                </div>
                <div className="run-drift-grid">
                  {Object.entries(selectedRunDrift.projections || {}).map(([name, detail]) => (
                    <div key={name} className={`run-drift-card ${(detail.drift_count || 0) > 0 ? 'has-drift' : ''}`}>
                      <div className="run-drift-card-title">{name}</div>
                      <div className="run-drift-card-count">{detail.drift_count || 0}</div>
                      <div className="run-drift-card-meta">
                        <span>ledger {detail.ledger_count ?? 0}</span>
                        <span>projection {detail.projection_count ?? 0}</span>
                        <span>missing {(detail.missing_in_projection || []).length}</span>
                        <span>stale {(detail.stale_in_projection || []).length}</span>
                        <span>mismatch {(detail.mismatches || []).length}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
        <div className="learn-run-sections">
          <div className="learn-run-section">
            <div className="learn-card-head">
              <h3>Interaction Runs <span className="muted">({interactionRuns.length})</span></h3>
              <span className="muted small">按问答终态语义展示，`non_task` 不再混入失败语义</span>
            </div>
            {interactionRuns.length === 0 ? (
              <p className="empty">暂无 interaction run 记录。</p>
            ) : (
              <table className="learn-runs-table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>问题</th>
                    <th>类型</th>
                    <th>结果</th>
                    <th>质量</th>
                    <th>置信</th>
                    <th>片段</th>
                    <th>迭代</th>
                    <th>工具</th>
                    <th>Drift</th>
                  </tr>
                </thead>
                <tbody>
                  {interactionRuns.map((r, i) => (
                    <tr key={r.run_id ?? i}>
                      <td className="ts-cell">{fmtDateTime(r.ts)}</td>
                      <td className="q-cell" title={r.query}>{r.query ?? '—'}</td>
                      <td><code>{TYPE_ZH[r.query_type ?? ''] ?? r.query_type ?? '—'}</code></td>
                      <td>
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                          {r.outcome_family && (
                            <span className="badge status-neutral">{OUTCOME_FAMILY_ZH[r.outcome_family] ?? r.outcome_family}</span>
                          )}
                          {r.outcome_code && <code>{r.outcome_code}</code>}
                        </div>
                      </td>
                      <td><span className={`badge q-${r.quality}`}>{QUALITY_ZH[r.quality] ?? r.quality}</span></td>
                      <td className="num">{r.evaluation?.confidence?.toFixed(2) ?? '—'}</td>
                      <td className="num">{r.chunks_count ?? 0}</td>
                      <td className="num">{r.iterations ?? 0}</td>
                      <td className="tools-cell">{(r.tools_used || []).join(', ') || '—'}</td>
                      <td>
                        {r.run_id ? (
                          <button className="run-drift-btn" onClick={() => inspectRunDrift(r.run_id)}>
                            Drift
                          </button>
                        ) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="learn-run-section">
            <div className="learn-card-head">
              <h3>Learning Loop Runs <span className="muted">({learningLoopRuns.length})</span></h3>
              <span className="muted small">来自 canonical lifecycle event，反映调度/执行状态而不是用户问答质量</span>
            </div>
            {learningLoopRuns.length === 0 ? (
              <p className="empty">暂无 learning-loop run 记录。</p>
            ) : (
              <table className="learn-runs-table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>运行 ID</th>
                    <th>触发方式</th>
                    <th>状态</th>
                    <th>事件</th>
                    <th>信号</th>
                    <th>问题</th>
                    <th>严重度</th>
                    <th>说明</th>
                    <th>Drift</th>
                  </tr>
                </thead>
                <tbody>
                  {learningLoopRuns.map((r, i) => (
                    <tr key={r.run_id ?? i}>
                      <td className="ts-cell">{fmtDateTime(r.ts)}</td>
                      <td><code>{r.run_id ?? '—'}</code></td>
                      <td>{RUN_TYPE_ZH[r.run_type ?? ''] ?? r.run_type ?? '—'}</td>
                      <td>{renderLearningRunStatusBadge(r.status)}</td>
                      <td><code>{r.event_type ?? '—'}</code></td>
                      <td className="num">
                        {Object.values(r.signal_summary || {}).reduce((sum, count) => sum + Number(count || 0), 0)}
                      </td>
                      <td className="num">{r.problems_count ?? '—'}</td>
                      <td className="num">{typeof r.severity_score === 'number' ? r.severity_score.toFixed(1) : '—'}</td>
                      <td className="q-cell" title={r.error || r.reason}>
                        {r.error || r.reason || '—'}
                      </td>
                      <td>
                        {r.run_id ? (
                          <button className="run-drift-btn" onClick={() => inspectRunDrift(r.run_id)}>
                            Drift
                          </button>
                        ) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </section>
      )}

      {/* 对话记录 */}
      {mainTab === 'conversations' && (
      <section className="learn-card learn-runs-card">
        <div className="learn-card-head">
          <h3>最近对话记录 <span className="muted">({conversations.length})</span></h3>
          <span className="muted small">来源：agent 问答 + 导览助手</span>
        </div>
        {conversations.length === 0 ? (
          <p className="empty">暂无对话记录。数据库中尚未储存任何会话轮次。</p>
        ) : (
          <table className="learn-runs-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>来源</th>
                <th>用户提问</th>
                <th>助手回答</th>
                <th>延迟 ms</th>
              </tr>
            </thead>
            <tbody>
              {conversations.map((c, i) => (
                <tr key={i}>
                  <td className="ts-cell">{fmtDateTime(c.ts)}</td>
                  <td><span className="badge q-good">{c.source}</span></td>
                  <td className="q-cell" title={c.user_content}>{c.user_content}</td>
                  <td className="q-cell" title={c.assistant_content}>{(c.assistant_content || '').slice(0, 80)}{c.assistant_content?.length > 80 ? '…' : ''}</td>
                  <td className="num">{c.latency_ms ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      )}

      {/* 反馈点评 */}
      {mainTab === 'feedback' && (
      <section className="learn-card learn-runs-card">
        <div className="learn-card-head">
          <h3>用户反馈点评 <span className="muted">({feedbackStats?.summary?.total ?? 0})</span></h3>
          <div className="muted small">
            👍 {feedbackStats?.summary?.positive ?? 0} · 👎 {feedbackStats?.summary?.negative ?? 0}
            {feedbackStats?.summary?.avg_overall_rating != null && ` · 平均总分 ${feedbackStats.summary.avg_overall_rating}`}
          </div>
        </div>

        {/* 趋势图 */}
        {(feedbackStats?.trend?.length ?? 0) > 0 && (
          <div className="fb-trend-chart">
            <div className="learn-card-head" style={{ paddingBottom: 8 }}>
              <h4 className="muted small">近 7 日好评趋势</h4>
            </div>
            <ResponsiveContainer width="100%" height={160}>
              <LineChart data={feedbackStats!.trend} margin={{ top: 4, right: 16, bottom: 0, left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="day" tick={{ fontSize: 11, fill: '#888' }} />
                <YAxis tick={{ fontSize: 11, fill: '#888' }} />
                <Tooltip
                  contentStyle={{ background: '#1a1208', border: '1px solid rgba(212,168,39,0.3)', borderRadius: 6 }}
                  labelStyle={{ color: '#d4a827' }}
                  itemStyle={{ color: '#ccc' }}
                />
                <Line type="monotone" dataKey="positive" name="好评" stroke="#d4a827" dot={false} strokeWidth={2} />
                <Line type="monotone" dataKey="total" name="总计" stroke="#888" dot={false} strokeDasharray="4 2" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* 标签分布 + 差评高亮 */}
        {(feedbackStats?.records?.length ?? 0) > 0 && (() => {
          const records = feedbackStats!.records;
          const tagCount = new Map<string, number>();
          records.forEach(r => (r.tags ?? []).forEach(t => tagCount.set(t, (tagCount.get(t) ?? 0) + 1)));
          const tagData = Array.from(tagCount.entries())
            .map(([tag, count]) => ({ tag, count }))
            .sort((a, b) => b.count - a.count)
            .slice(0, 10);
          const badReviews = records.filter(r => r.rating < 0 || (r.overall_rating != null && r.overall_rating <= 2));
          if (tagData.length === 0 && badReviews.length === 0) return null;
          return (
            <div className="fb-aux-row">
              {tagData.length > 0 && (
                <div className="fb-tag-dist">
                  <h4 className="muted small">标签分布（Top 10）</h4>
                  <ResponsiveContainer width="100%" height={Math.max(120, tagData.length * 24)}>
                    <BarChart data={tagData} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                      <XAxis type="number" tick={{ fontSize: 11, fill: '#888' }} allowDecimals={false} />
                      <YAxis type="category" dataKey="tag" width={110} tick={{ fontSize: 11, fill: '#ccc' }} />
                      <Tooltip
                        contentStyle={{ background: '#1a1208', border: '1px solid rgba(212,168,39,0.3)', borderRadius: 6 }}
                        labelStyle={{ color: '#d4a827' }}
                        itemStyle={{ color: '#ccc' }}
                      />
                      <Bar dataKey="count" name="次数" fill="#d4a827" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
              {badReviews.length > 0 && (
                <div className="fb-bad-list">
                  <h4 className="muted small">⚠️ 差评高亮 ({badReviews.length})</h4>
                  <ul className="bad-review-ul">
                    {badReviews.slice(0, 8).map((r, i) => (
                      <li key={i}>
                        <span className="bad-meta">{fmtDateTime(r.ts)}</span>
                        <span className="bad-score">总分 {r.overall_rating ?? (r.rating > 0 ? '+' : '−')}</span>
                        {r.criticism && <span className="bad-text">{r.criticism}</span>}
                        {!r.criticism && r.query && <span className="bad-text muted">Q: {r.query.slice(0, 80)}</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          );
        })()}

        {/* 反馈列表 */}
        {(feedbackStats?.records?.length ?? 0) === 0 ? (
          <p className="empty">暂无反馈记录。在问答页点击 👍/👎 并填写点评即可。</p>
        ) : (
          <table className="learn-runs-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>评价</th>
                <th>总分</th>
                <th>相关</th>
                <th>准确</th>
                <th>完整</th>
                <th>标签</th>
                <th>好评</th>
                <th>差评</th>
                <th>建议</th>
              </tr>
            </thead>
            <tbody>
              {feedbackStats!.records.map((r, i) => (
                <tr key={i}>
                  <td className="ts-cell">{fmtDateTime(r.ts)}</td>
                  <td>{r.rating > 0 ? '👍' : '👎'}</td>
                  <td className="num">{r.overall_rating ?? '—'}</td>
                  <td className="num">{r.rating_relevance ?? '—'}</td>
                  <td className="num">{r.rating_accuracy ?? '—'}</td>
                  <td className="num">{r.rating_completeness ?? '—'}</td>
                  <td className="tools-cell">{r.tags?.join(', ') ?? '—'}</td>
                  <td className="q-cell">{r.praise ?? '—'}</td>
                  <td className="q-cell">{r.criticism ?? '—'}</td>
                  <td className="q-cell">{r.suggestion ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      )}

      {/* 信号监控 */}
      {mainTab === 'signals' && signals && signalsSummary && (
      <section className="learn-card learn-signals-card">
        <div className="learn-card-head">
          <h3>📡 实时信号监控</h3>
          <span className="muted small">采集于 {fmtDateTime(signals.timestamp)}</span>
        </div>

        {/* 健康指示器 */}
        <div className="signal-health-indicator" data-status={signalsSummary.health_status}>
          <span className="status-icon">
            {signalsSummary.health_status === 'good' && '✅'}
            {signalsSummary.health_status === 'warning' && '⚠️'}
            {signalsSummary.health_status === 'critical' && '🚨'}
          </span>
          <span className="status-text">系统健康度: <strong>{signalsSummary.health_status}</strong></span>
        </div>

        {/* 信号卡片网格 */}
        <div className="signal-cards-grid">
          <div className="signal-card feedback">
            <div className="signal-count">{signalsSummary.signal_counts.feedback}</div>
            <div className="signal-label">用户反馈</div>
          </div>
          <div className="signal-card failure">
            <div className="signal-count">{signalsSummary.signal_counts.failures}</div>
            <div className="signal-label">失败信号</div>
          </div>
          <div className="signal-card repeat">
            <div className="signal-count">{signalsSummary.signal_counts.repeats}</div>
            <div className="signal-label">重复问题</div>
          </div>
          <div className="signal-card violation">
            <div className="signal-count">{signalsSummary.signal_counts.violations}</div>
            <div className="signal-label">合约违规</div>
          </div>
          <div className="signal-card topo">
            <div className="signal-count">{signalsSummary.signal_counts.topo}</div>
            <div className="signal-label">拓扑异常</div>
          </div>
        </div>

        {/* 严重度指数 */}
        <div className="severity-meter">
          <div className="meter-label">整体严重度指数</div>
          <div className="meter-bar">
            <div className="meter-fill" style={{ width: `${Math.min(signals.severity_score, 100)}%` }}></div>
          </div>
          <div className="meter-value">{signals.severity_score.toFixed(1)}/100</div>
        </div>

        {/* 采集统计 */}
        <div className="collection-stats">
          <div className="stat-item">
            <span className="stat-label">总信号数:</span>
            <span className="stat-value">{signals.total_count}</span>
          </div>
          <div className="stat-item">
            <span className="stat-label">采集耗时:</span>
            <span className="stat-value">{signals.collection_time_ms.toFixed(1)}ms</span>
          </div>
        </div>

        {/* 最新反馈信号 */}
        {signals.feedback_signals.length > 0 && (
          <div className="signal-details">
            <h4 className="muted small">最新反馈信号 (Top 5)</h4>
            <div className="signal-rows">
              {signals.feedback_signals.slice(0, 5).map((s, i) => (
                <div key={i} className="signal-row">
                  <span className="ts">{fmtDateTime(s.ts * 1000)}</span>
                  <span className="rating">⭐ {s.rating}/5</span>
                  <span className="tags">{s.tags.join(', ') || '—'}</span>
                  <span className="text">{(s.feedback_text || '—').substring(0, 60)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 最新失败信号 */}
        {signals.failure_signals.length > 0 && (
          <div className="signal-details">
            <h4 className="muted small">最新失败信号 (Top 5)</h4>
            <div className="signal-rows">
              {signals.failure_signals.slice(0, 5).map((s, i) => (
                <div key={i} className="signal-row">
                  <span className="ts">{fmtDateTime(s.ts * 1000)}</span>
                  <span className="status error">{s.status}</span>
                  <span className="latency">{s.latency_ms}ms</span>
                  <span className="session">{s.session_id.substring(0, 16)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
      )}

      {mainTab === 'signals' && !signals && (
      <section className="learn-card">
        <p className="empty">正在加载信号数据...</p>
      </section>
      )}

      {/* 问题诊断 Tab */}
      {mainTab === 'problems' && (
      <ProblemsPanel
        problems={problems}
      />
      )}

      {/* 待审核 Tab */}
      {mainTab === 'reviews' && (
      <ReviewsPanel
        reviews={historyEvents.filter(e => e.status === 'pending_review')}
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

      {/* 迭代历史 Tab */}
      {mainTab === 'history' && (
      <ImprovementHistoryPanel
        events={historyEvents}
        stats={learningStats}
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

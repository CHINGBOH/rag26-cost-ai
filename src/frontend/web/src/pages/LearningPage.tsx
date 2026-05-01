/**
 * 自学习看板 — 真实数据
 * 数据源：
 *   GET /api/v1/learning/summary   — 总览统计
 *   GET /api/v1/learning/runs      — 最近 agent run 明细
 *   GET /api/v1/learning/gaps      — 知识缺口（去重的失败/弱质量问题）
 */

import { useEffect, useState } from 'react';
import { PageHeader } from '../components/common/PageHeader';
import {
  getLearningSummary,
  getLearningRuns,
  getLearningGaps,
  getLearningBlindspots,
  LearningSummary,
  LearningRun,
  LearningGap,
  BlindspotCluster,
} from '../services/metricsApi';
import './LearningPage.css';
import { fmtDateTime } from '../utils/dateUtils';

type QualityFilter = 'all' | 'good' | 'weak' | 'failure';

const QUALITY_ZH: Record<string, string> = {
  good: '优质', weak: '弱', failure: '失败',
};
const TYPE_ZH: Record<string, string> = {
  standard_ref: '标准查询', price: '价格查询', trend_chart: '趋势图表',
  comparison: '对比分析', calculation: '计算推理', semantic: '语义检索',
};

export const LearningPage: React.FC = () => {
  const [summary, setSummary] = useState<LearningSummary | null>(null);
  const [runs, setRuns] = useState<LearningRun[]>([]);
  const [gaps, setGaps] = useState<LearningGap[]>([]);
  const [blindspots, setBlindspots] = useState<BlindspotCluster[]>([]);
  const [filter, setFilter] = useState<QualityFilter>('all');
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    const [s, r, g, b] = await Promise.all([
      getLearningSummary(),
      getLearningRuns(50, filter === 'all' ? undefined : filter),
      getLearningGaps(20),
      getLearningBlindspots(2),
    ]);
    setSummary(s);
    setRuns(r);
    setGaps(g);
    setBlindspots(b?.clusters || []);
    setLoading(false);
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
        {/* 知识缺口 */}
        <section className="learn-card learn-gaps">
          <div className="learn-card-head">
            <h3>知识缺口 <span className="muted">({gaps.length})</span></h3>
            <span className="muted small">去重的失败/弱问题，按时间倒序</span>
          </div>
          {gaps.length === 0 ? (
            <p className="empty">暂无识别到的知识缺口 — 当前所有运行均良好。</p>
          ) : (
            <ul className="gap-list">
              {gaps.map((g, i) => (
                <li key={i} className={`gap-item q-${g.quality}`}>
                  <div className="gap-q">{g.query}</div>
                  <div className="gap-meta">
                    <span className={`badge q-${g.quality}`}>{QUALITY_ZH[g.quality] ?? g.quality}</span>
                    {g.refused && <span className="badge refused">拒答</span>}
                    <span className="muted small">片段 {g.chunks_count}</span>
                    <span className="muted small">置信 {g.confidence.toFixed(2)}</span>
                    <span className="muted small">{fmtDateTime(g.ts)}</span>
                  </div>
                  {g.answer_preview && (
                    <details>
                      <summary className="muted small">查看答案预览</summary>
                      <p className="gap-preview">{g.answer_preview}</p>
                    </details>
                  )}
                </li>
              ))}
            </ul>
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

      {/* 运行明细 */}
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
        {runs.length === 0 ? (
          <p className="empty">暂无运行记录。在 Agent 或运行时页面提问即可生成。</p>
        ) : (
          <table className="learn-runs-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>问题</th>
                <th>类型</th>
                <th>质量</th>
                <th>置信</th>
                <th>片段</th>
                <th>迭代</th>
                <th>工具</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r, i) => (
                <tr key={i}>
                  <td className="ts-cell">{fmtDateTime(r.ts)}</td>
                  <td className="q-cell" title={r.query}>{r.query}</td>
                  <td><code>{TYPE_ZH[r.query_type] ?? r.query_type ?? '—'}</code></td>
                  <td><span className={`badge q-${r.quality}`}>{QUALITY_ZH[r.quality] ?? r.quality}</span></td>
                  <td className="num">{r.evaluation.confidence.toFixed(2)}</td>
                  <td className="num">{r.chunks_count}</td>
                  <td className="num">{r.iterations}</td>
                  <td className="tools-cell">{(r.tools_used || []).join(', ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
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

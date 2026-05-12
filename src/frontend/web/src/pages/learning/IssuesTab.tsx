import React from 'react';
import { ProblemsPanel } from '../../components/learning/ProblemsPanel';
import {
  LearningRun,
  ConversationTurn,
  FeedbackStats,
  ProblemReport,
} from '../../services/metricsApi';
import { fmtDateTime } from '../../utils/dateUtils';
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
import {
  QualityFilter,
  QUALITY_ZH,
  TYPE_ZH,
  OUTCOME_FAMILY_ZH,
  RUN_TYPE_ZH,
  renderLearningRunStatusBadge,
} from '../learning-i18n';

interface IssuesTabProps {
  problems: ProblemReport[];
  interactionRuns: LearningRun[];
  learningLoopRuns: LearningRun[];
  conversations: ConversationTurn[];
  feedbackStats: FeedbackStats | null;
  filter: QualityFilter;
  onFilterChange: (f: QualityFilter) => void;
}

export const IssuesTab: React.FC<IssuesTabProps> = ({
  problems,
  interactionRuns,
  learningLoopRuns,
  conversations,
  feedbackStats,
  filter,
  onFilterChange,
}) => {
  const FILTER_LABEL: Record<QualityFilter, string> = {
    all: '全部',
    good: QUALITY_ZH.good,
    weak: QUALITY_ZH.weak,
    failure: QUALITY_ZH.failure,
  };
  return (
    <>
      <ProblemsPanel problems={problems} />

      <section className="learn-card learn-runs-card">
        <div className="learn-card-head">
          <h3>最近 agent 运行</h3>
          <div className="filter-tabs">
            {(['all', 'good', 'weak', 'failure'] as QualityFilter[]).map((f) => (
              <button
                key={f}
                className={filter === f ? 'active' : ''}
                onClick={() => onFilterChange(f)}
              >
                {FILTER_LABEL[f]}
              </button>
            ))}
          </div>
        </div>
        <div className="learn-run-sections">
          <div className="learn-run-section">
            <div className="learn-card-head">
              <h3>
                Interaction Runs <span className="muted">({interactionRuns.length})</span>
              </h3>
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
                  </tr>
                </thead>
                <tbody>
                  {interactionRuns.map((r, i) => (
                    <tr key={r.run_id ?? i}>
                      <td className="ts-cell">{fmtDateTime(r.ts)}</td>
                      <td className="q-cell" title={r.query}>
                        {r.query ?? '—'}
                      </td>
                      <td>
                        <code>{TYPE_ZH[r.query_type ?? ''] ?? r.query_type ?? '—'}</code>
                      </td>
                      <td title={r.outcome_code ? `outcome_code：${r.outcome_code}` : undefined}>
                        {r.outcome_family ? (
                          <span className="badge status-neutral">
                            {OUTCOME_FAMILY_ZH[r.outcome_family] ?? r.outcome_family}
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td>
                        <span className={`badge q-${r.quality}`}>
                          {QUALITY_ZH[r.quality] ?? r.quality}
                        </span>
                      </td>
                      <td className="num">{r.evaluation?.confidence?.toFixed(2) ?? '—'}</td>
                      <td className="num">{r.chunks_count ?? 0}</td>
                      <td className="num">{r.iterations ?? 0}</td>
                      <td className="tools-cell">{(r.tools_used || []).join(', ') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="learn-run-section">
            <div className="learn-card-head">
              <h3>
                Learning Loop Runs <span className="muted">({learningLoopRuns.length})</span>
              </h3>
              <span className="muted small">
                来自 canonical lifecycle event，反映调度/执行状态而不是用户问答质量
              </span>
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
                  </tr>
                </thead>
                <tbody>
                  {learningLoopRuns.map((r, i) => (
                    <tr key={r.run_id ?? i}>
                      <td className="ts-cell">{fmtDateTime(r.ts)}</td>
                      <td>
                        <code>{r.run_id ?? '—'}</code>
                      </td>
                      <td>{RUN_TYPE_ZH[r.run_type ?? ''] ?? r.run_type ?? '—'}</td>
                      <td>{renderLearningRunStatusBadge(r.status)}</td>
                      <td>
                        <code>{r.event_type ?? '—'}</code>
                      </td>
                      <td className="num">
                        {Object.values(r.signal_summary || {}).reduce(
                          (sum, count) => sum + Number(count || 0),
                          0,
                        )}
                      </td>
                      <td className="num">{r.problems_count ?? '—'}</td>
                      <td className="num">
                        {typeof r.severity_score === 'number'
                          ? r.severity_score.toFixed(1)
                          : '—'}
                      </td>
                      <td className="q-cell" title={r.error || r.reason}>
                        {r.error || r.reason || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </section>

      <section className="learn-card learn-runs-card">
        <div className="learn-card-head">
          <h3>
            最近对话记录 <span className="muted">({conversations.length})</span>
          </h3>
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
                  <td>
                    <span className="badge q-good">{c.source}</span>
                  </td>
                  <td className="q-cell" title={c.user_content}>
                    {c.user_content}
                  </td>
                  <td className="q-cell" title={c.assistant_content}>
                    {(c.assistant_content || '').slice(0, 80)}
                    {c.assistant_content?.length > 80 ? '…' : ''}
                  </td>
                  <td className="num">{c.latency_ms ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="learn-card learn-runs-card">
        <div className="learn-card-head">
          <h3>
            用户反馈点评 <span className="muted">({feedbackStats?.summary?.total ?? 0})</span>
          </h3>
          <div className="muted small">
            👍 {feedbackStats?.summary?.positive ?? 0} · 👎{' '}
            {feedbackStats?.summary?.negative ?? 0}
            {feedbackStats?.summary?.avg_overall_rating != null &&
              ` · 平均总分 ${feedbackStats.summary.avg_overall_rating}`}
          </div>
        </div>

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
                  contentStyle={{
                    background: '#1a1208',
                    border: '1px solid rgba(212,168,39,0.3)',
                    borderRadius: 6,
                  }}
                  labelStyle={{ color: '#d4a827' }}
                  itemStyle={{ color: '#ccc' }}
                />
                <Line type="monotone" dataKey="positive" name="好评" stroke="#d4a827" dot={false} strokeWidth={2} />
                <Line
                  type="monotone"
                  dataKey="total"
                  name="总计"
                  stroke="#888"
                  dot={false}
                  strokeDasharray="4 2"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {(feedbackStats?.records?.length ?? 0) > 0 &&
          (() => {
            const records = feedbackStats!.records;
            const tagCount = new Map<string, number>();
            records.forEach((r) =>
              (r.tags ?? []).forEach((t) => tagCount.set(t, (tagCount.get(t) ?? 0) + 1)),
            );
            const tagData = Array.from(tagCount.entries())
              .map(([tag, count]) => ({ tag, count }))
              .sort((a, b) => b.count - a.count)
              .slice(0, 10);
            const badReviews = records.filter(
              (r) => r.rating < 0 || (r.overall_rating != null && r.overall_rating <= 2),
            );
            if (tagData.length === 0 && badReviews.length === 0) return null;
            return (
              <div className="fb-aux-row">
                {tagData.length > 0 && (
                  <div className="fb-tag-dist">
                    <h4 className="muted small">标签分布（Top 10）</h4>
                    <ResponsiveContainer width="100%" height={Math.max(120, tagData.length * 24)}>
                      <BarChart
                        data={tagData}
                        layout="vertical"
                        margin={{ top: 4, right: 16, bottom: 0, left: 8 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                        <XAxis type="number" tick={{ fontSize: 11, fill: '#888' }} allowDecimals={false} />
                        <YAxis
                          type="category"
                          dataKey="tag"
                          width={110}
                          tick={{ fontSize: 11, fill: '#ccc' }}
                        />
                        <Tooltip
                          contentStyle={{
                            background: '#1a1208',
                            border: '1px solid rgba(212,168,39,0.3)',
                            borderRadius: 6,
                          }}
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
                          <span className="bad-score">
                            总分 {r.overall_rating ?? (r.rating > 0 ? '+' : '−')}
                          </span>
                          {r.criticism && <span className="bad-text">{r.criticism}</span>}
                          {!r.criticism && r.query && (
                            <span className="bad-text muted">Q: {r.query.slice(0, 80)}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            );
          })()}

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
    </>
  );
};

export default IssuesTab;

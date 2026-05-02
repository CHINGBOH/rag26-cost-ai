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
  getConversations,
  getFeedbackStats,
  getLearningEngine,
  LearningSummary,
  LearningRun,
  LearningGap,
  BlindspotCluster,
  ConversationTurn,
  FeedbackStats,
  LearningEngineStatus,
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
type MainTab = 'runs' | 'conversations' | 'feedback';

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
  const [conversations, setConversations] = useState<ConversationTurn[]>([]);
  const [feedbackStats, setFeedbackStats] = useState<FeedbackStats | null>(null);
  const [engine, setEngine] = useState<LearningEngineStatus | null>(null);
  const [filter, setFilter] = useState<QualityFilter>('all');
  const [mainTab, setMainTab] = useState<MainTab>('runs');
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    const [s, r, g, b, convs, fb, eng] = await Promise.all([
      getLearningSummary(),
      getLearningRuns(50, filter === 'all' ? undefined : filter),
      getLearningGaps(20),
      getLearningBlindspots(2),
      getConversations(50),
      getFeedbackStats(100),
      getLearningEngine(),
    ]);
    setSummary(s);
    setRuns(r);
    setGaps(g);
    setBlindspots(b?.clusters || []);
    setConversations(convs);
    setFeedbackStats(fb);
    setEngine(eng);
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

      {/* 学习引擎 — 触发条件透明化 */}
      <section className="learn-card learn-engine-card" style={{ marginTop: 16 }}>
        <div className="learn-card-head">
          <h3>🧠 学习引擎</h3>
          <span className="muted small">
            {engine ? `触发模式：${engine.trigger_mode === 'manual' ? '手动' : engine.trigger_mode}` : '加载中…'}
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
        {([['runs', 'Agent 运行轨迹'], ['conversations', '问答记录'], ['feedback', '反馈与趋势']] as [MainTab, string][]).map(([t, label]) => (
          <button key={t} className={mainTab === t ? 'active' : ''} onClick={() => setMainTab(t)}>
            {label}
          </button>
        ))}
      </div>

      {/* Tab 简介 */}
      <p className="muted small" style={{ marginTop: -4, marginBottom: 12 }}>
        {mainTab === 'runs' && '🔍 Agent 内部节点级执行轨迹（query_analysis → retrieval → synthesize → verify），用于排查质量问题。'}
        {mainTab === 'conversations' && '💬 用户每一轮 Q&A 原始记录（conversation_turns 表），是迭代的第一手素材。'}
        {mainTab === 'feedback' && '⭐ 用户的 👍👎 + 1-5 星评分 + 文字点评（rag_feedback 表），驱动模型/检索改进。'}
      </p>

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

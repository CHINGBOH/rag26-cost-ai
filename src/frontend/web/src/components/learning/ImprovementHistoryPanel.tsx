import React, { useMemo } from 'react';
import { ImprovementEvent } from '../../services/metricsApi';
import { fmtDateTime } from '../../utils/dateUtils';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import './ImprovementHistoryPanel.css';

interface ImprovementHistoryPanelProps {
  events: ImprovementEvent[];
  stats: any;
}

const STATUS_LABELS: Record<string, string> = {
  pending_review: '📋 待审核',
  approved: '🕓 已批准',
  applied: '▶️ 已应用',
  verified: '✅ 已验证',
  reverted: '↩️ 已还原',
  rejected: '🚫 已拒绝',
  failed: '❌ 失败',
};

const REVIEW_LABELS: Record<string, string> = {
  pending_review: '待审核',
  approved: '已批准',
  rejected: '已拒绝',
};

const GAP_LABELS: Record<string, string> = {
  open: '未开始',
  in_progress: '处理中',
  observing: '观察期',
  resolved: '已解决',
  blocked: '已阻塞',
};

const SOURCE_KIND_ZH: Record<string, string> = {
  auto: '自动',
  human: '人工',
  external: '外部',
};

const RISK_ZH: Record<string, string> = {
  low: '低',
  mid: '中',
  medium: '中',
  high: '高',
};

const CAUSE_TYPE_ZH: Record<string, string> = {
  prompt_drift: '提示漂移',
  retrieval_miss: '检索缺失',
  tool_failure: '工具失败',
  routing_error: '路由错误',
  data_gap: '数据缺失',
  policy_mismatch: '策略不符',
  low_quality_output: '输出质量低',
  diversity_low: '多样性不足',
  unknown: '未知',
};

const VERIFICATION_STATUS_ZH: Record<string, string> = {
  passed: '✅ 通过',
  failed: '❌ 未通过',
  pending: '⏳ 待验证',
  skipped: '⏭ 已跳过',
};

const SCOPE_ZH: Record<string, string> = {
  user: '用户',
  agent: 'Agent',
  project: '项目',
  global: '全局',
};

function formatPercent(value?: number | null): string {
  return `${((value ?? 0) * 100).toFixed(1)}%`;
}

function renderLifecycleStatus(event: ImprovementEvent) {
  return STATUS_LABELS[event.status] ?? event.status;
}

export const ImprovementHistoryPanel: React.FC<ImprovementHistoryPanelProps> = ({ events, stats }) => {
  // 为图表准备数据
  const chartData = useMemo(() => {
    return events.map((e) => ({
      timestamp: fmtDateTime(e.timestamp),
      before: e.before_rate,
      after: e.after_rate,
      improvement: e.delta,
    }));
  }, [events]);

  return (
    <div className="improvement-history-panel">
      {/* 统计摘要 */}
      <div className="stats-summary">
        <div className="stat-card">
          <span className="label">总修复数</span>
          <span className="value">{stats?.summary?.total_events || 0}</span>
        </div>
        <div className="stat-card success">
          <span className="label">成功修复</span>
          <span className="value">{stats?.summary?.successful || 0}</span>
        </div>
        <div className="stat-card failed">
          <span className="label">失败修复</span>
          <span className="value">{stats?.summary?.failed || 0}</span>
        </div>
        <div className="stat-card reverted">
          <span className="label">已还原</span>
          <span className="value">{stats?.summary?.reverted || 0}</span>
        </div>
        <div className="stat-card improvement">
          <span className="label">累计改进</span>
          <span className="value">+{stats?.effectiveness?.total_improvement?.toFixed(2) || 0}</span>
        </div>
      </div>

      {/* 成功率趋势图 */}
      {chartData.length > 0 && (
        <div className="chart-container">
          <h3>成功率趋势</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="timestamp" />
              <YAxis />
              <Tooltip formatter={(value: any) => `${(Number(value) * 100).toFixed(1)}%`} />
              <Legend />
              <Line type="monotone" dataKey="before" stroke="var(--color-info)" name="修改前" />
              <Line type="monotone" dataKey="after" stroke="var(--color-success)" name="修改后" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* 历史详情表格 */}
      <div className="history-table">
        <h3>修复详情</h3>
        {events.length === 0 ? (
          <p className="empty">暂无修复历史</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>时间</th>
                <th>生命周期</th>
                <th>策略</th>
                <th>验证结果</th>
                <th>Gap 联动</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.event_id} className={`status-${e.status}`}>
                  <td className="history-time-cell">
                    <div>{fmtDateTime(e.timestamp)}</div>
                    <div className="history-subtle">事件 #{e.event_id}</div>
                    {e.created_at && e.created_at !== e.timestamp && (
                      <div className="history-subtle">创建于 {fmtDateTime(e.created_at)}</div>
                    )}
                  </td>
                  <td className="history-lifecycle-cell">
                    <span className={`history-status-pill status-${e.status}`}>{renderLifecycleStatus(e)}</span>
                    <div className="history-detail-list">
                      <div>
                        <strong>来源：</strong>
                        {SOURCE_KIND_ZH[e.source?.kind ?? ''] ?? e.source?.kind ?? '—'}
                        {' / '}
                        {e.source?.actor ?? '—'}
                      </div>
                      <div><strong>审核：</strong>{REVIEW_LABELS[e.review?.status ?? ''] ?? (e.review?.status ?? '—')}</div>
                      {e.review?.reviewer && <div><strong>审核人：</strong>{e.review.reviewer}</div>}
                      {e.review?.note && <div className="history-note">{e.review.note}</div>}
                    </div>
                  </td>
                  <td className="history-strategy-cell">
                    <div className="history-action">{e.action}</div>
                    <div className="history-detail-list">
                      <div><strong>路径：</strong><code>{e.route}</code></div>
                      {e.problem_id && <div><strong>问题：</strong><code>{e.problem_id}</code></div>}
                      {e.source?.source_run_id && <div><strong>关联运行：</strong><code>{e.source.source_run_id}</code></div>}
                      {e.strategy?.risk_level && (
                        <div>
                          <strong>风险：</strong>
                          {RISK_ZH[e.strategy.risk_level] ?? e.strategy.risk_level}
                        </div>
                      )}
                      {e.strategy?.root_cause_type && (
                        <div title={`后端字段：${e.strategy.root_cause_type}`}>
                          <strong>成因：</strong>
                          {CAUSE_TYPE_ZH[e.strategy.root_cause_type] ?? e.strategy.root_cause_type}
                        </div>
                      )}
                      {e.strategy?.decision && (
                        <div className="history-subtle" title={`后端字段：${e.strategy.decision}`}>
                          <strong>处置：</strong>
                          {e.strategy.decision === 'auto_apply'
                            ? '自动应用'
                            : e.strategy.decision === 'pending_review'
                            ? '待审核'
                            : e.strategy.decision === 'manual_only'
                            ? '人工决策'
                            : e.strategy.decision}
                        </div>
                      )}
                    </div>
                  </td>
                  <td className="history-verification-cell">
                    <div className="history-metric-row">
                      <span>{formatPercent(e.before_rate)}</span>
                      <span>→</span>
                      <span>{formatPercent(e.after_rate)}</span>
                    </div>
                    <div className={`delta ${e.delta < 0 ? 'negative' : e.delta === 0 ? 'neutral' : ''}`}>
                      {e.delta > 0 ? '+' : ''}{formatPercent(e.delta)}
                    </div>
                    <div className="history-detail-list">
                      <div>
                        <strong>验证：</strong>
                        {VERIFICATION_STATUS_ZH[e.verification?.status ?? ''] ?? (e.verification?.status ?? '—')}
                      </div>
                      {typeof e.verification?.improved === 'boolean' && (
                        <div><strong>是否改善：</strong>{e.verification.improved ? '是' : '否'}</div>
                      )}
                      {e.execution_time > 0 && <div><strong>耗时：</strong>{e.execution_time}ms</div>}
                      {e.verification?.error && <div className="history-error">{e.verification.error}</div>}
                      {e.revert_reason && <div className="history-note">回滚/审核备注：{e.revert_reason}</div>}
                    </div>
                  </td>
                  <td className="history-gap-cell">
                    {e.gap?.gap_key ? (
                      <div className="history-detail-list">
                        <div><strong>缺口键：</strong><code>{e.gap.gap_key}</code></div>
                        <div><strong>状态：</strong>{GAP_LABELS[e.gap.status ?? ''] ?? (e.gap.status ?? '—')}</div>
                        {e.gap.scope_type && (
                          <div title={`后端字段：${e.gap.scope_type}`}>
                            <strong>范围：</strong>{SCOPE_ZH[e.gap.scope_type] ?? e.gap.scope_type}
                          </div>
                        )}
                        {e.gap.owner && <div><strong>负责人：</strong>{e.gap.owner}</div>}
                        {typeof e.gap.reopen_count === 'number' && e.gap.reopen_count > 0 && (
                          <div><strong>重开次数：</strong>{e.gap.reopen_count}</div>
                        )}
                        {e.gap.observation_until && (
                          <div><strong>观察至：</strong>{fmtDateTime(e.gap.observation_until)}</div>
                        )}
                      </div>
                    ) : (
                      <span className="history-subtle">未关联知识缺口</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};

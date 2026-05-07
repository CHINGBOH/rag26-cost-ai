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
  open: 'Open',
  in_progress: 'In Progress',
  observing: 'Observing',
  resolved: 'Resolved',
  blocked: 'Blocked',
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
              <Line type="monotone" dataKey="before" stroke="#3498db" name="修改前" />
              <Line type="monotone" dataKey="after" stroke="#2ecc71" name="修改后" />
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
                    <div className="history-subtle">Event #{e.event_id}</div>
                    {e.created_at && e.created_at !== e.timestamp && (
                      <div className="history-subtle">创建于 {fmtDateTime(e.created_at)}</div>
                    )}
                  </td>
                  <td className="history-lifecycle-cell">
                    <span className={`history-status-pill status-${e.status}`}>{renderLifecycleStatus(e)}</span>
                    <div className="history-detail-list">
                      <div><strong>Source:</strong> {e.source?.kind ?? '—'} / {e.source?.actor ?? '—'}</div>
                      <div><strong>Review:</strong> {REVIEW_LABELS[e.review?.status ?? ''] ?? (e.review?.status ?? '—')}</div>
                      {e.review?.reviewer && <div><strong>Reviewer:</strong> {e.review.reviewer}</div>}
                      {e.review?.note && <div className="history-note">{e.review.note}</div>}
                    </div>
                  </td>
                  <td className="history-strategy-cell">
                    <div className="history-action">{e.action}</div>
                    <div className="history-detail-list">
                      <div><strong>Route:</strong> <code>{e.route}</code></div>
                      {e.problem_id && <div><strong>Problem:</strong> <code>{e.problem_id}</code></div>}
                      {e.source?.source_run_id && <div><strong>Run:</strong> <code>{e.source.source_run_id}</code></div>}
                      {e.strategy?.decision && <div><strong>Decision:</strong> {e.strategy.decision}</div>}
                      {e.strategy?.risk_level && <div><strong>Risk:</strong> {e.strategy.risk_level}</div>}
                      {e.strategy?.root_cause_type && <div><strong>Cause:</strong> {e.strategy.root_cause_type}</div>}
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
                      <div><strong>Verification:</strong> {e.verification?.status ?? '—'}</div>
                      {typeof e.verification?.improved === 'boolean' && (
                        <div><strong>Improved:</strong> {e.verification.improved ? 'Yes' : 'No'}</div>
                      )}
                      {e.execution_time > 0 && <div><strong>Duration:</strong> {e.execution_time}ms</div>}
                      {e.verification?.error && <div className="history-error">{e.verification.error}</div>}
                      {e.revert_reason && <div className="history-note">Revert/Review note: {e.revert_reason}</div>}
                    </div>
                  </td>
                  <td className="history-gap-cell">
                    {e.gap?.gap_key ? (
                      <div className="history-detail-list">
                        <div><strong>Gap:</strong> <code>{e.gap.gap_key}</code></div>
                        <div><strong>Status:</strong> {GAP_LABELS[e.gap.status ?? ''] ?? (e.gap.status ?? '—')}</div>
                        {e.gap.scope_type && <div><strong>Scope:</strong> {e.gap.scope_type}</div>}
                        {e.gap.owner && <div><strong>Owner:</strong> {e.gap.owner}</div>}
                        {typeof e.gap.reopen_count === 'number' && e.gap.reopen_count > 0 && (
                          <div><strong>Reopened:</strong> {e.gap.reopen_count}</div>
                        )}
                        {e.gap.observation_until && (
                          <div><strong>Observe until:</strong> {fmtDateTime(e.gap.observation_until)}</div>
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

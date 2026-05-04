import React, { useMemo } from 'react';
import { ImprovementEvent } from '../../services/metricsApi';
import { fmtDateTime } from '../../utils/dateUtils';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import './ImprovementHistoryPanel.css';

interface ImprovementHistoryPanelProps {
  events: ImprovementEvent[];
  stats: any;
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
                <th>操作</th>
                <th>影响路由</th>
                <th>修改前</th>
                <th>修改后</th>
                <th>改进</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.event_id} className={`status-${e.status}`}>
                  <td>{fmtDateTime(e.timestamp)}</td>
                  <td>{e.action}</td>
                  <td>{e.route}</td>
                  <td>{(e.before_rate * 100).toFixed(1)}%</td>
                  <td>{(e.after_rate * 100).toFixed(1)}%</td>
                  <td className="delta">
                    {e.delta > 0 ? '+' : ''}{(e.delta * 100).toFixed(1)}%
                  </td>
                  <td>
                    {e.status === 'verified' ? '✅ 已验证' : e.status === 'reverted' ? '↩️ 已还原' : e.status === 'applied' ? '▶️ 已应用' : '❌ 失败'}
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

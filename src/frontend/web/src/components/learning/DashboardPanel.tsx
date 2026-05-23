import React from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { LearningDashboard } from '../../services/metricsApi';
import './DashboardPanel.css';

interface DashboardPanelProps {
  dashboard: LearningDashboard | null;
}

export const DashboardPanel: React.FC<DashboardPanelProps> = ({ dashboard }) => {
  if (!dashboard) return <div className="loading">⏳ 加载看板中...</div>;

  const { improvement_trend, alerts, recent_events } = dashboard;

  return (
    <div className="dashboard-panel">
      {/* 告警 */}
      {alerts.length > 0 && (
        <div className="alerts-section">
          <h3>⚠️ 告警 ({alerts.length})</h3>
          <div className="alerts-list">
            {alerts.map((alert, i) => (
              <div key={i} className={`alert alert-${alert.severity}`}>
                <span className="severity-icon">
                  {alert.severity === 'critical' ? '🚨' : '⚠️'}
                </span>
                <span className="message">{alert.message}</span>
                <span className="time">
                  {new Date(alert.created_at).toLocaleTimeString('zh-CN')}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 改进趋势图 */}
      {improvement_trend.length > 0 && (
        <div className="chart-container">
          <h3>📈 近 30 天表现</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={improvement_trend}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis 
                dataKey="date" 
                angle={-45}
                textAnchor="end"
                height={60}
              />
              <YAxis yAxisId="left" label={{ value: '答对比例', angle: -90, position: 'insideLeft' }} />
              <YAxis
                yAxisId="right"
                orientation="right"
                label={{ value: '修好的问题', angle: 90, position: 'insideRight' }}
              />
              <Tooltip
                contentStyle={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-default)' }}
                formatter={(value, name) => {
                  if (name === '答对比例') return [Number(value).toFixed(2), '答对比例'];
                  if (name === '修好的问题') return [value, '修好的问题'];
                  return [value, name];
                }}
              />
              <Legend />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="rate"
                stroke="var(--color-success)"
                name="答对比例"
                strokeWidth={2}
                dot={{ r: 4 }}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="fixed"
                stroke="var(--color-info)"
                name="修好的问题"
                strokeWidth={2}
                dot={{ r: 4 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* 最近做过的事 */}
      {recent_events.length > 0 && (
        <div className="recent-events">
          <h3>🕐 最近做过的事 ({recent_events.length})</h3>
          <div className="events-list">
            {recent_events.slice(0, 8).map((event, i) => {
              const statusText =
                event.status === 'verified' ? '✅ 已验证' :
                event.status === 'pending_review' ? '📋 等批准' :
                event.status === 'approved' ? '🕓 已批准' :
                event.status === 'applied' ? '📝 已生效' :
                event.status === 'rejected' ? '🚫 已拒绝' :
                event.status === 'reverted' ? '↩️ 已撤销' :
                '⏳ 处理中';
              return (
                <div key={i} className={`event-item status-${event.status}`}>
                  <div className="event-time">
                    {event.timestamp
                      ? new Date(event.timestamp).toLocaleTimeString('zh-CN')
                      : '—'}
                  </div>
                  <div className="event-content">
                    <div className={`event-status status-${event.status}`}>{statusText}</div>
                    <details className="event-tech-detail">
                      <summary>看技术细节</summary>
                      <div className="event-route"><code>{event.route}</code></div>
                      <div className="event-description">{event.description}</div>
                    </details>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {improvement_trend.length === 0 && recent_events.length === 0 && !alerts.length && (
        <div className="empty-state">
          <p>📊 看板数据加载中或暂无数据</p>
          <p className="hint">当学习系统运行时数据会自动更新</p>
        </div>
      )}
    </div>
  );
};

export default DashboardPanel;

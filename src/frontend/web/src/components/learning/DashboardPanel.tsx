import React, { useEffect, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import './DashboardPanel.css';

interface HealthMetrics {
  status: 'good' | 'warning' | 'critical';
  score: number;
  last_check: number;
}

interface KeyMetrics {
  last_run: number | null;
  next_run: number | null;
  running: boolean;
  pending_approvals: number;
}

interface Alert {
  severity: 'warning' | 'critical';
  message: string;
  created_at: number;
  acknowledged: boolean;
}

interface TrendData {
  date: string;
  rate: number;
  problems: number;
  fixed: number;
}

interface RecentEvent {
  timestamp: number | null;
  route: string;
  description: string;
  status: 'verified' | 'applied' | 'reverted' | 'pending';
}

interface DashboardData {
  health: HealthMetrics;
  key_metrics: KeyMetrics;
  improvement_trend: TrendData[];
  alerts: Alert[];
  recent_events: RecentEvent[];
}

export const DashboardPanel: React.FC = () => {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDashboard = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await fetch('/api/v1/learning/dashboard');
      if (!response.ok) throw new Error('Failed to fetch dashboard');
      const data = await response.json();
      setDashboard(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setError(message);
      console.error('Dashboard fetch error:', message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboard();
    // 每 30 秒刷新一次
    const interval = setInterval(fetchDashboard, 30000);
    return () => clearInterval(interval);
  }, []);

  if (error) {
    return (
      <div className="dashboard-error">
        <p>❌ 加载看板失败: {error}</p>
        <button onClick={fetchDashboard}>重试</button>
      </div>
    );
  }

  if (loading || !dashboard) return <div className="loading">⏳ 加载看板中...</div>;

  const { health, key_metrics, improvement_trend, alerts, recent_events } = dashboard;

  const healthColor = 
    health.status === 'good' ? '#2ecc71' : 
    health.status === 'warning' ? '#f39c12' : 
    '#e74c3c';
  
  const healthEmoji = 
    health.status === 'good' ? '✅' : 
    health.status === 'warning' ? '⚠️' : 
    '🚨';

  return (
    <div className="dashboard-panel">
      {/* 健康度指示 */}
      <div className="health-card" style={{ borderLeftColor: healthColor }}>
        <div className="health-emoji">{healthEmoji}</div>
        <div className="health-info">
          <h3>系统健康度</h3>
          <div className="health-score">
            <div className="score-number">{health.score}</div>
            <div className="score-bar">
              <div className="fill" style={{ width: `${health.score}%`, backgroundColor: healthColor }}></div>
            </div>
            <div className="score-text">
              {health.status === 'good' ? '运行正常' : health.status === 'warning' ? '需要关注' : '需要紧急处理'}
            </div>
          </div>
        </div>
      </div>

      {/* 关键指标 */}
      <div className="key-metrics-grid">
        <div className="metric-card">
          <span className="label">待审核</span>
          <span className={`value ${key_metrics.pending_approvals > 0 ? 'warning' : ''}`}>
            {key_metrics.pending_approvals}
          </span>
          <span className="hint">个待审核项</span>
        </div>
        <div className="metric-card">
          <span className="label">最后运行</span>
          <span className="value">
            {key_metrics.last_run 
              ? new Date(key_metrics.last_run).toLocaleDateString('zh-CN')
              : '从未'
            }
          </span>
          <span className="hint">时间</span>
        </div>
        <div className="metric-card">
          <span className="label">系统状态</span>
          <span className={`value ${key_metrics.running ? 'running' : 'idle'}`}>
            {key_metrics.running ? '🔄 运行中' : '✓ 就绪'}
          </span>
          <span className="hint">当前状态</span>
        </div>
      </div>

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
          <h3>📊 成功率趋势（30 天）</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={improvement_trend}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis 
                dataKey="date" 
                angle={-45}
                textAnchor="end"
                height={60}
              />
              <YAxis yAxisId="left" label={{ value: '成功率', angle: -90, position: 'insideLeft' }} />
              <YAxis 
                yAxisId="right" 
                orientation="right" 
                label={{ value: '修复数', angle: 90, position: 'insideRight' }}
              />
              <Tooltip 
                contentStyle={{ backgroundColor: '#fff', border: '1px solid #ddd' }}
                formatter={(value, name) => {
                  if (name === 'rate') return [Number(value).toFixed(2), '成功率'];
                  if (name === 'fixed') return [value, '修复数'];
                  return [value, name];
                }}
              />
              <Legend />
              <Line 
                yAxisId="left" 
                type="monotone" 
                dataKey="rate" 
                stroke="#2ecc71" 
                name="成功率"
                strokeWidth={2}
                dot={{ r: 4 }}
              />
              <Line 
                yAxisId="right" 
                type="monotone" 
                dataKey="fixed" 
                stroke="#3498db" 
                name="修复数"
                strokeWidth={2}
                dot={{ r: 4 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* 最近事件 */}
      {recent_events.length > 0 && (
        <div className="recent-events">
          <h3>📋 最近事件 ({recent_events.length})</h3>
          <div className="events-list">
            {recent_events.slice(0, 8).map((event, i) => (
              <div key={i} className={`event-item status-${event.status}`}>
                <div className="event-time">
                  {event.timestamp 
                    ? new Date(event.timestamp).toLocaleTimeString('zh-CN')
                    : '—'
                  }
                </div>
                <div className="event-content">
                  <div className="event-route">{event.route}</div>
                  <div className="event-description">{event.description}</div>
                </div>
                <div className={`event-status status-${event.status}`}>
                  {event.status === 'verified' && '✅ 已验证'}
                  {event.status === 'applied' && '📝 已应用'}
                  {event.status === 'reverted' && '↩️ 已撤销'}
                  {event.status === 'pending' && '⏳ 待处理'}
                </div>
              </div>
            ))}
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

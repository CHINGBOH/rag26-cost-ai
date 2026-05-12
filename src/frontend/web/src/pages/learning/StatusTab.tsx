import React from 'react';
import { DashboardPanel } from '../../components/learning/DashboardPanel';
import { SignalAggregation, SignalSummary, LearningDashboard } from '../../services/metricsApi';
import { fmtDateTime } from '../../utils/dateUtils';

interface StatusTabProps {
  signals: SignalAggregation | null;
  signalsSummary: SignalSummary | null;
  dashboard: LearningDashboard | null;
}

export const StatusTab: React.FC<StatusTabProps> = ({ signals, signalsSummary, dashboard }) => (
  <>
    <DashboardPanel dashboard={dashboard} />

    {signals && signalsSummary ? (
      <details className="learn-card learn-signals-card learn-signals-collapsed">
        <summary className="learn-signals-summary">
          <span>📡 详细信号监控</span>
          <span className="muted small">点开看技术统计（开发用）</span>
        </summary>
        <div className="learn-card-head">
          <span className="muted small">采集于 {fmtDateTime(signals.timestamp)}</span>
        </div>

        <div className="signal-health-indicator" data-status={signalsSummary.health_status}>
          <span className="status-icon">
            {signalsSummary.health_status === 'good' && '✅'}
            {signalsSummary.health_status === 'warning' && '⚠️'}
            {signalsSummary.health_status === 'critical' && '🚨'}
          </span>
          <span className="status-text">
            系统健康度: <strong>{signalsSummary.health_status}</strong>
          </span>
        </div>

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

        <div className="severity-meter">
          <div className="meter-label">整体严重度指数</div>
          <div className="meter-bar">
            <div className="meter-fill" style={{ width: `${Math.min(signals.severity_score, 100)}%` }} />
          </div>
          <div className="meter-value">{signals.severity_score.toFixed(1)}/100</div>
        </div>

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
      </details>
    ) : null}
  </>
);

export default StatusTab;

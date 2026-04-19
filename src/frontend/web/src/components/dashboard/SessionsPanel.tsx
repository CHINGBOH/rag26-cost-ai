/**
 * 会话列表面板
 * 展示所有会话的详细信息
 */

import { useRecursionStore } from '../../stores/recursionStore';
// import { StatusBadge, GaugeChart } from '../charts';
import { RecursionSession } from '@rag/shared';
import './Dashboard.css';

export const SessionsPanel: React.FC = () => {
  const sessions = useRecursionStore(state => state.sessions);
  const activeSessionId = useRecursionStore(state => state.activeSessionId);
  const setActiveSession = useRecursionStore(state => state.setActiveSession);
  
  const sessionsList = Array.from(sessions.values()).sort((a, b) => b.createdAt - a.createdAt);
  
  const activeSessions = sessionsList.filter(s => 
    s.currentState !== 'completed' && s.currentState !== 'failed'
  );
  
  const completedSessions = sessionsList.filter(s => 
    s.currentState === 'completed'
  );
  
  const failedSessions = sessionsList.filter(s => 
    s.currentState === 'failed'
  );

  return (
    <div className="sessions-panel">
      {/* 统计概览 */}
      <div className="sessions-stats">
        <div className="stat-box">
          <span className="stat-number">{activeSessions.length}</span>
          <span className="stat-label">活跃</span>
        </div>
        <div className="stat-box">
          <span className="stat-number">{completedSessions.length}</span>
          <span className="stat-label">完成</span>
        </div>
        <div className="stat-box error">
          <span className="stat-number">{failedSessions.length}</span>
          <span className="stat-label">失败</span>
        </div>
        <div className="stat-box">
          <span className="stat-number">{sessionsList.length}</span>
          <span className="stat-label">总计</span>
        </div>
      </div>

      {/* 活跃会话 */}
      {activeSessions.length > 0 && (
        <section className="sessions-section">
          <h3 className="section-title">🔄 活跃会话</h3>
          <div className="sessions-list">
            {activeSessions.map(session => (
              <SessionCard 
                key={session.id} 
                session={session} 
                isActive={session.id === activeSessionId}
                onClick={() => setActiveSession(session.id)}
              />
            ))}
          </div>
        </section>
      )}

      {/* 已完成会话 */}
      {completedSessions.length > 0 && (
        <section className="sessions-section">
          <h3 className="section-title">✅ 已完成</h3>
          <div className="sessions-list">
            {completedSessions.map(session => (
              <SessionCard 
                key={session.id} 
                session={session} 
                isActive={session.id === activeSessionId}
                onClick={() => setActiveSession(session.id)}
              />
            ))}
          </div>
        </section>
      )}

      {/* 失败会话 */}
      {failedSessions.length > 0 && (
        <section className="sessions-section">
          <h3 className="section-title">❌ 失败</h3>
          <div className="sessions-list">
            {failedSessions.map(session => (
              <SessionCard 
                key={session.id} 
                session={session} 
                isActive={session.id === activeSessionId}
                onClick={() => setActiveSession(session.id)}
              />
            ))}
          </div>
        </section>
      )}

      {sessionsList.length === 0 && (
        <div className="no-sessions">
          <p>暂无会话记录</p>
          <p className="hint">输入查询开始新的递归会话</p>
        </div>
      )}
    </div>
  );
};

const SessionCard: React.FC<{
  session: RecursionSession;
  isActive: boolean;
  onClick: () => void;
}> = ({ session, isActive, onClick }) => {
  const latestRound = session.rounds[session.rounds.length - 1];
  const evaluation = latestRound?.evaluation;
  
  const stateLabels: Record<string, { label: string; color: string }> = {
    idle: { label: '就绪', color: 'var(--text-muted)' },
    decomposing: { label: '拆解', color: 'var(--color-primary)' },
    dispatching: { label: '分发', color: 'var(--color-info)' },
    retrieving: { label: '检索', color: 'var(--color-info)' },
    ranking: { label: '精排', color: 'var(--color-success)' },
    generating: { label: '生成', color: 'var(--color-success)' },
    evaluating: { label: '评估', color: 'var(--color-success)' },
    deciding: { label: '决策', color: 'var(--color-warning)' },
    querying_external: { label: '外查', color: 'var(--color-warning)' },
    human_review: { label: '审核', color: 'var(--color-warning)' },
    completed: { label: '完成', color: 'var(--color-success)' },
    failed: { label: '失败', color: 'var(--color-error)' }
  };
  
  const state = stateLabels[session.currentState] || { label: session.currentState, color: 'var(--text-muted)' };
  const runtime = Math.floor((Date.now() - session.createdAt) / 1000);
  const runtimeStr = runtime < 60 ? `${runtime}s` : `${Math.floor(runtime / 60)}m ${runtime % 60}s`;
  
  return (
    <div 
      className={`session-card ${isActive ? 'active' : ''}`}
      onClick={onClick}
    >
      <div className="session-card-header">
        <div className="session-title" title={session.originalQuery}>
          {session.originalQuery.slice(0, 60)}
          {session.originalQuery.length > 60 && '...'}
        </div>
        <span 
          className="session-state-badge"
          style={{ backgroundColor: state.color + '20', color: state.color }}
        >
          {state.label}
        </span>
      </div>
      
      <div className="session-card-meta">
        <span>⏱️ {runtimeStr}</span>
        <span>📏 深度 {session.currentDepth}</span>
        <span>🔄 轮次 {session.rounds.length}</span>
        <span>📄 检索 {session.metrics.totalChunksRetrieved}</span>
      </div>
      
      {evaluation && (
        <div className="session-card-metrics">
          <div className="mini-metric">
            <span className="mini-label">置信</span>
            <div className="mini-bar">
              <div 
                className="mini-fill"
                style={{ width: `${evaluation.confidence * 100}%` }}
              />
            </div>
            <span className="mini-value">{(evaluation.confidence * 100).toFixed(0)}%</span>
          </div>
          <div className="mini-metric">
            <span className="mini-label">完整</span>
            <div className="mini-bar">
              <div 
                className="mini-fill"
                style={{ width: `${evaluation.completeness * 100}%` }}
              />
            </div>
            <span className="mini-value">{(evaluation.completeness * 100).toFixed(0)}%</span>
          </div>
        </div>
      )}
      
      {session.anomalies.length > 0 && (
        <div className="session-anomalies">
          {session.anomalies.map((a, i) => (
            <span key={i} className={`anomaly-tag ${a.level}`}>
              {a.level === 'critical' ? '🔴' : '🟡'} {a.type}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};

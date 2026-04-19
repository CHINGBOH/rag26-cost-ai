/**
 * 会话列表
 * 显示所有递归会话
 */


import { RecursionSession, RecursionState } from '@rag/shared';

interface SessionListProps {
  sessions: Map<string, RecursionSession>;
  activeId: string | null;
  onSelect: (id: string) => void;
}

const stateColors: Record<RecursionState, string> = {
  idle: 'var(--text-muted)',
  decomposing: 'var(--color-primary)',
  dispatching: 'var(--color-info)',
  retrieving: 'var(--color-info)',
  ranking: 'var(--color-success)',
  generating: 'var(--color-success)',
  evaluating: 'var(--color-success)',
  deciding: 'var(--color-warning)',
  querying_external: 'var(--color-warning)',
  human_review: 'var(--color-warning)',
  completed: 'var(--color-success)',
  failed: 'var(--color-error)'
};

const stateLabels: Record<RecursionState, string> = {
  idle: '空闲',
  decomposing: '拆解',
  dispatching: '分发',
  retrieving: '检索',
  ranking: '精排',
  generating: '生成',
  evaluating: '评估',
  deciding: '决策',
  querying_external: '外部查询',
  human_review: '人工审核',
  completed: '完成',
  failed: '失败'
};

export const SessionList: React.FC<SessionListProps> = ({ 
  sessions, 
  activeId, 
  onSelect 
}) => {
  const sessionArray = Array.from(sessions.values()).sort(
    (a, b) => b.createdAt - a.createdAt
  );

  return (
    <div className="session-list">
      <h2>递归会话</h2>
      
      {sessionArray.length === 0 ? (
        <p className="empty">暂无会话</p>
      ) : (
        <div className="sessions">
          {sessionArray.map(session => (
            <div
              key={session.id}
              className={`session-item ${session.id === activeId ? 'active' : ''}`}
              onClick={() => onSelect(session.id)}
            >
              <div className="session-header">
                <span 
                  className="status-dot"
                  style={{ backgroundColor: stateColors[session.currentState] }}
                />
                <span className="state-label">
                  {stateLabels[session.currentState]}
                </span>
                <span className="depth">D{session.currentDepth}</span>
              </div>
              
              <div className="query-preview">
                {session.originalQuery.slice(0, 50)}
                {session.originalQuery.length > 50 ? '...' : ''}
              </div>
              
              <div className="session-meta">
                <span>轮次: {session.rounds.length}</span>
                <span>{new Date(session.createdAt).toLocaleTimeString()}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

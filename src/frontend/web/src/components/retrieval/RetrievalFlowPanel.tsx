/**
 * 检索流程可视化面板
 * 展示查询拆解、多库路由、召回、精排全过程
 */

import { useRecursionStore } from '../../stores/recursionStore';
import { TimelineChart, FunnelChart } from '../charts';
import { RecursionSession, SubQuery, RetrievedChunk } from '@rag/shared';
import './Retrieval.css';

export const RetrievalFlowPanel: React.FC = () => {
  const sessions = useRecursionStore(state => state.sessions);
  const activeSessionId = useRecursionStore(state => state.activeSessionId);
  
  const activeSession = activeSessionId ? sessions.get(activeSessionId) : null;
  
  return (
    <div className="retrieval-panel">
      {activeSession ? (
        <ActiveSessionRetrieval session={activeSession} />
      ) : (
        <div className="no-session">
          <p>请选择一个活跃会话来查看检索流程</p>
        </div>
      )}
    </div>
  );
};

const ActiveSessionRetrieval: React.FC<{ session: RecursionSession }> = ({ session }) => {
  const currentRound = session.rounds[session.rounds.length - 1];
  
  return (
    <div className="retrieval-flow">
      {/* 流程概览 */}
      <section className="retrieval-section">
        <h3 className="section-title">📍 当前检索状态</h3>
        <div className="flow-status-bar">
          <FlowStep 
            label="查询拆解" 
            status={session.currentState === 'decomposing' ? 'running' : 
                   session.currentState === 'idle' ? 'pending' : 'completed'}
          />
          <FlowArrow />
          <FlowStep 
            label="多库路由" 
            status={session.currentState === 'dispatching' ? 'running' :
                   ['idle', 'decomposing'].includes(session.currentState) ? 'pending' : 'completed'}
          />
          <FlowArrow />
          <FlowStep 
            label="文档召回" 
            status={session.currentState === 'retrieving' ? 'running' :
                   ['idle', 'decomposing', 'dispatching'].includes(session.currentState) ? 'pending' : 'completed'}
          />
          <FlowArrow />
          <FlowStep 
            label="精排重算" 
            status={session.currentState === 'ranking' ? 'running' :
                   ['idle', 'decomposing', 'dispatching', 'retrieving'].includes(session.currentState) ? 'pending' : 'completed'}
          />
          <FlowArrow />
          <FlowStep 
            label="答案生成" 
            status={session.currentState === 'generating' ? 'running' :
                   session.currentState === 'completed' ? 'completed' : 'pending'}
          />
        </div>
      </section>

      {/* 查询拆解 */}
      {currentRound?.subQueries && currentRound.subQueries.length > 0 && (
        <section className="retrieval-section">
          <h3 className="section-title">🔨 查询拆解</h3>
          <div className="subqueries-grid">
            {currentRound.subQueries.map((sq, idx) => (
              <SubQueryCard key={sq.id} subQuery={sq} index={idx} />
            ))}
          </div>
        </section>
      )}

      {/* 召回漏斗 */}
      {currentRound && (
        <section className="retrieval-section">
          <h3 className="section-title">📊 召回漏斗</h3>
          <div className="funnel-row">
            <div className="funnel-visual">
              <FunnelChart 
                stages={[
                  { name: '向量召回', value: 100, label: '100' },
                  { name: '知识库', value: 80, label: '80' },
                  { name: '图谱', value: 40, label: '40' },
                  { name: '精排后', value: 20, label: '20' },
                  { name: '最终', value: 10, label: '10' }
                ]}
                width={300}
                height={200}
              />
            </div>
            <div className="funnel-stats">
              <div className="funnel-stat-card">
                <span className="stat-label">召回总数</span>
                <span className="stat-value">{currentRound.retrievedChunks.length}</span>
              </div>
              <div className="funnel-stat-card">
                <span className="stat-label">来源数</span>
                <span className="stat-value">
                  {new Set(currentRound.retrievedChunks.map(c => c.source)).size}
                </span>
              </div>
              <div className="funnel-stat-card">
                <span className="stat-label">平均相似度</span>
                <span className="stat-value">
                  {currentRound.retrievedChunks.length > 0 
                    ? (currentRound.retrievedChunks.reduce((s, c) => s + c.score, 0) / currentRound.retrievedChunks.length * 100).toFixed(1)
                    : 0}%
                </span>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* 检索结果 */}
      {currentRound?.retrievedChunks && currentRound.retrievedChunks.length > 0 && (
        <section className="retrieval-section">
          <h3 className="section-title">📄 检索证据</h3>
          <div className="evidence-list">
            {currentRound.retrievedChunks.map((chunk, idx) => (
              <EvidenceCard key={chunk.id} chunk={chunk} index={idx} />
            ))}
          </div>
        </section>
      )}

      {/* 矛盾检测 */}
      {currentRound?.contradictions && currentRound.contradictions.length > 0 && (
        <section className="retrieval-section">
          <h3 className="section-title">⚠️ 检测到的矛盾</h3>
          <div className="contradictions-list">
            {currentRound.contradictions.map((c, idx) => (
              <div key={idx} className={`contradiction-card ${c.severity}`}>
                <div className="contradiction-header">
                  <span className={`severity-badge ${c.severity}`}>
                    {c.severity === 'high' ? '🔴' : c.severity === 'medium' ? '🟡' : '🟢'}
                    {c.severity}
                  </span>
                </div>
                <p className="contradiction-desc">{c.description}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 历史时间线 */}
      {session.rounds.length > 0 && (
        <section className="retrieval-section">
          <h3 className="section-title">⏱️ 递归轮次时间线</h3>
          <TimelineChart 
            events={session.rounds.map(r => ({
              time: r.timestamp,
              label: `第 ${r.roundId} 轮检索`,
              state: r.decision === 'satisfy' ? 'completed' : 'completed',
              details: r.decision 
                ? `决策: ${r.decision}, 置信度: ${(r.evaluation?.confidence || 0 * 100).toFixed(0)}%`
                : undefined
            }))}
            height={300}
          />
        </section>
      )}
    </div>
  );
};

// 流程步骤
const FlowStep: React.FC<{ label: string; status: 'pending' | 'running' | 'completed' | 'error' }> = ({ 
  label, 
  status 
}) => {
  const statusConfig = {
    pending: { color: 'var(--text-muted)', icon: '○' },
    running: { color: 'var(--color-primary)', icon: '◐' },
    completed: { color: 'var(--color-success)', icon: '●' },
    error: { color: 'var(--color-error)', icon: '✕' }
  };
  
  const config = statusConfig[status];
  
  return (
    <div className={`flow-step ${status}`}>
      <div 
        className="step-indicator"
        style={{ borderColor: config.color, color: config.color }}
      >
        {config.icon}
      </div>
      <span className="step-label" style={{ color: config.color }}>{label}</span>
    </div>
  );
};

// 流程箭头
const FlowArrow: React.FC = () => (
  <div className="flow-arrow">→</div>
);

// 子查询卡片
const SubQueryCard: React.FC<{ subQuery: SubQuery; index: number }> = ({ subQuery, index }) => {
  const statusMap = {
    pending: { badge: '⏳ 等待', color: 'var(--text-muted)' },
    running: { badge: '🔄 执行', color: 'var(--color-primary)' },
    completed: { badge: '✅ 完成', color: 'var(--color-success)' },
    failed: { badge: '❌ 失败', color: 'var(--color-error)' }
  };
  
  const status = statusMap[subQuery.status];
  
  return (
    <div className={`subquery-card ${subQuery.status}`}>
      <div className="subquery-header">
        <span className="subquery-index">#{index + 1}</span>
        <span className="subquery-target">{subQuery.targetDB}</span>
        <span className="subquery-status" style={{ color: status.color }}>
          {status.badge}
        </span>
      </div>
      <p className="subquery-text">{subQuery.query}</p>
      {subQuery.latency && (
        <div className="subquery-meta">
          <span>⏱️ {subQuery.latency}ms</span>
          {subQuery.resultCount !== undefined && (
            <span>📄 {subQuery.resultCount} 结果</span>
          )}
        </div>
      )}
    </div>
  );
};

// 证据卡片
const EvidenceCard: React.FC<{ chunk: RetrievedChunk; index: number }> = ({ chunk, index }) => {
  const scorePercent = Math.round(chunk.score * 100);
  const scoreColor = scorePercent >= 80 ? 'var(--color-success)' : scorePercent >= 60 ? 'var(--color-warning)' : 'var(--color-error)';
  
  return (
    <div className="evidence-card">
      <div className="evidence-header">
        <div className="evidence-rank">#{index + 1}</div>
        <div className="evidence-score" style={{ color: scoreColor }}>
          {scorePercent}%
        </div>
        <div className="evidence-source">{chunk.source}</div>
        <div className="evidence-db">{chunk.database}</div>
      </div>
      <div className="evidence-content">
        {chunk.content.slice(0, 150)}
        {chunk.content.length > 150 && '...'}
      </div>
      {chunk.metadata.page && (
        <div className="evidence-meta">
          <span>📄 第 {chunk.metadata.page} 页</span>
          {chunk.metadata.section && (
            <span>📑 {chunk.metadata.section}</span>
          )}
        </div>
      )}
    </div>
  );
};

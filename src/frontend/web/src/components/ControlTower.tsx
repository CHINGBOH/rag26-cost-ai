/**
 * 递归控制塔
 * 观察和控制递归过程的中央面板
 * 
 * 核心功能：
 * - 实时状态监控（在哪、多深、多久）
 * - 质量指标趋势（置信度、完整性、信息增益）
 * - 专家判断历史（每轮决策可见）
 * - 人工干预入口（停止、接管、分叉）
 */

import { useState } from 'react';
import {
  RecursionSession,
  RecursionState,
  ExpertDecision
} from '@rag/shared';
import './ControlTower.css';

interface ControlTowerProps {
  session: RecursionSession;
  onStop: () => void;
  onHumanTakeover: () => void;
  onCreateBranch: () => void;
  onForceContinue: () => void;
}

const stateLabels: Record<RecursionState, { label: string; color: string; desc: string }> = {
  idle: { label: '就绪', color: 'var(--text-muted)', desc: '等待启动' },
  decomposing: { label: '拆解', color: 'var(--color-primary)', desc: '分解查询' },
  dispatching: { label: '分发', color: 'var(--color-info)', desc: '分发子查询' },
  retrieving: { label: '检索', color: 'var(--color-info)', desc: '召回文档' },
  ranking: { label: '精排', color: 'var(--color-success)', desc: '排序结果' },
  generating: { label: '生成', color: 'var(--color-success)', desc: '生成答案' },
  evaluating: { label: '评估', color: 'var(--color-success)', desc: '质量评估' },
  deciding: { label: '决策', color: 'var(--color-warning)', desc: '专家判断' },
  querying_external: { label: '外查', color: 'var(--color-warning)', desc: '查询外部' },
  human_review: { label: '审核', color: 'var(--color-warning)', desc: '等待人工' },
  completed: { label: '完成', color: 'var(--color-success)', desc: '已结束' },
  failed: { label: '失败', color: 'var(--color-error)', desc: '异常终止' }
};

const decisionIcons: Record<ExpertDecision, string> = {
  satisfy: '✓',
  continue: '↻',
  query_external: '↗',
  human_review: '?'
};

const decisionLabels: Record<ExpertDecision, string> = {
  satisfy: '满意',
  continue: '继续',
  query_external: '外查',
  human_review: '人工'
};

export const ControlTower: React.FC<ControlTowerProps> = ({
  session,
  onStop,
  onHumanTakeover,
  onCreateBranch,
  onForceContinue
}) => {
  const [showDetails, setShowDetails] = useState(true);
  const [activeTab, setActiveTab] = useState<'overview' | 'rounds' | 'tree'>('overview');

  const currentState = stateLabels[session.currentState];
  const isRunning = session.currentState !== 'completed' && session.currentState !== 'failed';
  const isInHumanReview = session.currentState === 'human_review';

  // 计算运行时间
  const runtime = Math.floor((Date.now() - session.createdAt) / 1000);
  const runtimeStr = runtime < 60 
    ? `${runtime}s` 
    : `${Math.floor(runtime / 60)}m ${runtime % 60}s`;

  // 获取最新评估
  const latestRound = session.rounds[session.rounds.length - 1];
  const latestEval = latestRound?.evaluation;

  // 置信度趋势
  const confidenceHistory = session.rounds
    .filter(r => r.evaluation)
    .map(r => r.evaluation!.confidence);

  // 渲染进度条
  const renderProgress = (value: number, color: string) => (
    <div className="progress-bar">
      <div 
        className="progress-fill" 
        style={{ width: `${value * 100}%`, backgroundColor: color }}
      />
      <span className="progress-text">{(value * 100).toFixed(0)}%</span>
    </div>
  );

  // 渲染趋势箭头
  const renderTrend = (current: number, history: number[]) => {
    if (history.length < 2) return <span className="trend-flat">→</span>;
    const prev = history[history.length - 2];
    if (current > prev) return <span className="trend-up">↑</span>;
    if (current < prev) return <span className="trend-down">↓</span>;
    return <span className="trend-flat">→</span>;
  };

  return (
    <div className="control-tower">
      {/* 顶部状态栏 */}
      <div className="tower-header" style={{ borderColor: currentState.color }}>
        <div className="status-section">
          <div 
            className="status-indicator" 
            style={{ backgroundColor: currentState.color }}
          >
            <span className="status-pulse" />
          </div>
          <div className="status-info">
            <span className="status-label" style={{ color: currentState.color }}>
              {currentState.label}
            </span>
            <span className="status-desc">{currentState.desc}</span>
          </div>
        </div>

        <div className="meta-section">
          <div className="meta-item">
            <span className="meta-label">深度</span>
            <span className="meta-value depth">{session.currentDepth}</span>
          </div>
          <div className="meta-item">
            <span className="meta-label">轮次</span>
            <span className="meta-value">{session.rounds.length}</span>
          </div>
          <div className="meta-item">
            <span className="meta-label">时间</span>
            <span className="meta-value">{runtimeStr}</span>
          </div>
        </div>

        <div className="actions-section">
          {isRunning && (
            <>
              <button className="action-btn stop" onClick={onStop} title="强制停止">
                ⏹
              </button>
              <button className="action-btn branch" onClick={onCreateBranch} title="创建分支">
                🔀
              </button>
            </>
          )}
          {isInHumanReview && (
            <button className="action-btn takeover" onClick={onHumanTakeover}>
              接管
            </button>
          )}
          <button 
            className="action-btn toggle"
            onClick={() => setShowDetails(!showDetails)}
          >
            {showDetails ? '▲' : '▼'}
          </button>
        </div>
      </div>

      {/* 详细信息面板 */}
      {showDetails && (
        <div className="tower-body">
          {/* 标签页 */}
          <div className="tower-tabs">
            <button 
              className={`tab ${activeTab === 'overview' ? 'active' : ''}`}
              onClick={() => setActiveTab('overview')}
            >
              总览
            </button>
            <button 
              className={`tab ${activeTab === 'rounds' ? 'active' : ''}`}
              onClick={() => setActiveTab('rounds')}
            >
              轮次 ({session.rounds.length})
            </button>
            <button 
              className={`tab ${activeTab === 'tree' ? 'active' : ''}`}
              onClick={() => setActiveTab('tree')}
            >
              结构
            </button>
          </div>

          {/* 总览面板 */}
          {activeTab === 'overview' && (
            <div className="panel overview-panel">
              {/* 质量指标 */}
              {latestEval && (
                <div className="metrics-section">
                  <h4>当前质量</h4>
                  
                  <div className="metric-row">
                    <span className="metric-label">置信度</span>
                    {renderProgress(latestEval.confidence, 'var(--color-success)')}
                    {renderTrend(latestEval.confidence, confidenceHistory)}
                  </div>
                  
                  <div className="metric-row">
                    <span className="metric-label">完整性</span>
                    {renderProgress(latestEval.completeness, 'var(--color-primary)')}
                  </div>
                  
                  <div className="metric-row">
                    <span className="metric-label">一致性</span>
                    {renderProgress(latestEval.consistency, 'var(--color-warning)')}
                  </div>
                  
                  <div className="metric-row">
                    <span className="metric-label">信息增益</span>
                    {renderProgress(latestEval.informationGain, '#7c3aed')}
                  </div>

                  {/* 饱和度判断 */}
                  <div className="saturation-indicator">
                    {latestEval.informationGain < 0.05 ? (
                      <span className="saturation-high">⚠️ 信息增益接近饱和</span>
                    ) : latestEval.informationGain < 0.1 ? (
                      <span className="saturation-medium">信息增益减缓</span>
                    ) : (
                      <span className="saturation-low">信息增益良好</span>
                    )}
                  </div>
                </div>
              )}

              {/* 最新专家判断 */}
              {latestRound?.expertReasoning && (
                <div className="latest-judgment">
                  <h4>最新决策</h4>
                  <div className="judgment-card">
                    <span className={`decision-badge ${latestRound.decision}`}>
                      {decisionIcons[latestRound.decision!]} {decisionLabels[latestRound.decision!]}
                    </span>
                    <p className="judgment-text">{latestRound.expertReasoning}</p>
                  </div>
                </div>
              )}

              {/* 快捷干预 */}
              {isRunning && (
                <div className="quick-actions">
                  <h4>快捷干预</h4>
                  <div className="action-row">
                    <button className="quick-btn" onClick={onForceContinue}>
                      强制继续
                    </button>
                    <span className="quick-desc">无视当前判断，继续深挖</span>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 轮次历史面板 */}
          {activeTab === 'rounds' && (
            <div className="panel rounds-panel">
              {session.rounds.length === 0 ? (
                <p className="empty-text">暂无递归轮次</p>
              ) : (
                <div className="rounds-timeline">
                  {session.rounds.map((round, idx) => (
                    <div key={idx} className="round-item">
                      <div className="round-header">
                        <span className="round-num">第 {round.roundId} 轮</span>
                        <span className="round-time">
                          {new Date(round.timestamp).toLocaleTimeString()}
                        </span>
                      </div>
                      
                      {round.decision && (
                        <span className={`round-decision ${round.decision}`}>
                          {decisionIcons[round.decision]} {decisionLabels[round.decision]}
                        </span>
                      )}

                      {round.evaluation && (
                        <div className="round-metrics">
                          <span>置信 {(round.evaluation.confidence * 100).toFixed(0)}%</span>
                          <span>完整 {(round.evaluation.completeness * 100).toFixed(0)}%</span>
                          <span>增益 {(round.evaluation.informationGain * 100).toFixed(0)}%</span>
                        </div>
                      )}

                      {round.expertReasoning && (
                        <p className="round-reasoning">{round.expertReasoning}</p>
                      )}

                      {round.retrievedChunks.length > 0 && (
                        <div className="round-evidence">
                          检索到 {round.retrievedChunks.length} 个证据
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 结构面板 */}
          {activeTab === 'tree' && (
            <div className="panel tree-panel">
              <div className="tree-visualization">
                <div className="tree-node root">
                  <span className="tree-icon">🎯</span>
                  <span className="tree-content">根问题</span>
                </div>
                {session.rounds.map((round, idx) => (
                  <div key={idx} className="tree-level" style={{ marginLeft: `${(idx + 1) * 20}px` }}>
                    <div className="tree-node">
                      <span className="tree-icon">
                        {round.decision === 'satisfy' ? '✓' : '↻'}
                      </span>
                      <span className="tree-content">
                        第 {round.roundId} 轮 {round.subQueries.length > 0 && `(${round.subQueries.length}子查询)`}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

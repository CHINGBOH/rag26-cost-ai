import React, { useState } from 'react';
import { ProblemReport, RootCauseAnalysis, RepairStrategy, analyzeRootCause, getRepairStrategies } from '../../services/metricsApi';
import './ProblemsPanel.css';

interface ProblemsPanelProps {
  problems: ProblemReport[];
}

export const ProblemsPanel: React.FC<ProblemsPanelProps> = ({ problems }) => {
  const [selectedProblem, setSelectedProblem] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<RootCauseAnalysis | null>(null);
  const [strategies, setStrategies] = useState<RepairStrategy[]>([]);
  const [loading, setLoading] = useState(false);

  const handleSelectProblem = async (problemId: string) => {
    setSelectedProblem(problemId);
    setLoading(true);
    try {
      const [analysisData, strategiesData] = await Promise.all([
        analyzeRootCause(problemId),
        getRepairStrategies(problemId),
      ]);
      setAnalysis(analysisData);
      setStrategies(strategiesData.strategies);
    } finally {
      setLoading(false);
    }
  };

  const severityColor = (severity: string) => {
    switch (severity) {
      case 'high': return '#e74c3c';
      case 'medium': return '#f39c12';
      default: return '#3498db';
    }
  };

  return (
    <div className="problems-panel">
      {/* 左边：问题列表 */}
      <div className="problems-list">
        <h3>检测到的问题 ({problems.length})</h3>
        <div className="problem-items">
          {problems.length === 0 ? (
            <p className="empty">暂无检测到的问题</p>
          ) : (
            problems.map((p) => (
              <div
                key={p.problem_id}
                className={`problem-item ${selectedProblem === p.problem_id ? 'selected' : ''}`}
                onClick={() => handleSelectProblem(p.problem_id)}
                style={{ borderLeftColor: severityColor(p.severity) }}
              >
                <div className="header">
                  <span className={`severity ${p.severity}`}>
                    {p.severity === 'high' ? '🔴' : p.severity === 'medium' ? '🟡' : '🔵'}
                  </span>
                  <span className="category">{p.category}</span>
                  <span className="route">[{p.affected_route}]</span>
                </div>
                <div className="description">{p.description}</div>
                <div className="confidence">
                  确信度: <strong>{(p.confidence * 100).toFixed(0)}%</strong>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* 右边：详情面板 */}
      {selectedProblem && (
        <div className="problem-detail">
          {loading ? (
            <div className="loading">分析中...</div>
          ) : analysis ? (
            <>
              {/* 根因分析 */}
              <div className="analysis-section">
                <h3>🔎 根因分析</h3>
                <p className="root-cause">{analysis.root_cause}</p>
                <p className="confidence">
                  确信度: <strong>{(analysis.confidence * 100).toFixed(0)}%</strong>
                </p>

                {/* 证据链 */}
                <div className="evidence">
                  <h4>证据链</h4>
                  {Object.entries(analysis.evidence).map(([type, items]) => (
                    <div key={type} className="evidence-group">
                      <strong>{type}:</strong>
                      <ul>
                        {items.map((item, i) => (
                          <li key={i}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </div>

              {/* 修复建议 */}
              <div className="strategies-section">
                <h3>💡 修复建议</h3>
                <div className="strategies-list">
                  {strategies.map((s) => {
                    const decisionLabel =
                      s.decision === 'auto_apply'
                        ? '自动应用'
                        : s.decision === 'pending_review'
                        ? '待审核'
                        : '人工决策';
                    return (
                      <div key={s.strategy_id} className={`strategy-card ${s.decision}`}>
                        <div className="header">
                          <span className="action">{s.action_type}</span>
                          <span className={`risk ${s.risk_level}`}>
                            {s.risk_level === 'low' ? '✅ 低风险' : s.risk_level === 'mid' ? '⚠️ 中风险' : '🚨 高风险'}
                          </span>
                        </div>
                        <p className="description">{s.description}</p>
                        <details className="strategy-detail">
                          <summary>处置：{decisionLabel}</summary>
                          <ul>
                            <li>预期改进：{s.estimated_impact}%</li>
                            <li>处置策略：{decisionLabel}（<code>{s.decision}</code>）</li>
                            <li>动作类型：<code>{s.action_type}</code></li>
                          </ul>
                        </details>
                      </div>
                    );
                  })}
                </div>
              </div>
            </>
          ) : null}
        </div>
      )}
    </div>
  );
};

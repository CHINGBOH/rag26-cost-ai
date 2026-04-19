/**
 * 系统生命体征面板
 * 显示核心指标
 */


import { SystemVitals } from '@rag/shared';

interface VitalsPanelProps {
  vitals: SystemVitals | null;
}

export const VitalsPanel: React.FC<VitalsPanelProps> = ({ vitals }) => {
  if (!vitals) {
    return (
      <div className="vitals-panel loading">
        <h2>系统状态</h2>
        <p>连接中...</p>
      </div>
    );
  }

  const getHealthColor = (score: number) => {
    if (score >= 80) return 'var(--color-success)';
    if (score >= 60) return 'var(--color-warning)';
    return 'var(--color-error)';
  };

  const getTrendSymbol = (trend: string) => {
    switch (trend) {
      case 'up': return '↑';
      case 'down': return '↓';
      default: return '→';
    }
  };

  return (
    <div className="vitals-panel">
      <h2>系统生命体征</h2>
      
      <div className="vitals-grid">
        <div className="vital-card" style={{ borderColor: getHealthColor(vitals.healthScore) }}>
          <div className="vital-value" style={{ color: getHealthColor(vitals.healthScore) }}>
            {vitals.healthScore}
          </div>
          <div className="vital-label">健康度</div>
        </div>

        <div className="vital-card">
          <div className="vital-value">{vitals.recursionDepth}</div>
          <div className="vital-label">当前深度</div>
        </div>

        <div className="vital-card">
          <div className="vital-value">{vitals.maxDepthReached}</div>
          <div className="vital-label">最大深度</div>
        </div>

        <div className="vital-card">
          <div className="vital-value">
            {getTrendSymbol(vitals.confidenceTrend)}
          </div>
          <div className="vital-label">置信趋势</div>
        </div>
      </div>

      <div className="tasks-section">
        <h3>任务队列</h3>
        <div className="task-stats">
          <span className="task-badge active">
            运行中: {vitals.activeTasks}
          </span>
          <span className="task-badge pending">
            等待: {vitals.pendingTasks}
          </span>
          <span className="task-badge completed">
            完成: {vitals.completedTasks}
          </span>
        </div>
      </div>

      <div className="latency-section">
        <h3>延迟指标 (ms)</h3>
        <div className="latency-bars">
          <div className="latency-item">
            <span>检索</span>
            <div className="bar">
              <div className="fill" style={{ width: `${Math.min(vitals.latency.retrieval / 10, 100)}%` }} />
            </div>
            <span>{vitals.latency.retrieval}</span>
          </div>
          <div className="latency-item">
            <span>生成</span>
            <div className="bar">
              <div className="fill" style={{ width: `${Math.min(vitals.latency.generation / 10, 100)}%` }} />
            </div>
            <span>{vitals.latency.generation}</span>
          </div>
          <div className="latency-item">
            <span>评估</span>
            <div className="bar">
              <div className="fill" style={{ width: `${Math.min(vitals.latency.evaluation / 10, 100)}%` }} />
            </div>
            <span>{vitals.latency.evaluation}</span>
          </div>
        </div>
      </div>
    </div>
  );
};

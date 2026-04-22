/**
 * 任务管道可视化组件
 * 在对话区域顶部显示实时RAG处理流程
 */

import { useEffect, useState } from 'react';
import { PipelineStage } from './types';
import { ragStages, uiConfig, chatFlowConfig } from '../../config';

interface TaskPipelineVisualProps {
  state: {
    stage: PipelineStage;
    progress: number;
    status: 'pending' | 'running' | 'completed' | 'error';
    details?: string;
    metrics?: Record<string, number>;
  };
  query?: string;
  onCancel?: () => void;
}

interface StageInfo {
  id: PipelineStage;
  name: string;
  icon: string;
  description: string;
}

// 从配置读取 RAG 阶段
const STAGES: StageInfo[] = ragStages as StageInfo[];

export const TaskPipelineVisual: React.FC<TaskPipelineVisualProps> = ({
  state,
  query,
  onCancel
}) => {
  const [elapsedTime, setElapsedTime] = useState(0);

  useEffect(() => {
    if (state.status === 'running') {
      const startTime = Date.now();
      const interval = setInterval(() => {
        setElapsedTime(Math.floor((Date.now() - startTime) / 1000));
      }, 1000);
      return () => clearInterval(interval);
    }
  }, [state.status, state.stage]);

  const currentStageIndex = STAGES.findIndex(s => s.id === state.stage);
  
  const getStageStatus = (index: number): 'completed' | 'current' | 'pending' => {
    if (index < currentStageIndex) return 'completed';
    if (index === currentStageIndex) return 'current';
    return 'pending';
  };

  const formatTime = (seconds: number) => {
    if (seconds < uiConfig.pipeline.timeFormatThreshold) return `${seconds}s`;
    return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  };

  return (
    <div className="task-pipeline-visual">
      {/* 头部信息 */}
      <div className="pipeline-header">
        <div className="pipeline-title">
          <span className="pulse-dot"></span>
          <span>RAG 任务执行中</span>
        </div>
        <div className="pipeline-meta">
          <span className="elapsed-time">⏱️ {formatTime(elapsedTime)}</span>
          <span className="progress-percent">{Math.round(state.progress)}%</span>
          {onCancel && (
            <button className="cancel-btn" onClick={onCancel} title={chatFlowConfig.ui.tooltips.cancelTask}>
              ✕
            </button>
          )}
        </div>
      </div>

      {/* 查询显示 */}
      {query && (
        <div className="pipeline-query">
          <span className="query-label">查询:</span>
          <span className="query-text">{query}</span>
        </div>
      )}

      {/* 进度条 */}
      <div className="pipeline-progress-container">
        <div className="pipeline-progress-bg">
          <div 
            className="pipeline-progress-fill"
            style={{ width: `${state.progress}%` }}
          />
        </div>
      </div>

      {/* 阶段可视化 */}
      <div className="pipeline-stages">
        {STAGES.map((stage, index) => {
          const status = getStageStatus(index);
          const isLast = index === STAGES.length - 1;
          
          return (
            <div key={stage.id} className={`pipeline-stage-item ${status}`}>
              <div className="stage-node">
                <span className="stage-icon">{stage.icon}</span>
                {status === 'completed' && (
                  <span className="stage-check">✓</span>
                )}
                {status === 'current' && state.status === 'running' && (
                  <span className="stage-spinner"></span>
                )}
              </div>
              <span className="stage-name">{stage.name}</span>
              {status === 'current' && state.details && (
                <span className="stage-detail">{state.details}</span>
              )}
              {!isLast && <div className="stage-connector" />}
            </div>
          );
        })}
      </div>

      {/* 当前阶段详情 */}
      {state.status === 'running' && state.metrics && (
        <div className="pipeline-metrics">
          {Object.entries(state.metrics).map(([key, value]) => (
            <div key={key} className="pipeline-metric">
              <span className="metric-name">
                {key === 'retrieved' ? '已检索' :
                 key === 'filtered' ? '已过滤' :
                 key === 'articles' ? '文章' :
                 key === 'entities' ? '实体' :
                 key === 'nodes' ? '节点' :
                 key === 'relationships' ? '关系' :
                 key === 'input' ? '输入' :
                 key === 'output' ? '输出' :
                 key === 'topScore' ? '最高分' :
                 key === 'tokensPerSecond' ? '生成速度' :
                 key === 'tokensGenerated' ? '已生成' : key}
              </span>
              <span className="metric-value">
                {typeof value === 'number' && value < 1 
                  ? value.toFixed(2) 
                  : value}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

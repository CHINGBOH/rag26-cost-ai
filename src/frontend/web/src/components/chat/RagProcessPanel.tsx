/**
 * RAG 流程可视化面板
 * 展示从意图识别到答案生成的完整流程
 */

import { useState } from 'react';
import {
  RagProcessStep,
  RagProcessStepType,
  SubQuery,
  PromptAssembly
} from '@rag/shared';
import { StatusBadge } from '../charts';
import { TaskDecompositionView } from './TaskDecompositionView';
import { PromptAssemblyViewer } from './PromptAssemblyViewer';
import './Chat.css';

interface RagProcessPanelProps {
  steps: RagProcessStep[];
  isExpanded: boolean;
  onToggle: () => void;
  originalQuery?: string;
}

const STEP_CONFIG: Record<RagProcessStepType, { 
  label: string; 
  icon: string;
  description: string;
  color: string;
}> = {
  intent_recognition: { 
    label: '意图识别', 
    icon: '🎯',
    description: '识别用户查询的意图类型',
    color: 'var(--color-error)'
  },
  task_decomposition: { 
    label: '任务拆解', 
    icon: '🔨',
    description: '将复杂问题分解为子查询',
    color: 'var(--color-warning)'
  },
  query_generation: { 
    label: '查询生成', 
    icon: '🔍',
    description: '生成用于检索的查询语句',
    color: 'var(--color-warning)'
  },
  vector_retrieval: { 
    label: '向量召回', 
    icon: '📊',
    description: '从向量库检索相似文档',
    color: 'var(--color-success)'
  },
  knowledge_retrieval: { 
    label: '知识召回', 
    icon: '📚',
    description: '从知识库检索相关条目',
    color: 'var(--color-success)'
  },
  graph_retrieval: { 
    label: '图谱召回', 
    icon: '🕸️',
    description: '从知识图谱检索关系',
    color: 'var(--color-info)'
  },
  reranking: { 
    label: '精排重算', 
    icon: '⚖️',
    description: '对召回结果重新排序',
    color: 'var(--color-info)'
  },
  prompt_assembly: { 
    label: 'Prompt组装', 
    icon: '📝',
    description: '组装最终提示词',
    color: 'var(--color-primary)'
  },
  llm_generation: { 
    label: 'LLM生成', 
    icon: '🤖',
    description: '大模型生成答案',
    color: '#4f46e5'
  },
  answer_formatting: { 
    label: '答案格式化', 
    icon: '✨',
    description: '格式化并添加引用',
    color: '#7c3aed'
  }
};

export const RagProcessPanel: React.FC<RagProcessPanelProps> = ({
  steps,
  isExpanded,
  onToggle,
  originalQuery = ''
}) => {
  const [selectedStep, setSelectedStep] = useState<RagProcessStep | null>(null);
  const [viewMode, setViewMode] = useState<'flow' | 'detail'>('flow');

  // 计算总体进度
  const completedSteps = steps.filter(s => s.status === 'completed').length;
  const runningStep = steps.find(s => s.status === 'running');
  const progress = steps.length > 0 ? (completedSteps / steps.length) * 100 : 0;

  return (
    <div className={`rag-process-panel ${isExpanded ? 'expanded' : ''}`}>
      {/* 流程条（折叠时显示） */}
      {!isExpanded && (
        <div className="process-bar" onClick={onToggle}>
          <div className="process-flow">
            {steps.map((step, index) => (
              <FlowNode 
                key={step.type} 
                step={step} 
                isLast={index === steps.length - 1}
              />
            ))}
          </div>
          {runningStep && (
            <div className="running-indicator">
              <span className="pulse">◐</span>
              <span>{STEP_CONFIG[runningStep.type].label}...</span>
            </div>
          )}
          <div className="expand-hint">▼ 展开详情</div>
        </div>
      )}

      {/* 详细面板（展开时显示） */}
      {isExpanded && (
        <div className="process-detail">
          <div className="detail-header">
            <h4>🔄 RAG 流程详情</h4>
            <div className="header-actions">
              <div className="view-toggle">
                <button
                  className={`view-btn ${viewMode === 'flow' ? 'active' : ''}`}
                  onClick={() => setViewMode('flow')}
                >
                  流程
                </button>
                <button
                  className={`view-btn ${viewMode === 'detail' ? 'active' : ''}`}
                  onClick={() => setViewMode('detail')}
                >
                  详情
                </button>
              </div>
              <span className="progress-text">{completedSteps}/{steps.length} 完成</span>
              <button className="collapse-btn" onClick={onToggle}>▲ 收起</button>
            </div>
          </div>

          {/* 总体进度条 */}
          <div className="overall-progress">
            <div className="progress-bar">
              <div 
                className="progress-fill"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>

          {viewMode === 'flow' ? (
            <div className="process-content flow-view">
              {/* 步骤流程图 */}
              <div className="flow-timeline">
                {steps.map((step, index) => (
                  <TimelineNode
                    key={step.type}
                    step={step}
                    isActive={selectedStep?.type === step.type}
                    onClick={() => setSelectedStep(step)}
                    isLast={index === steps.length - 1}
                  />
                ))}
              </div>

              {/* 选中步骤详情 */}
              {selectedStep && (
                <StepDetail 
                  step={selectedStep} 
                  originalQuery={originalQuery}
                />
              )}
            </div>
          ) : (
            <div className="process-content detail-view">
              {/* 详情视图 - 所有步骤详细信息 */}
              {steps.map((step) => (
                <StepDetailSection
                  key={step.type}
                  step={step}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// 流程节点（折叠状态）
const FlowNode: React.FC<{ step: RagProcessStep; isLast: boolean }> = ({ 
  step, 
  isLast 
}) => {
  const config = STEP_CONFIG[step.type];
  const statusIcon = {
    pending: '○',
    running: '◐',
    completed: '●',
    failed: '✕'
  }[step.status];

  return (
    <>
      <div 
        className={`flow-node ${step.status}`}
        style={{ '--step-color': config.color } as React.CSSProperties}
        title={config.label}
      >
        <span className="node-icon">{config.icon}</span>
        <span className="node-status">{statusIcon}</span>
      </div>
      {!isLast && <div className="flow-arrow">→</div>}
    </>
  );
};

// 时间线节点
const TimelineNode: React.FC<{
  step: RagProcessStep;
  isActive: boolean;
  onClick: () => void;
  isLast: boolean;
}> = ({ step, isActive, onClick, isLast }) => {
  const config = STEP_CONFIG[step.type];

  return (
    <div 
      className={`timeline-node ${step.status} ${isActive ? 'active' : ''}`}
      onClick={onClick}
      style={{ '--step-color': config.color } as React.CSSProperties}
    >
      <div className="timeline-icon">{config.icon}</div>
      <div className="timeline-content">
        <div className="timeline-label">{config.label}</div>
        <div className="timeline-status">
          <StatusBadge 
            status={step.status === 'completed' ? 'healthy' : 
                    step.status === 'running' ? 'running' : 
                    step.status === 'failed' ? 'down' : 'unknown'}
            size="small"
          />
        </div>
      </div>
      {step.latency && (
        <div className="timeline-latency">{step.latency}ms</div>
      )}
      {!isLast && <div className="timeline-connector" />}
    </div>
  );
};

// 步骤详情（侧边栏）
const StepDetail: React.FC<{ step: RagProcessStep; originalQuery?: string }> = ({ 
  step,
  originalQuery
}) => {
  const config = STEP_CONFIG[step.type];
  const { data } = step;

  return (
    <div className="step-detail-sidebar">
      <h5 style={{ color: config.color }}>
        {config.icon} {config.label}
      </h5>
      <p className="step-description">{config.description}</p>
      
      {step.status === 'failed' && step.error && (
        <div className="detail-error">
          <span className="error-label">❌ 错误:</span>
          <span className="error-message">{step.error}</span>
        </div>
      )}

      {/* 意图识别详情 */}
      {step.type === 'intent_recognition' && data?.intentType && (
        <div className="detail-section">
          <div className="detail-row">
            <span className="detail-label">识别意图:</span>
            <span className="detail-value intent-badge">{data.intentType}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">置信度:</span>
            <div className="confidence-bar">
              <div 
                className="confidence-fill"
                style={{ width: `${(data.confidence! * 100)}%` }}
              />
              <span>{(data.confidence! * 100).toFixed(1)}%</span>
            </div>
          </div>
        </div>
      )}

      {/* 任务拆解详情 - 使用新组件 */}
      {step.type === 'task_decomposition' && data?.subQueries && (
        <div className="detail-section">
          <TaskDecompositionView
            subQueries={data.subQueries as SubQuery[]}
            originalQuery={originalQuery || ''}
            intent={data.intent}
          />
        </div>
      )}

      {/* 召回详情 - 使用新组件 */}
      {(step.type === 'vector_retrieval' || 
        step.type === 'knowledge_retrieval' || 
        step.type === 'graph_retrieval') && (
        <div className="detail-section">
          <div className="detail-row">
            <span className="detail-label">数据源:</span>
            <span className="detail-value db-badge">{data?.dbType || '-'}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">召回数量:</span>
            <span className="detail-value highlight">{data?.resultCount || 0} 条</span>
          </div>
        </div>
      )}

      {/* 精排详情 */}
      {step.type === 'reranking' && (
        <div className="detail-section">
          <div className="funnel-mini">
            <div className="funnel-in">{data?.inputCount} 候选</div>
            <div className="funnel-arrow">→</div>
            <div className="funnel-out">{data?.outputCount} 结果</div>
          </div>
          <div className="detail-row">
            <span className="detail-label">压缩率:</span>
            <span className="detail-value">
              {data?.inputCount && data?.outputCount
                ? ((1 - data.outputCount / data.inputCount) * 100).toFixed(1)
                : 0}%
            </span>
          </div>
          <div className="detail-row">
            <span className="detail-label">最高分:</span>
            <span className="detail-value highlight">{(data?.topScore! * 100).toFixed(1)}%</span>
          </div>
        </div>
      )}

      {/* Prompt组装详情 - 使用新组件 */}
      {step.type === 'prompt_assembly' && data?.assembly && (
        <div className="detail-section">
          <PromptAssemblyViewer
            assembly={data.assembly as PromptAssembly}
            tokenCount={data.tokenCount}
            contextLength={data.contextLength}
          />
        </div>
      )}

      {/* LLM生成详情 */}
      {step.type === 'llm_generation' && (
        <div className="detail-section">
          <div className="detail-row">
            <span className="detail-label">生成Token:</span>
            <span className="detail-value">{data?.tokensGenerated}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">生成速度:</span>
            <span className="detail-value highlight">
              {data?.tokensPerSecond?.toFixed(1)} tok/s
            </span>
          </div>
          <div className="detail-row">
            <span className="detail-label">首Token延迟:</span>
            <span className="detail-value">{data?.firstTokenLatency}ms</span>
          </div>
        </div>
      )}

      {/* 时间信息 */}
      {(step.startTime || step.endTime) && (
        <div className="detail-timing">
          {step.latency && (
            <div className="timing-total">
              <span>⏱️ 总耗时:</span>
              <strong>{step.latency}ms</strong>
            </div>
          )}
          {step.startTime && (
            <div className="timing-start">
              开始: {new Date(step.startTime).toLocaleTimeString()}
            </div>
          )}
          {step.endTime && (
            <div className="timing-end">
              结束: {new Date(step.endTime).toLocaleTimeString()}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// 步骤详情区块（用于详情视图）
const StepDetailSection: React.FC<{ step: RagProcessStep }> = ({
  step
}) => {
  const config = STEP_CONFIG[step.type];
  const isCompleted = step.status === 'completed';

  return (
    <div className={`step-section ${step.status}`}>
      <div className="section-header-row">
        <span className="section-icon" style={{ color: config.color }}>
          {config.icon}
        </span>
        <span className="section-title">{config.label}</span>
        <StatusBadge 
          status={step.status === 'completed' ? 'healthy' : 
                  step.status === 'running' ? 'running' : 
                  step.status === 'failed' ? 'down' : 'unknown'}
          size="small"
        />
        {step.latency && <span className="section-latency">{step.latency}ms</span>}
      </div>

      {isCompleted && step.data && (
        <div className="section-preview">
          {step.type === 'task_decomposition' && step.data.subQueries && (
            <span>拆分为 {step.data.subQueries.length} 个子查询</span>
          )}
          {(step.type === 'vector_retrieval' || 
            step.type === 'knowledge_retrieval' || 
            step.type === 'graph_retrieval') && step.data.resultCount && (
            <span>召回 {step.data.resultCount} 条结果</span>
          )}
          {step.type === 'reranking' && step.data.outputCount && (
            <span>精排后 {step.data.outputCount} 条</span>
          )}
          {step.type === 'llm_generation' && step.data.tokensGenerated && (
            <span>生成 {step.data.tokensGenerated} tokens</span>
          )}
        </div>
      )}
    </div>
  );
};

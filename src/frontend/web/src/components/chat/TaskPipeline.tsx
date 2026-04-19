/**
 * 任务管道组件
 * 显示 RAG 处理流程的实时进度
 */

export type TaskStage = 
  | 'idle'
  | 'input'
  | 'intent_analysis'
  | 'query_rewrite'
  | 'retrieval'
  | 'rerank'
  | 'context_build'
  | 'generation'
  | 'post_process'
  | 'complete';

interface TaskPipelineProps {
  currentStage: TaskStage;
  query?: string;
}

interface StageInfo {
  id: TaskStage;
  name: string;
  icon: string;
}

const PIPELINE_STAGES: StageInfo[] = [
  { id: 'input', name: '输入', icon: '📝' },
  { id: 'intent_analysis', name: '意图分析', icon: '🎯' },
  { id: 'query_rewrite', name: '查询优化', icon: '✨' },
  { id: 'retrieval', name: '知识检索', icon: '🔍' },
  { id: 'rerank', name: '精排筛选', icon: '📊' },
  { id: 'context_build', name: '构建上下文', icon: '🧩' },
  { id: 'generation', name: '生成回答', icon: '💬' },
  { id: 'post_process', name: '后处理', icon: '🔧' },
  { id: 'complete', name: '完成', icon: '✅' }
];

export const TaskPipeline: React.FC<TaskPipelineProps> = ({ 
  currentStage,
  query
}) => {
  const getStageStatus = (stage: TaskStage): 'pending' | 'running' | 'completed' => {
    const stageIndex = PIPELINE_STAGES.findIndex(s => s.id === stage);
    const currentIndex = PIPELINE_STAGES.findIndex(s => s.id === currentStage);
    
    if (stageIndex < currentIndex) return 'completed';
    if (stageIndex === currentIndex) return 'running';
    return 'pending';
  };

  const currentIndex = PIPELINE_STAGES.findIndex(s => s.id === currentStage);
  const progress = ((currentIndex) / (PIPELINE_STAGES.length - 1)) * 100;

  return (
    <div className="task-pipeline-wrapper">
      {/* 查询显示 */}
      {query && (
        <div className="pipeline-query-display">
          <span className="pipeline-query-icon">💬</span> {query}
        </div>
      )}

      {/* 进度条 */}
      <div className="pipeline-progress-track">
        <div 
          className="pipeline-progress-fill"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* 阶段列表 */}
      <div className="task-pipeline-stages">
        {PIPELINE_STAGES.map((stage, index) => {
          const status = getStageStatus(stage.id);
          
          return (
            <div key={stage.id} className="pipeline-stage-wrapper">
              <div className={`pipeline-stage-badge ${status}`}>
                <span className="pipeline-stage-icon">{stage.icon}</span>
                <span className="pipeline-stage-name">{stage.name}</span>
              </div>
              
              {index < PIPELINE_STAGES.length - 1 && (
                <span className={`pipeline-arrow ${status}`}>▶</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

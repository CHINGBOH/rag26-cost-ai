/**
 * 总览看板
 * 展示系统整体状态、关键指标、活跃会话概览
 */

import { useRecursionStore } from '../../stores/recursionStore';
import { useInfrastructureStore } from '../../stores/infrastructureStore';
import { RadarChart, MetricCard, GaugeChart, StatusBadge } from '../charts';
import { RecursionSession } from '@rag/shared';
import './Dashboard.css';

export const OverviewDashboard: React.FC = () => {
  const sessions = useRecursionStore(state => state.sessions);
  const eventLog = useRecursionStore(state => state.eventLog);
  const overview = useInfrastructureStore(state => state.overview);
  const alerts = useInfrastructureStore(state => state.alerts);
  
  const sessionsList = Array.from(sessions.values());
  const activeSessions = sessionsList.filter(s => 
    s.currentState !== 'completed' && s.currentState !== 'failed'
  );
  
  // 计算平均指标
  const calculateAvgMetrics = () => {
    const rounds = sessionsList.flatMap(s => s.rounds);
    const evaluations = rounds.map(r => r.evaluation).filter(Boolean);
    
    if (evaluations.length === 0) {
      return {
        confidence: 0,
        completeness: 0,
        consistency: 0,
        informationGain: 0,
        sourceDiversity: 0,
        factConsistency: 0
      };
    }
    
    return {
      confidence: evaluations.reduce((sum, e) => sum + e!.confidence, 0) / evaluations.length,
      completeness: evaluations.reduce((sum, e) => sum + e!.completeness, 0) / evaluations.length,
      consistency: evaluations.reduce((sum, e) => sum + e!.consistency, 0) / evaluations.length,
      informationGain: evaluations.reduce((sum, e) => sum + e!.informationGain, 0) / evaluations.length,
      sourceDiversity: evaluations.reduce((sum, e) => sum + e!.sourceDiversity, 0) / evaluations.length,
      factConsistency: evaluations.reduce((sum, e) => sum + e!.factConsistency, 0) / evaluations.length
    };
  };
  
  const avgMetrics = calculateAvgMetrics();
  
  const radarData = [
    { label: '置信度', value: avgMetrics.confidence },
    { label: '完整性', value: avgMetrics.completeness },
    { label: '一致性', value: avgMetrics.consistency },
    { label: '信息增益', value: avgMetrics.informationGain },
    { label: '来源多样', value: avgMetrics.sourceDiversity },
    { label: '事实一致', value: avgMetrics.factConsistency }
  ];
  
  // 计算整体健康度
  const healthScore = overview?.overallHealth === 'healthy' ? 90 :
    overview?.overallHealth === 'degraded' ? 60 : 30;
  
  // 未解决告警
  const unresolvedAlerts = alerts.filter(a => !a.resolved && !a.acknowledged);
  
  // 统计
  const totalChunks = sessionsList.reduce((sum, s) => sum + s.metrics.totalChunksRetrieved, 0);
  const maxDepth = Math.max(0, ...sessionsList.map(s => s.metrics.maxDepthReached));
  
  return (
    <div className="overview-dashboard">
      {/* 顶部指标卡片 */}
      <div className="metrics-grid">
        <MetricCard
          title="系统健康度"
          value={healthScore}
          unit="%"
          status={healthScore >= 80 ? 'good' : healthScore >= 60 ? 'warning' : 'critical'}
          icon="❤️"
          trend={healthScore > 70 ? 'up' : 'down'}
        />
        
        <MetricCard
          title="活跃会话"
          value={activeSessions.length}
          status={activeSessions.length > 0 ? 'good' : 'neutral'}
          icon="💬"
          subtitle={`共 ${sessionsList.length} 个会话`}
        />
        
        <MetricCard
          title="检索文档"
          value={totalChunks}
          status="good"
          icon="📄"
        />
        
        <MetricCard
          title="最大深度"
          value={maxDepth}
          status={maxDepth > 10 ? 'warning' : 'good'}
          icon="📏"
        />
        
        <MetricCard
          title="未解决告警"
          value={unresolvedAlerts.length}
          status={unresolvedAlerts.length === 0 ? 'good' : unresolvedAlerts.some(a => a.level === 'critical') ? 'critical' : 'warning'}
          icon="🔔"
        />
      </div>
      
      {/* 中部可视化区域 */}
      <div className="viz-row">
        <div className="viz-card">
          <h3 className="viz-title">质量指标雷达</h3>
          <div className="viz-content center">
            <RadarChart data={radarData} size={280} />
          </div>
        </div>
        
        <div className="viz-card">
          <h3 className="viz-title">系统健康度</h3>
          <div className="viz-content center">
            <GaugeChart 
              value={healthScore} 
              size={200}
              label="健康度"
              sublabel={overview?.overallHealth || 'unknown'}
            />
          </div>
        </div>
        
        <div className="viz-card">
          <h3 className="viz-title">组件状态概览</h3>
          <div className="viz-content">
            <div className="component-status-list">
              <div className="comp-status-item">
                <span className="comp-name">LLM 服务</span>
                <StatusBadge status={overview?.llmStatus || 'unknown'} size="small" />
              </div>
              <div className="comp-status-item">
                <span className="comp-name">检索引擎</span>
                <StatusBadge status={overview?.retrievalStatus || 'unknown'} size="small" />
              </div>
              <div className="comp-status-item">
                <span className="comp-name">存储层</span>
                <StatusBadge status={overview?.storageStatus || 'unknown'} size="small" />
              </div>
              <div className="comp-status-item">
                <span className="comp-name">数据管道</span>
                <StatusBadge status={overview?.pipelineStatus || 'unknown'} size="small" />
              </div>
            </div>
            
            {overview && (
              <div className="healthy-count">
                <span className="count-value">{overview.healthyComponents}</span>
                <span className="count-total">/{overview.totalComponents}</span>
                <span className="count-label">组件健康</span>
              </div>
            )}
          </div>
        </div>
      </div>
      
      {/* 底部：活跃会话 + 事件日志 */}
      <div className="bottom-row">
        <div className="viz-card flex-2">
          <h3 className="viz-title">活跃会话</h3>
          <div className="viz-content">
            {activeSessions.length === 0 ? (
              <div className="empty-state">暂无活跃会话</div>
            ) : (
              <div className="active-sessions-list">
                {activeSessions.map(session => (
                  <ActiveSessionItem key={session.id} session={session} />
                ))}
              </div>
            )}
          </div>
        </div>
        
        <div className="viz-card flex-1">
          <h3 className="viz-title">最近事件</h3>
          <div className="viz-content">
            {eventLog.slice(0, 10).map((event, idx) => (
              <div key={idx} className="event-item">
                <span className="event-time">
                  {new Date(event.timestamp).toLocaleTimeString()}
                </span>
                <span className="event-type">{event.type}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

// 活跃会话项
const ActiveSessionItem: React.FC<{ session: RecursionSession }> = ({ session }) => {
  const latestRound = session.rounds[session.rounds.length - 1];
  const progress = Math.min(100, (session.currentDepth / 10) * 100);
  
  const stateLabels: Record<string, string> = {
    idle: '就绪',
    decomposing: '拆解',
    dispatching: '分发',
    retrieving: '检索',
    ranking: '精排',
    generating: '生成',
    evaluating: '评估',
    deciding: '决策',
    querying_external: '外查',
    human_review: '审核',
    completed: '完成',
    failed: '失败'
  };
  
  return (
    <div className="active-session-item">
      <div className="session-header">
        <span className="session-query" title={session.originalQuery}>
          {session.originalQuery.slice(0, 40)}
          {session.originalQuery.length > 40 && '...'}
        </span>
        <span className="session-state">{stateLabels[session.currentState] || session.currentState}</span>
      </div>
      
      <div className="session-metrics">
        <span>深度: {session.currentDepth}</span>
        <span>轮次: {session.rounds.length}</span>
        {latestRound?.evaluation && (
          <span>置信: {(latestRound.evaluation.confidence * 100).toFixed(0)}%</span>
        )}
      </div>
      
      <div className="session-progress-bar">
        <div 
          className="session-progress-fill"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
};

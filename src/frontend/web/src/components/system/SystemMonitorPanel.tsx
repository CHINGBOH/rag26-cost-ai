/**
 * 系统监控面板
 * 展示性能指标、资源使用、缓存统计等
 */

import { useSystemStore } from '../../stores/systemStore';
import { useInfrastructureStore } from '../../stores/infrastructureStore';
import { MetricCard, StatusBadge } from '../charts';
import { SystemPerformance } from '@rag/shared';
import './System.css';

export const SystemMonitorPanel: React.FC = () => {
  const performance = useSystemStore(state => state.performance);
  const uptime = useSystemStore(state => state.uptime);
  const version = useSystemStore(state => state.version);
  const alerts = useInfrastructureStore(state => state.alerts);
  
  const unresolvedAlerts = alerts.filter(a => !a.resolved);
  
  const formatUptime = (seconds: number) => {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return `${days}天 ${hours}时 ${mins}分`;
  };
  
  return (
    <div className="system-panel">
      {/* 系统概览 */}
      <section className="system-section">
        <h3 className="section-title">🖥️ 系统概览</h3>
        <div className="system-overview">
          <div className="overview-item">
            <span className="overview-label">系统版本</span>
            <span className="overview-value">v{version}</span>
          </div>
          <div className="overview-item">
            <span className="overview-label">运行时间</span>
            <span className="overview-value">{formatUptime(uptime)}</span>
          </div>
          <div className="overview-item">
            <span className="overview-label">活跃告警</span>
            <span className={`overview-value ${unresolvedAlerts.length > 0 ? 'warning' : ''}`}>
              {unresolvedAlerts.length}
            </span>
          </div>
        </div>
      </section>

      {/* 性能指标 */}
      {performance && (
        <>
          <section className="system-section">
            <h3 className="section-title">⚡ 延迟分解</h3>
            <LatencyBreakdown latency={performance.latency} />
          </section>

          <section className="system-section">
            <h3 className="section-title">📈 吞吐量</h3>
            <ThroughputMetrics throughput={performance.throughput} />
          </section>

          <section className="system-section">
            <h3 className="section-title">💾 资源使用</h3>
            <ResourceUsage resources={performance.resources} />
          </section>

          <section className="system-section">
            <h3 className="section-title">📋 队列深度</h3>
            <QueueDepth queues={performance.queues} />
          </section>

          <section className="system-section">
            <h3 className="section-title">🗂️ 缓存统计</h3>
            <CacheStats cache={performance.cache} />
          </section>
        </>
      )}

      {/* 告警列表 */}
      <section className="system-section">
        <h3 className="section-title">🔔 告警历史</h3>
        <AlertsList alerts={alerts} />
      </section>
    </div>
  );
};

// 延迟分解
const LatencyBreakdown: React.FC<{ latency: SystemPerformance['latency'] }> = ({ latency }) => {
  const stages = [
    { name: '查询拆解', value: latency.decomposition, color: 'var(--color-primary)' },
    { name: '文档召回', value: latency.retrieval, color: 'var(--color-info)' },
    { name: '精排重算', value: latency.reranking, color: 'var(--color-info)' },
    { name: '答案生成', value: latency.generation, color: 'var(--color-success)' },
    { name: '质量评估', value: latency.evaluation, color: 'var(--color-success)' }
  ];
  
  const maxValue = Math.max(...stages.map(s => s.value), latency.total);
  
  return (
    <div className="latency-breakdown">
      {stages.map(stage => (
        <div key={stage.name} className="latency-bar">
          <span className="latency-name">{stage.name}</span>
          <div className="latency-progress">
            <div 
              className="latency-fill"
              style={{ 
                width: `${(stage.value / maxValue) * 100}%`,
                backgroundColor: stage.color
              }}
            />
          </div>
          <span className="latency-value">{stage.value.toFixed(0)}ms</span>
        </div>
      ))}
      <div className="latency-total">
        <span className="total-label">端到端总延迟</span>
        <span className="total-value">{latency.total.toFixed(0)}ms</span>
      </div>
    </div>
  );
};

// 吞吐量指标
const ThroughputMetrics: React.FC<{ throughput: SystemPerformance['throughput'] }> = ({ throughput }) => {
  return (
    <div className="throughput-grid">
      <MetricCard
        title="查询吞吐"
        value={throughput.queriesPerSecond.toFixed(1)}
        unit="QPS"
        status={throughput.queriesPerSecond > 10 ? 'good' : 'neutral'}
        icon="🔍"
      />
      <MetricCard
        title="Token 吞吐"
        value={throughput.tokensPerSecond.toFixed(0)}
        unit="tok/s"
        status="good"
        icon="📝"
      />
      <MetricCard
        title="向量吞吐"
        value={throughput.vectorsPerSecond.toFixed(0)}
        unit="vec/s"
        status="good"
        icon="📊"
      />
    </div>
  );
};

// 资源使用
const ResourceUsage: React.FC<{ resources: SystemPerformance['resources'] }> = ({ resources }) => {
  const cpuStatus = resources.cpuUsage > 80 ? 'critical' : resources.cpuUsage > 60 ? 'warning' : 'good';
  const memoryStatus = resources.memoryUsage > 8000 ? 'critical' : resources.memoryUsage > 4000 ? 'warning' : 'good';
  
  return (
    <div className="resource-grid">
      <div className="resource-item">
        <div className="resource-header">
          <span className="resource-name">CPU</span>
          <span className={`resource-value ${cpuStatus}`}>{resources.cpuUsage.toFixed(1)}%</span>
        </div>
        <div className="resource-bar">
          <div 
            className={`resource-fill ${cpuStatus}`}
            style={{ width: `${resources.cpuUsage}%` }}
          />
        </div>
      </div>
      
      <div className="resource-item">
        <div className="resource-header">
          <span className="resource-name">内存</span>
          <span className={`resource-value ${memoryStatus}`}>
            {(resources.memoryUsage / 1024).toFixed(1)} GB
          </span>
        </div>
        <div className="resource-bar">
          <div 
            className={`resource-fill ${memoryStatus}`}
            style={{ width: `${Math.min(100, (resources.memoryUsage / 16384) * 100)}%` }}
          />
        </div>
      </div>
      
      <div className="resource-item">
        <div className="resource-header">
          <span className="resource-name">磁盘 I/O</span>
          <span className="resource-value">{(resources.diskUsage / 1024).toFixed(1)} MB/s</span>
        </div>
        <div className="resource-bar">
          <div 
            className="resource-fill"
            style={{ width: `${Math.min(100, (resources.diskUsage / 100) * 100)}%` }}
          />
        </div>
      </div>
      
      <div className="resource-item">
        <div className="resource-header">
          <span className="resource-name">网络</span>
          <span className="resource-value">{resources.networkIO.toFixed(1)} MB/s</span>
        </div>
        <div className="resource-bar">
          <div 
            className="resource-fill"
            style={{ width: `${Math.min(100, (resources.networkIO / 100) * 100)}%` }}
          />
        </div>
      </div>
    </div>
  );
};

// 队列深度
const QueueDepth: React.FC<{ queues: SystemPerformance['queues'] }> = ({ queues }) => {
  const getStatus = (value: number, thresholds: [number, number]) => {
    if (value > thresholds[1]) return 'critical';
    if (value > thresholds[0]) return 'warning';
    return 'good';
  };
  
  return (
    <div className="queue-grid">
      <div className="queue-item">
        <div className="queue-info">
          <span className="queue-name">查询队列</span>
          <span className={`queue-value ${getStatus(queues.queryQueue, [50, 100])}`}>
            {queues.queryQueue}
          </span>
        </div>
        <div className="queue-bar">
          <div 
            className={`queue-fill ${getStatus(queues.queryQueue, [50, 100])}`}
            style={{ width: `${Math.min(100, (queues.queryQueue / 150) * 100)}%` }}
          />
        </div>
      </div>
      
      <div className="queue-item">
        <div className="queue-info">
          <span className="queue-name">Embedding 队列</span>
          <span className={`queue-value ${getStatus(queues.embeddingQueue, [100, 200])}`}>
            {queues.embeddingQueue}
          </span>
        </div>
        <div className="queue-bar">
          <div 
            className={`queue-fill ${getStatus(queues.embeddingQueue, [100, 200])}`}
            style={{ width: `${Math.min(100, (queues.embeddingQueue / 300) * 100)}%` }}
          />
        </div>
      </div>
      
      <div className="queue-item">
        <div className="queue-info">
          <span className="queue-name">索引队列</span>
          <span className={`queue-value ${getStatus(queues.indexQueue, [50, 100])}`}>
            {queues.indexQueue}
          </span>
        </div>
        <div className="queue-bar">
          <div 
            className={`queue-fill ${getStatus(queues.indexQueue, [50, 100])}`}
            style={{ width: `${Math.min(100, (queues.indexQueue / 150) * 100)}%` }}
          />
        </div>
      </div>
    </div>
  );
};

// 缓存统计
const CacheStats: React.FC<{ cache: SystemPerformance['cache'] }> = ({ cache }) => {
  return (
    <div className="cache-grid">
      <div className="cache-item">
        <span className="cache-name">查询缓存</span>
        <div className="cache-gauge">
          <div 
            className="cache-fill"
            style={{ width: `${cache.queryCacheHitRate * 100}%` }}
          />
        </div>
        <span className="cache-value">{(cache.queryCacheHitRate * 100).toFixed(1)}%</span>
      </div>
      
      <div className="cache-item">
        <span className="cache-name">Embedding 缓存</span>
        <div className="cache-gauge">
          <div 
            className="cache-fill"
            style={{ width: `${cache.embeddingCacheHitRate * 100}%` }}
          />
        </div>
        <span className="cache-value">{(cache.embeddingCacheHitRate * 100).toFixed(1)}%</span>
      </div>
      
      <div className="cache-item">
        <span className="cache-name">结果缓存</span>
        <div className="cache-gauge">
          <div 
            className="cache-fill"
            style={{ width: `${cache.resultCacheHitRate * 100}%` }}
          />
        </div>
        <span className="cache-value">{(cache.resultCacheHitRate * 100).toFixed(1)}%</span>
      </div>
    </div>
  );
};

// 告警列表
const AlertsList: React.FC<{ alerts: import('@rag/shared').Alert[] }> = ({ alerts }) => {
  if (alerts.length === 0) {
    return <div className="empty-alerts">暂无告警</div>;
  }
  
  return (
    <div className="alerts-list">
      {alerts.slice(0, 20).map(alert => (
        <div key={alert.id} className={`alert-item ${alert.level} ${alert.resolved ? 'resolved' : ''}`}>
          <div className="alert-header">
            <StatusBadge 
              status={alert.level === 'critical' ? 'down' : alert.level === 'warning' ? 'degraded' : 'healthy'} 
              size="small"
              text={alert.level}
            />
            <span className="alert-time">
              {new Date(alert.timestamp).toLocaleString()}
            </span>
            {alert.resolved && (
              <span className="alert-resolved">已解决</span>
            )}
          </div>
          <div className="alert-title">{alert.title}</div>
          <div className="alert-message">{alert.message}</div>
          <div className="alert-component">📍 {alert.component}</div>
        </div>
      ))}
    </div>
  );
};

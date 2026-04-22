import React from 'react';
import { DatabaseHealth } from './types';

interface DatabaseStatusPanelProps {
  health: DatabaseHealth;
}

const DatabaseCard: React.FC<{
  name: string;
  icon: string;
  data: { status: 'healthy' | 'degraded' | 'down'; latency: number; count: number };
  description: string;
}> = ({ name, icon, data, description }) => {
  const statusColors = {
    healthy: '#52c41a',
    degraded: '#faad14',
    down: '#f5222d'
  };

  const statusText = {
    healthy: '健康',
    degraded: '降级',
    down: '宕机'
  };

  return (
    <div className={`database-card ${data.status}`}>
      <div className="card-header">
        <span className="icon">{icon}</span>
        <h4>{name}</h4>
        <span className="status-badge" style={{ backgroundColor: statusColors[data.status] }}>
          {statusText[data.status]}
        </span>
      </div>
      <p className="description">{description}</p>
      <div className="metrics">
        <div className="metric">
          <span className="label">响应延迟</span>
          <span className="value">{data.latency}ms</span>
        </div>
        <div className="metric">
          <span className="label">文档数量</span>
          <span className="value">{data.count.toLocaleString()}</span>
        </div>
      </div>
    </div>
  );
};

export const DatabaseStatusPanel: React.FC<DatabaseStatusPanelProps> = ({ health }) => {
  return (
    <div className="database-status-panel">
      <h3>🗄️ 四库状态监控</h3>
      <div className="database-grid">
        <DatabaseCard
          name="向量库 (Qdrant)"
          icon="🔍"
          data={health.vector}
          description="存储文档向量嵌入，支持语义检索"
        />
        <DatabaseCard
          name="关键词库 (ES)"
          icon="📝"
          data={health.keyword}
          description="存储全文索引，支持BM25关键词检索"
        />
        <DatabaseCard
          name="图库 (Neo4j)"
          icon="🕸️"
          data={health.graph}
          description="存储实体关系图谱，支持关联查询"
        />
        <DatabaseCard
          name="缓存 (Redis)"
          icon="⚡"
          data={health.cache}
          description="高速缓存层，加速热点数据访问"
        />
      </div>

      <div className="health-summary">
        <h4>健康度汇总</h4>
        <div className="health-bar">
          {Object.entries(health).map(([key, data]) => (
            <div 
              key={key}
              className={`health-segment ${data.status}`}
              style={{ width: '25%' }}
              title={`${key}: ${data.status}`}
            />
          ))}
        </div>
        <div className="health-legend">
          <span><span className="dot healthy" /> 健康</span>
          <span><span className="dot degraded" /> 降级</span>
          <span><span className="dot down" /> 宕机</span>
        </div>
      </div>
    </div>
  );
};

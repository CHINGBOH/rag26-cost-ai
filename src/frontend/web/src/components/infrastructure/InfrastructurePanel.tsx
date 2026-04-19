/**
 * 基础设施监控面板
 * 展示 LLM、数据库、服务、数据管道等全链路组件状态
 */

import { useInfrastructureStore } from '../../stores/infrastructureStore';
import { MetricCard, StatusBadge } from '../charts';
import { LLMProvider, VectorDB, GraphDB, DataPipeline } from '@rag/shared';
import './Infrastructure.css';

export const InfrastructurePanel: React.FC = () => {
  const {
    llmProviders,
    vectorDBs,
    graphDBs,
    knowledgeBases,
    embeddingServices,
    rerankServices,
    dataPipelines,
    retrievalEngines,
    dataConsistency
  } = useInfrastructureStore();

  return (
    <div className="infrastructure-panel">
      {/* LLM 提供者 */}
      <section className="infra-section">
        <h3 className="section-title">🤖 LLM 服务</h3>
        <div className="llm-grid">
          {llmProviders.length === 0 ? (
            <EmptyState message="暂无 LLM 提供者配置" />
          ) : (
            llmProviders.map(provider => (
              <LLMProviderCard key={provider.id} provider={provider} />
            ))
          )}
        </div>
      </section>

      {/* 数据存储层 - 四库 */}
      <section className="infra-section">
        <h3 className="section-title">🗄️ 数据存储层（四库）</h3>
        <div className="storage-grid">
          {/* 向量库 */}
          <div className="storage-group">
            <h4 className="group-title">向量数据库</h4>
            {vectorDBs.length === 0 ? (
              <EmptyState message="未配置向量数据库" />
            ) : (
              vectorDBs.map(db => <VectorDBCard key={db.id} db={db} />)
            )}
          </div>

          {/* 知识库 */}
          <div className="storage-group">
            <h4 className="group-title">知识库</h4>
            {knowledgeBases.length === 0 ? (
              <EmptyState message="未配置知识库" />
            ) : (
              knowledgeBases.map(kb => (
                <div key={kb.id} className="kb-card">
                  <div className="kb-header">
                    <span className="kb-name">{kb.name}</span>
                    <StatusBadge status={kb.status} size="small" />
                  </div>
                  <div className="kb-stats">
                    <span>📄 {kb.documentCount.toLocaleString()} 文档</span>
                    <span>🧩 {kb.chunkCount.toLocaleString()} 片段</span>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* 图数据库 */}
          <div className="storage-group">
            <h4 className="group-title">知识图谱</h4>
            {graphDBs.length === 0 ? (
              <EmptyState message="未配置图数据库" />
            ) : (
              graphDBs.map(db => <GraphDBCard key={db.id} db={db} />)
            )}
          </div>
        </div>

        {/* 数据一致性 */}
        {dataConsistency && (
          <div className="consistency-panel">
            <h4 className="group-title">数据一致性</h4>
            <div className="consistency-metrics">
              <MetricCard
                title="向量→知识库延迟"
                value={dataConsistency.vectorToKnowledgeLag}
                unit="s"
                status={dataConsistency.vectorToKnowledgeLag > 300 ? 'warning' : 'good'}
              />
              <MetricCard
                title="知识库→图谱延迟"
                value={dataConsistency.knowledgeToGraphLag}
                unit="s"
                status={dataConsistency.knowledgeToGraphLag > 600 ? 'warning' : 'good'}
              />
              <MetricCard
                title="不一致条目"
                value={dataConsistency.inconsistenciesFound}
                status={dataConsistency.inconsistenciesFound > 0 ? 'warning' : 'good'}
              />
            </div>
          </div>
        )}
      </section>

      {/* 检索与生成服务 */}
      <section className="infra-section">
        <h3 className="section-title">⚡ 检索与生成服务</h3>
        <div className="service-grid">
          {/* Embedding 服务 */}
          <div className="service-group">
            <h4 className="group-title">Embedding 服务</h4>
            {embeddingServices.length === 0 ? (
              <EmptyState message="未配置 Embedding 服务" />
            ) : (
              embeddingServices.map(service => (
                <div key={service.id} className="service-card">
                  <div className="service-header">
                    <span className="service-name">{service.model}</span>
                    <StatusBadge status={service.status} size="small" />
                  </div>
                  <div className="service-metrics">
                    <span>📐 {service.dimensions} 维</span>
                    <span>⚡ {service.throughput.toFixed(0)} vec/s</span>
                    <span>💾 {service.cacheHitRate.toFixed(1)}% 缓存</span>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Rerank 服务 */}
          <div className="service-group">
            <h4 className="group-title">Rerank 服务</h4>
            {rerankServices.length === 0 ? (
              <EmptyState message="未配置 Rerank 服务" />
            ) : (
              rerankServices.map(service => (
                <div key={service.id} className="service-card">
                  <div className="service-header">
                    <span className="service-name">{service.model}</span>
                    <StatusBadge status={service.status} size="small" />
                  </div>
                  <div className="service-metrics">
                    <span>⏱️ {service.latency.toFixed(0)}ms</span>
                    <span>📊 {(service.avgScore * 100).toFixed(1)}% 平均分</span>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* 检索引擎 */}
          <div className="service-group">
            <h4 className="group-title">检索引擎</h4>
            {retrievalEngines.length === 0 ? (
              <EmptyState message="未配置检索引擎" />
            ) : (
              retrievalEngines.map(engine => (
                <div key={engine.id} className="service-card">
                  <div className="service-header">
                    <span className="service-name">{engine.name}</span>
                    <StatusBadge status={engine.status} size="small" />
                  </div>
                  <div className="service-metrics">
                    <span>🔍 Top-{engine.topK}</span>
                    <span>📈 {(engine.cacheHitRate * 100).toFixed(1)}% 缓存</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </section>

      {/* 数据处理管道 */}
      <section className="infra-section">
        <h3 className="section-title">🔄 数据处理管道</h3>
        <div className="pipeline-grid">
          {dataPipelines.length === 0 ? (
            <EmptyState message="未配置数据管道" />
          ) : (
            dataPipelines.map(pipeline => (
              <PipelineCard key={pipeline.id} pipeline={pipeline} />
            ))
          )}
        </div>
      </section>
    </div>
  );
};

// LLM 提供者卡片
const LLMProviderCard: React.FC<{ provider: LLMProvider }> = ({ provider }) => {
  const successRate = provider.requestSuccessRate * 100;
  
  return (
    <div className={`llm-card ${provider.status}`}>
      <div className="llm-header">
        <div className="llm-info">
          <span className="llm-name">{provider.name}</span>
          <span className="llm-model">{provider.model}</span>
        </div>
        <StatusBadge status={provider.status} />
      </div>
      
      <div className="llm-metrics">
        <div className="llm-metric">
          <span className="metric-label">延迟</span>
          <span className="metric-value">{provider.latency.p95.toFixed(0)}ms</span>
        </div>
        <div className="llm-metric">
          <span className="metric-label">吞吐</span>
          <span className="metric-value">{provider.tokenThroughput.toFixed(0)}/s</span>
        </div>
        <div className="llm-metric">
          <span className="metric-label">成功率</span>
          <span className={`metric-value ${successRate < 95 ? 'warning' : ''}`}>
            {successRate.toFixed(1)}%
          </span>
        </div>
        <div className="llm-metric">
          <span className="metric-label">队列</span>
          <span className={`metric-value ${provider.queueLength > 10 ? 'warning' : ''}`}>
            {provider.queueLength}
          </span>
        </div>
      </div>
      
      <div className="llm-footer">
        <span className="llm-capabilities">
          {provider.capabilities.join(' · ')}
        </span>
        <span className="llm-version">v{provider.modelVersion}</span>
      </div>
    </div>
  );
};

// 向量数据库卡片
const VectorDBCard: React.FC<{ db: VectorDB }> = ({ db }) => {
  return (
    <div className={`db-card ${db.status}`}>
      <div className="db-header">
        <span className="db-name">{db.name}</span>
        <StatusBadge status={db.status === 'connected' ? 'healthy' : db.status === 'degraded' ? 'degraded' : 'down'} />
      </div>
      <div className="db-type">{db.type} · v{db.version}</div>
      
      <div className="db-stats">
        <div className="db-stat">
          <span className="stat-label">向量数</span>
          <span className="stat-value">{db.vectorCount.toLocaleString()}</span>
        </div>
        <div className="db-stat">
          <span className="stat-label">集合</span>
          <span className="stat-value">{db.collections}</span>
        </div>
        <div className="db-stat">
          <span className="stat-label">查询延迟</span>
          <span className="stat-value">{db.queryLatency.p95.toFixed(0)}ms</span>
        </div>
      </div>
      
      {db.indexStatus !== 'ready' && (
        <div className="db-index-status">
          <span className="index-label">索引状态:</span>
          <span className={`index-value ${db.indexStatus}`}>
            {db.indexStatus} {db.indexProgress && `(${db.indexProgress.toFixed(0)}%)`}
          </span>
        </div>
      )}
    </div>
  );
};

// 图数据库卡片
const GraphDBCard: React.FC<{ db: GraphDB }> = ({ db }) => {
  return (
    <div className={`db-card ${db.status}`}>
      <div className="db-header">
        <span className="db-name">{db.name}</span>
        <StatusBadge status={db.status === 'connected' ? 'healthy' : 'down'} />
      </div>
      <div className="db-type">{db.type} · v{db.version}</div>
      
      <div className="db-stats">
        <div className="db-stat">
          <span className="stat-label">节点</span>
          <span className="stat-value">{db.nodeCount.toLocaleString()}</span>
        </div>
        <div className="db-stat">
          <span className="stat-label">关系</span>
          <span className="stat-value">{db.edgeCount.toLocaleString()}</span>
        </div>
      </div>
      
      <div className="db-backup">
        上次备份: {new Date(db.lastBackup).toLocaleDateString()}
      </div>
    </div>
  );
};

// 数据管道卡片
const PipelineCard: React.FC<{ pipeline: DataPipeline }> = ({ pipeline }) => {
  const stages: { key: keyof DataPipeline; label: string; icon: string }[] = [
    { key: 'totalProcessed', label: '已处理', icon: '✅' },
    { key: 'totalFailed', label: '失败', icon: '❌' },
    { key: 'pendingReview', label: '待审', icon: '👁️' }
  ];

  return (
    <div className={`pipeline-card ${pipeline.status}`}>
      <div className="pipeline-header">
        <span className="pipeline-name">{pipeline.name}</span>
        <StatusBadge 
          status={pipeline.status === 'running' ? 'running' : pipeline.status === 'paused' ? 'idle' : 'error'} 
        />
      </div>
      
      <div className="pipeline-stats">
        {stages.map(stage => (
          <div key={stage.key} className="pipeline-stat">
            <span className="stat-icon">{stage.icon}</span>
            <span className="stat-label">{stage.label}</span>
            <span className="stat-value">
              {(pipeline[stage.key] as number).toLocaleString()}
            </span>
          </div>
        ))}
      </div>
      
      <div className="pipeline-metrics">
        <div className="pipeline-metric">
          <span className="metric-label">队列长度</span>
          <span className={`metric-value ${pipeline.queueLength > 100 ? 'warning' : ''}`}>
            {pipeline.queueLength}
          </span>
        </div>
        <div className="pipeline-metric">
          <span className="metric-label">处理速度</span>
          <span className="metric-value">{pipeline.processingRate.toFixed(1)} 文档/分</span>
        </div>
        <div className="pipeline-metric">
          <span className="metric-label">OCR 准确率</span>
          <span className="metric-value">{(pipeline.ocrAccuracy * 100).toFixed(1)}%</span>
        </div>
      </div>
    </div>
  );
};

// 空状态
const EmptyState: React.FC<{ message: string }> = ({ message }) => (
  <div className="infra-empty-state">{message}</div>
);

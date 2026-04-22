import React from 'react';
import { EvaluationMetrics } from './types';

interface EvaluationPanelProps {
  metrics: EvaluationMetrics;
}

const MetricCard: React.FC<{
  title: string;
  icon: string;
  metrics: { label: string; value: string | number; unit?: string; trend?: 'up' | 'down' | 'stable' }[];
}> = ({ title, icon, metrics }) => {
  return (
    <div className="metric-card">
      <h4><span className="icon">{icon}</span> {title}</h4>
      <div className="metric-list">
        {metrics.map((m, idx) => (
          <div key={idx} className="metric-row">
            <span className="metric-label">{m.label}</span>
            <span className={`metric-value ${m.trend || ''}`}>
              {m.value}{m.unit && <span className="unit">{m.unit}</span>}
              {m.trend && (
                <span className={`trend ${m.trend}`}>
                  {m.trend === 'up' ? '↑' : m.trend === 'down' ? '↓' : '→'}
                </span>
              )}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};

export const EvaluationPanel: React.FC<EvaluationPanelProps> = ({ metrics }) => {
  const embeddingMetrics = [
    { label: '平均处理时间', value: metrics.embedding.averageTime.toFixed(2), unit: 'ms', trend: 'down' as const },
    { label: '成功率', value: metrics.embedding.successRate.toFixed(1), unit: '%', trend: 'up' as const },
    { label: '队列大小', value: metrics.embedding.queueSize, unit: '个' },
    { label: '批处理大小', value: metrics.embedding.batchSize, unit: '个' },
  ];

  const rerankMetrics = [
    { label: '平均处理时间', value: metrics.rerank.averageTime.toFixed(2), unit: 'ms', trend: 'down' as const },
    { label: '成功率', value: metrics.rerank.successRate.toFixed(1), unit: '%', trend: 'up' as const },
    { label: 'Cross-Encoder延迟', value: metrics.rerank.crossEncoderLatency.toFixed(2), unit: 'ms', trend: 'down' as const },
    { label: '融合分数精度', value: metrics.rerank.fusionScoreAccuracy.toFixed(2), unit: '%', trend: 'up' as const },
  ];

  return (
    <div className="evaluation-panel">
      <h3>📈 模型评估指标</h3>
      
      <div className="evaluation-grid">
        <MetricCard
          title="Embedding 服务"
          icon="🔤"
          metrics={embeddingMetrics}
        />
        <MetricCard
          title="Rerank 服务"
          icon="📊"
          metrics={rerankMetrics}
        />
      </div>

      <div className="evaluation-details">
        <h4>模型信息</h4>
        <div className="model-info">
          <div className="model-card">
            <h5>Embedding Model</h5>
            <p className="model-name">BAAI/bge-m3</p>
            <p className="model-desc">1024维向量，支持多语言</p>
            <div className="model-stats">
              <span>维度: 1024</span>
              <span>语言: 多语言</span>
            </div>
          </div>
          <div className="model-card">
            <h5>Reranker Model</h5>
            <p className="model-name">BAAI/bge-reranker-large</p>
            <p className="model-desc">Cross-Encoder精排模型</p>
            <div className="model-stats">
              <span>架构: Cross-Encoder</span>
              <span>精度: 高</span>
            </div>
          </div>
        </div>
      </div>

      <div className="score-explanation">
        <h4>分数融合权重</h4>
        <div className="weight-bars">
          <div className="weight-item">
            <span className="label">Rerank (精排)</span>
            <div className="bar">
              <div className="fill" style={{ width: '40%', background: '#1890ff' }} />
            </div>
            <span className="value">40%</span>
          </div>
          <div className="weight-item">
            <span className="label">Vector (向量)</span>
            <div className="bar">
              <div className="fill" style={{ width: '30%', background: '#52c41a' }} />
            </div>
            <span className="value">30%</span>
          </div>
          <div className="weight-item">
            <span className="label">Keyword (关键词)</span>
            <div className="bar">
              <div className="fill" style={{ width: '20%', background: '#faad14' }} />
            </div>
            <span className="value">20%</span>
          </div>
          <div className="weight-item">
            <span className="label">Graph (图谱)</span>
            <div className="bar">
              <div className="fill" style={{ width: '5%', background: '#722ed1' }} />
            </div>
            <span className="value">5%</span>
          </div>
          <div className="weight-item">
            <span className="label">Time (时间)</span>
            <div className="bar">
              <div className="fill" style={{ width: '5%', background: '#eb2f96' }} />
            </div>
            <span className="value">5%</span>
          </div>
        </div>
      </div>
    </div>
  );
};

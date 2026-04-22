import React from 'react';
import { PipelineStats, DatabaseHealth } from './types';

interface DataFlowVisualizationProps {
  stats: PipelineStats;
  dbHealth: DatabaseHealth;
}

export const DataFlowVisualization: React.FC<DataFlowVisualizationProps> = ({ stats, dbHealth }) => {
  const allHealthy = Object.values(dbHealth).every(d => d.status === 'healthy');

  return (
    <div className="data-flow-visualization">
      <h3>🌊 数据流可视化</h3>
      
      <div className="flow-diagram">
        {/* 输入层 */}
        <div className="flow-layer input-layer">
          <div className="layer-title">📤 输入层</div>
          <div className="nodes">
            <div className="node file-upload">
              <span className="icon">📁</span>
              <span className="label">文件上传</span>
              <span className="count">{stats.totalFiles}</span>
            </div>
          </div>
        </div>

        {/* 箭头 */}
        <div className="flow-arrow">⬇</div>

        {/* 处理层 */}
        <div className="flow-layer processing-layer">
          <div className="layer-title">⚙️ 处理层</div>
          <div className="nodes">
            <div className="node ocr">
              <span className="icon">👁️</span>
              <span className="label">OCR识别</span>
              <span className="count">{stats.processingFiles}</span>
            </div>
            <div className="node embedding">
              <span className="icon">🔤</span>
              <span className="label">Embedding</span>
              <span className="count">{stats.queueLength}</span>
            </div>
            <div className="node chunking">
              <span className="icon">✂️</span>
              <span className="label">文本分块</span>
            </div>
          </div>
        </div>

        {/* 箭头 */}
        <div className="flow-arrow">⬇</div>

        {/* 存储层 - 四库 */}
        <div className="flow-layer storage-layer">
          <div className="layer-title">🗄️ 存储层 (四库联动)</div>
          <div className="nodes">
            <div className={`node db-vector ${dbHealth.vector.status}`}>
              <span className="icon">🔍</span>
              <span className="label">向量库</span>
              <span className="count">{dbHealth.vector.count}</span>
            </div>
            <div className={`node db-keyword ${dbHealth.keyword.status}`}>
              <span className="icon">📝</span>
              <span className="label">关键词库</span>
              <span className="count">{dbHealth.keyword.count}</span>
            </div>
            <div className={`node db-graph ${dbHealth.graph.status}`}>
              <span className="icon">🕸️</span>
              <span className="label">图库</span>
              <span className="count">{dbHealth.graph.count}</span>
            </div>
            <div className={`node db-cache ${dbHealth.cache.status}`}>
              <span className="icon">⚡</span>
              <span className="label">缓存</span>
            </div>
          </div>
        </div>

        {/* 箭头 */}
        <div className="flow-arrow">⬇</div>

        {/* 服务层 */}
        <div className="flow-layer service-layer">
          <div className="layer-title">🔍 服务层</div>
          <div className="nodes">
            <div className="node retrieval">
              <span className="icon">🎯</span>
              <span className="label">召回精排</span>
            </div>
            <div className="node rerank">
              <span className="icon">📊</span>
              <span className="label">Cross-Encoder</span>
            </div>
          </div>
        </div>

        {/* 箭头 */}
        <div className="flow-arrow">⬇</div>

        {/* 输出层 */}
        <div className="flow-layer output-layer">
          <div className="layer-title">✅ 输出层</div>
          <div className="nodes">
            <div className="node completed">
              <span className="icon">✓</span>
              <span className="label">处理完成</span>
              <span className="count">{stats.completedFiles}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="flow-stats">
        <div className="stat-item">
          <span className="label">整体健康度</span>
          <span className={`value ${allHealthy ? 'healthy' : 'warning'}`}>
            {allHealthy ? '✅ 优秀' : '⚠️ 需关注'}
          </span>
        </div>
        <div className="stat-item">
          <span className="label">吞吐量</span>
          <span className="value">{stats.throughput.toFixed(1)} 文件/分</span>
        </div>
        <div className="stat-item">
          <span className="label">成功率</span>
          <span className="value">
            {stats.totalFiles > 0 
              ? ((stats.completedFiles / stats.totalFiles) * 100).toFixed(1) 
              : 100}%
          </span>
        </div>
      </div>
    </div>
  );
};

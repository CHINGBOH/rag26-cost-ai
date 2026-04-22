import React from 'react';
import { PipelineStats } from './types';

interface PipelineMetricsProps {
  stats: PipelineStats;
}

export const PipelineMetrics: React.FC<PipelineMetricsProps> = ({ stats }) => {
  const successRate = stats.totalFiles > 0 
    ? (stats.completedFiles / stats.totalFiles) * 100 
    : 100;

  return (
    <div className="pipeline-metrics">
      <div className="metric-item">
        <span className="metric-icon">📁</span>
        <div className="metric-data">
          <span className="metric-value">{stats.totalFiles}</span>
          <span className="metric-label">总文件</span>
        </div>
      </div>
      <div className="metric-item">
        <span className="metric-icon">✅</span>
        <div className="metric-data">
          <span className="metric-value">{stats.completedFiles}</span>
          <span className="metric-label">成功</span>
        </div>
      </div>
      <div className="metric-item">
        <span className="metric-icon">❌</span>
        <div className="metric-data">
          <span className="metric-value">{stats.failedFiles}</span>
          <span className="metric-label">失败</span>
        </div>
      </div>
      <div className="metric-item">
        <span className="metric-icon">⚙️</span>
        <div className="metric-data">
          <span className="metric-value">{stats.processingFiles}</span>
          <span className="metric-label">处理中</span>
        </div>
      </div>
      <div className="metric-item">
        <span className="metric-icon">📊</span>
        <div className="metric-data">
          <span className="metric-value">{successRate.toFixed(1)}%</span>
          <span className="metric-label">成功率</span>
        </div>
      </div>
      <div className="metric-item">
        <span className="metric-icon">⏱️</span>
        <div className="metric-data">
          <span className="metric-value">
            {stats.averageProcessingTime < 1000 
              ? `${stats.averageProcessingTime.toFixed(0)}ms`
              : `${(stats.averageProcessingTime / 1000).toFixed(1)}s`}
          </span>
          <span className="metric-label">平均耗时</span>
        </div>
      </div>
    </div>
  );
};

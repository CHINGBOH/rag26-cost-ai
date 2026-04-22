import React from 'react';
import { UploadFile, PipelineStats } from './types';

interface ProcessingQueueProps {
  queue: UploadFile[];
  onRemove: (fileId: string) => void;
  onClearCompleted: () => void;
  onRetry: (fileId: string) => void;
  stats: PipelineStats;
}

const formatFileSize = (bytes: number): string => {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(2) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
};

const formatDuration = (ms: number): string => {
  if (ms < 1000) return ms + 'ms';
  if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
  return (ms / 60000).toFixed(1) + 'min';
};

export const ProcessingQueue: React.FC<ProcessingQueueProps> = ({
  queue,
  onRemove,
  onClearCompleted,
  onRetry,
  stats
}) => {
  const pendingCount = queue.filter(f => f.status === 'pending').length;
  const uploadingCount = queue.filter(f => f.status === 'uploading').length;
  const processingCount = queue.filter(f => f.status === 'processing').length;
  const completedCount = queue.filter(f => f.status === 'completed').length;
  const failedCount = queue.filter(f => f.status === 'failed').length;

  return (
    <div className="processing-queue">
      <div className="queue-header">
        <h3>📋 处理队列</h3>
        <div className="queue-stats">
          <span className="stat pending">待处理: {pendingCount}</span>
          <span className="stat uploading">上传中: {uploadingCount}</span>
          <span className="stat processing">处理中: {processingCount}</span>
          <span className="stat completed">成功: {completedCount}</span>
          <span className="stat failed">失败: {failedCount}</span>
          {completedCount > 0 && (
            <button className="clear-btn" onClick={onClearCompleted}>
              清除已完成
            </button>
          )}
        </div>
      </div>

      {queue.length === 0 ? (
        <div className="empty-queue">
          <p>暂无文件</p>
          <p className="hint">上传文件后将显示在这里</p>
        </div>
      ) : (
        <div className="queue-list">
          {queue.map(file => (
            <div key={file.id} className={`queue-item ${file.status}`}>
              <div className="file-info">
                <div className="file-icon">
                  {file.name.endsWith('.pdf') ? '📄' : 
                   file.name.endsWith('.png') || file.name.endsWith('.jpg') ? '🖼️' : '📃'}
                </div>
                <div className="file-details">
                  <span className="file-name" title={file.name}>{file.name}</span>
                  <span className="file-size">{formatFileSize(file.size)}</span>
                </div>
              </div>

              <div className="progress-section">
                {file.status === 'failed' ? (
                  <span className="error-message" title={file.error}>❌ {file.error}</span>
                ) : (
                  <>
                    <div className="progress-bar">
                      <div 
                        className="progress-fill" 
                        style={{ width: `${file.progress}%` }}
                      />
                    </div>
                    <span className="progress-text">{file.progress}%</span>
                  </>
                )}
                {file.stage && <span className="stage">{file.stage}</span>}
              </div>

              <div className="file-actions">
                {file.status === 'failed' && (
                  <button className="retry-btn" onClick={() => onRetry(file.id)}>重试</button>
                )}
                {(file.status === 'completed' || file.status === 'failed') && (
                  <button className="remove-btn" onClick={() => onRemove(file.id)}>删除</button>
                )}
                {file.status === 'processing' && (
                  <span className="processing-indicator">
                    <span className="dot" />
                    <span className="dot" />
                    <span className="dot" />
                  </span>
                )}
              </div>

              <div className="timing">
                {file.endTime ? (
                  <span>耗时: {formatDuration(file.endTime - file.startTime)}</span>
                ) : (
                  <span>已用时: {formatDuration(Date.now() - file.startTime)}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {stats.throughput > 0 && (
        <div className="throughput-info">
          <span>⚡ 当前吞吐量: {stats.throughput.toFixed(1)} 文件/分钟</span>
          <span>⏱️ 平均处理时间: {formatDuration(stats.averageProcessingTime)}</span>
        </div>
      )}
    </div>
  );
};

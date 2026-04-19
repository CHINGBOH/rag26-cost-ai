/**
 * 任务拆解可视化组件
 * 展示查询被分解为子查询的过程
 */

import { useState } from 'react';
import { SubQuery } from '@rag/shared';
import './Chat.css';

interface TaskDecompositionViewProps {
  subQueries: SubQuery[];
  originalQuery: string;
  intent?: {
    type: string;
    confidence: number;
  };
}

export const TaskDecompositionView: React.FC<TaskDecompositionViewProps> = ({
  subQueries,
  originalQuery,
  intent
}) => {
  const [expandedQuery, setExpandedQuery] = useState<string | null>(null);

  const getTargetDBIcon = (targetDB: string) => {
    const icons: Record<string, string> = {
      vector: '📊',
      knowledge: '📚',
      graph: '🕸️',
      sql: '🗃️'
    };
    return icons[targetDB] || '📄';
  };

  const getTargetDBLabel = (targetDB: string) => {
    const labels: Record<string, string> = {
      vector: '向量库',
      knowledge: '知识库',
      graph: '知识图谱',
      sql: '数据库'
    };
    return labels[targetDB] || targetDB;
  };

  const getStatusIcon = (status: string) => {
    const icons: Record<string, string> = {
      pending: '⏳',
      running: '◐',
      completed: '✓',
      failed: '✗'
    };
    return icons[status] || '○';
  };

  return (
    <div className="task-decomposition-view">
      {/* 原始查询 */}
      <div className="original-query-section">
        <div className="section-label">📝 原始查询</div>
        <div className="original-query-text">{originalQuery}</div>
        {intent && (
          <div className="intent-badge">
            <span className="intent-type">{intent.type}</span>
            <span className="intent-confidence">
              {(intent.confidence * 100).toFixed(0)}%
            </span>
          </div>
        )}
      </div>

      {/* 拆解流程箭头 */}
      <div className="decomposition-arrow">
        <span>↓ 拆解为 {subQueries.length} 个子任务</span>
      </div>

      {/* 子查询列表 */}
      <div className="subqueries-container">
        {subQueries.map((sq, index) => (
          <div
            key={sq.id}
            className={`subquery-card ${sq.status} ${expandedQuery === sq.id ? 'expanded' : ''}`}
            onClick={() => setExpandedQuery(expandedQuery === sq.id ? null : sq.id)}
          >
            {/* 头部 */}
            <div className="subquery-header">
              <div className="sq-number">{index + 1}</div>
              <div className="sq-status-icon">{getStatusIcon(sq.status)}</div>
              <div className="sq-target-db">
                <span className="db-icon">{getTargetDBIcon(sq.targetDB)}</span>
                <span className="db-label">{getTargetDBLabel(sq.targetDB)}</span>
              </div>
              <div className="sq-query-text">{sq.query}</div>
              {sq.latency && (
                <div className="sq-latency">{sq.latency}ms</div>
              )}
            </div>

            {/* 展开详情 */}
            {expandedQuery === sq.id && (
              <div className="subquery-details">
                <div className="detail-grid">
                  <div className="detail-item">
                    <span className="label">目标数据库:</span>
                    <span className="value">{getTargetDBLabel(sq.targetDB)}</span>
                  </div>
                  <div className="detail-item">
                    <span className="label">执行状态:</span>
                    <span className={`value status-${sq.status}`}>{sq.status}</span>
                  </div>
                  {sq.resultCount !== undefined && (
                    <div className="detail-item">
                      <span className="label">召回结果:</span>
                      <span className="value">{sq.resultCount} 条</span>
                    </div>
                  )}
                  {sq.latency !== undefined && (
                    <div className="detail-item">
                      <span className="label">执行耗时:</span>
                      <span className="value">{sq.latency}ms</span>
                    </div>
                  )}
                </div>

                {/* 如果已完成，显示示例结果 */}
                {sq.status === 'completed' && sq.resultCount && sq.resultCount > 0 && (
                  <div className="sample-results">
                    <div className="results-label">召回示例:</div>
                    <div className="result-chips">
                      <span className="result-chip">匹配段落 A</span>
                      <span className="result-chip">相关条目 B</span>
                      <span className="result-chip">实体关系 C</span>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* 统计汇总 */}
      <div className="decomposition-summary">
        <div className="summary-item">
          <span className="summary-label">总子查询:</span>
          <span className="summary-value">{subQueries.length}</span>
        </div>
        <div className="summary-item">
          <span className="summary-label">已完成:</span>
          <span className="summary-value">
            {subQueries.filter(sq => sq.status === 'completed').length}
          </span>
        </div>
        <div className="summary-item">
          <span className="summary-label">总召回:</span>
          <span className="summary-value">
            {subQueries.reduce((sum, sq) => sum + (sq.resultCount || 0), 0)} 条
          </span>
        </div>
        <div className="summary-item">
          <span className="summary-label">总耗时:</span>
          <span className="summary-value">
            {subQueries.reduce((sum, sq) => sum + (sq.latency || 0), 0)}ms
          </span>
        </div>
      </div>
    </div>
  );
};

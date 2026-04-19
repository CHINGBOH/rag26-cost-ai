/**
 * 内联引用展示组件
 * 在消息下方直接展示引用的资料，一目了然
 */

import { useState } from 'react';
import { ChatReference } from '@rag/shared';
import './Chat.css';

interface InlineReferencesProps {
  references: ChatReference[];
  onReferenceClick?: (ref: ChatReference) => void;
}

export const InlineReferences: React.FC<InlineReferencesProps> = ({
  references,
  onReferenceClick
}) => {
  const [expandedRef, setExpandedRef] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  if (!references || references.length === 0) return null;

  // 按相关度排序
  const sortedRefs = [...references].sort((a, b) => b.relevanceScore - a.relevanceScore);
  
  // 实际展示的引用
  const displayedRefs = showAll ? sortedRefs : sortedRefs.slice(0, 5);
  const hasMore = sortedRefs.length > 5;

  const getSourceIcon = (db: string) => {
    const icons: Record<string, string> = {
      vector: '📊',
      knowledge: '📚',
      graph: '🕸️',
      sql: '🗃️'
    };
    return icons[db] || '📄';
  };

  const getScoreColor = (score: number) => {
    if (score >= 0.8) return 'var(--color-success)';
    if (score >= 0.6) return 'var(--color-warning)';
    return 'var(--color-error)';
  };

  return (
    <div className="inline-references">
      <div className="references-header">
        <span className="header-icon">📚</span>
        <span className="header-title">参考来源</span>
        <span className="references-count">{references.length} 条</span>
        <span className="avg-relevance">
          平均相关度: {(references.reduce((s, r) => s + r.relevanceScore, 0) / references.length * 100).toFixed(0)}%
        </span>
      </div>

      <div className="references-grid">
        {displayedRefs.map((ref) => (
          <div
            key={ref.id}
            className={`reference-item ${expandedRef === ref.id ? 'expanded' : ''} ${ref.usedInAnswer ? 'used' : ''}`}
            onClick={() => {
              setExpandedRef(expandedRef === ref.id ? null : ref.id);
              onReferenceClick?.(ref);
            }}
          >
            {/* 引用编号 */}
            <div className="ref-index-badge">[{ref.index}]</div>

            {/* 内容预览 */}
            <div className="ref-content-preview">
              <div className="ref-source-row">
                <span className="ref-source-icon">{getSourceIcon(ref.chunk.database)}</span>
                <span className="ref-source-name" title={ref.chunk.source}>
                  {ref.chunk.source.split('/').pop()}
                </span>
                {ref.chunk.metadata.page && (
                  <span className="ref-page">p.{ref.chunk.metadata.page}</span>
                )}
              </div>
              
              <div className="ref-text-preview">
                {ref.chunk.content.slice(0, expandedRef === ref.id ? 500 : 100)}
                {ref.chunk.content.length > (expandedRef === ref.id ? 500 : 100) && '...'}
              </div>

              {/* 展开时显示完整信息 */}
              {expandedRef === ref.id && (
                <div className="ref-expanded-info">
                  <div className="ref-scores-detail">
                    <div className="score-item">
                      <span className="score-label">检索分数:</span>
                      <span className="score-value" style={{ color: getScoreColor(ref.chunk.score) }}>
                        {(ref.chunk.score * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="score-item">
                      <span className="score-label">精排分数:</span>
                      <span className="score-value" style={{ color: getScoreColor(ref.relevanceScore) }}>
                        {(ref.relevanceScore * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="score-item">
                      <span className="score-label">数据源:</span>
                      <span className="score-value">{ref.chunk.database}</span>
                    </div>
                  </div>
                  
                  <div className="ref-actions">
                    <button className="ref-action-btn">查看原文</button>
                    <button className="ref-action-btn">复制链接</button>
                  </div>
                </div>
              )}
            </div>

            {/* 相关度指示 */}
            <div className="ref-score-indicator">
              <div 
                className="score-ring"
                style={{ 
                  borderColor: getScoreColor(ref.relevanceScore),
                  background: `conic-gradient(${getScoreColor(ref.relevanceScore)} ${ref.relevanceScore * 360}deg, transparent 0)`
                }}
              >
                <span className="score-text">{(ref.relevanceScore * 100).toFixed(0)}</span>
              </div>
              {ref.usedInAnswer && <span className="used-badge">已引用</span>}
            </div>

            {/* 展开指示 */}
            <div className="expand-hint">
              {expandedRef === ref.id ? '▲' : '▼'}
            </div>
          </div>
        ))}
      </div>

      {/* 显示更多 */}
      {hasMore && (
        <button className="show-more-btn" onClick={() => setShowAll(!showAll)}>
          {showAll ? '收起' : `显示全部 ${sortedRefs.length} 条引用`}
        </button>
      )}

      {/* 数据源分布 */}
      <div className="source-distribution">
        <span className="dist-label">来源分布:</span>
        {['vector', 'knowledge', 'graph'].map(db => {
          const count = references.filter(r => r.chunk.database === db).length;
          if (count === 0) return null;
          return (
            <span key={db} className={`dist-badge ${db}`}>
              {getSourceIcon(db)} {count}
            </span>
          );
        })}
      </div>
    </div>
  );
};

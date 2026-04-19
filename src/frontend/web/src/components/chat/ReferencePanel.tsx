/**
 * 引用资料面板
 * 展示答案引用的所有文档来源
 */

import { useState } from 'react';
import { ChatReference } from '@rag/shared';
import './Chat.css';

interface ReferencePanelProps {
  references: ChatReference[];
  isExpanded: boolean;
  onToggle: () => void;
}

export const ReferencePanel: React.FC<ReferencePanelProps> = ({
  references,
  isExpanded,
  onToggle
}) => {
  const [selectedRef, setSelectedRef] = useState<ChatReference | null>(null);

  if (references.length === 0) return null;

  return (
    <div className={`reference-panel ${isExpanded ? 'expanded' : ''}`}>
      {/* 标题栏 */}
      <div className="reference-header" onClick={onToggle}>
        <div className="header-left">
          <span className="header-icon">📚</span>
          <span className="header-title">引用资料</span>
          <span className="reference-count">{references.length}</span>
        </div>
        <div className="header-right">
          <span className="avg-score">
            平均相关度: {(references.reduce((s, r) => s + r.relevanceScore, 0) / references.length * 100).toFixed(1)}%
          </span>
          <button className="toggle-btn">
            {isExpanded ? '▲' : '▼'}
          </button>
        </div>
      </div>

      {/* 展开内容 */}
      {isExpanded && (
        <div className="reference-content">
          <div className="reference-list">
            {references.map((ref) => (
              <ReferenceCard
                key={ref.id}
                reference={ref}
                isSelected={selectedRef?.id === ref.id}
                onClick={() => setSelectedRef(selectedRef?.id === ref.id ? null : ref)}
              />
            ))}
          </div>

          {selectedRef && (
            <ReferenceDetail reference={selectedRef} />
          )}
        </div>
      )}

      {/* 折叠时的引用标记 */}
      {!isExpanded && (
        <div className="reference-badges">
          {references.slice(0, 5).map((ref) => (
            <span 
              key={ref.id} 
              className="ref-badge"
              title={`${ref.chunk.source} - ${(ref.relevanceScore * 100).toFixed(0)}%`}
            >
              [{ref.index}]
            </span>
          ))}
          {references.length > 5 && (
            <span className="ref-badge more">+{references.length - 5}</span>
          )}
        </div>
      )}
    </div>
  );
};

// 引用卡片
const ReferenceCard: React.FC<{
  reference: ChatReference;
  isSelected: boolean;
  onClick: () => void;
}> = ({ reference, isSelected, onClick }) => {
  const { chunk, relevanceScore, usedInAnswer } = reference;
  const scorePercent = Math.round(relevanceScore * 100);
  
  const scoreColor = scorePercent >= 80 ? 'var(--color-success)' : 
                     scorePercent >= 60 ? 'var(--color-warning)' : 'var(--color-error)';

  return (
    <div 
      className={`reference-card ${isSelected ? 'selected' : ''} ${usedInAnswer ? 'used' : ''}`}
      onClick={onClick}
    >
      <div className="ref-index">[{reference.index}]</div>
      
      <div className="ref-content">
        <div className="ref-source">
          <span className="source-icon">📄</span>
          <span className="source-name" title={chunk.source}>
            {chunk.source.split('/').pop()}
          </span>
          {chunk.metadata.page && (
            <span className="source-page">p.{chunk.metadata.page}</span>
          )}
        </div>
        
        <div className="ref-preview">
          {chunk.content.slice(0, 80)}
          {chunk.content.length > 80 && '...'}
        </div>
        
        <div className="ref-meta">
          <span 
            className="ref-score"
            style={{ color: scoreColor }}
          >
            {scorePercent}% 相关度
          </span>
          <span className="ref-db">{chunk.database}</span>
          {usedInAnswer && <span className="ref-used">已引用</span>}
        </div>
      </div>
    </div>
  );
};

// 引用详情
const ReferenceDetail: React.FC<{ reference: ChatReference }> = ({ reference }) => {
  const { chunk } = reference;

  return (
    <div className="reference-detail">
      <h5>📄 文档详情</h5>
      
      <div className="detail-section">
        <div className="detail-row">
          <span className="detail-label">来源:</span>
          <span className="detail-value">{chunk.source}</span>
        </div>
        <div className="detail-row">
          <span className="detail-label">数据库:</span>
          <span className="detail-value db-badge">{chunk.database}</span>
        </div>
        {chunk.metadata.page && (
          <div className="detail-row">
            <span className="detail-label">页码:</span>
            <span className="detail-value">第 {chunk.metadata.page} 页</span>
          </div>
        )}
        {chunk.metadata.section && (
          <div className="detail-row">
            <span className="detail-label">章节:</span>
            <span className="detail-value">{chunk.metadata.section}</span>
          </div>
        )}
        <div className="detail-row">
          <span className="detail-label">原始相似度:</span>
          <span className="detail-value">{(chunk.score * 100).toFixed(1)}%</span>
        </div>
        <div className="detail-row">
          <span className="detail-label">重排分数:</span>
          <span className="detail-value">{(reference.relevanceScore * 100).toFixed(1)}%</span>
        </div>
      </div>

      <div className="detail-section">
        <div className="detail-label">完整内容:</div>
        <div className="full-content">{chunk.content}</div>
      </div>

      <div className="detail-actions">
        <button className="action-btn">在新窗口打开</button>
        <button className="action-btn">查看原文</button>
      </div>
    </div>
  );
};

// 内嵌引用标记（用于消息内容中）
interface InlineReferenceProps {
  index: number;
  reference?: ChatReference;
}

export const InlineReference: React.FC<InlineReferenceProps> = ({ 
  index,
  reference 
}) => {
  const [showTooltip, setShowTooltip] = useState(false);

  return (
    <span 
      className="inline-reference"
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <sup className="ref-link">[{index}]</sup>
      
      {showTooltip && reference && (
        <div className="ref-tooltip">
          <div className="tooltip-source">{reference.chunk.source}</div>
          <div className="tooltip-preview">
            {reference.chunk.content.slice(0, 100)}...
          </div>
          <div className="tooltip-score">
            相关度: {(reference.relevanceScore * 100).toFixed(0)}%
          </div>
        </div>
      )}
    </span>
  );
};

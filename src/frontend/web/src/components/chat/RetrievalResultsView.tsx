/**
 * 检索结果可视化组件
 * 展示从各数据库召回的文档及精排过程
 */

import { useState } from 'react';
import { RetrievedChunk } from '@rag/shared';
import './Chat.css';

interface RetrievalResultsViewProps {
  vectorResults?: RetrievedChunk[];
  knowledgeResults?: RetrievedChunk[];
  graphResults?: RetrievedChunk[];
  rerankedResults?: {
    chunk: RetrievedChunk;
    originalRank: number;
    rerankScore: number;
  }[];
  showRerankDetails?: boolean;
}

export const RetrievalResultsView: React.FC<RetrievalResultsViewProps> = ({
  vectorResults = [],
  knowledgeResults = [],
  graphResults = [],
  rerankedResults = [],
  showRerankDetails = true
}) => {
  const [activeSource, setActiveSource] = useState<'all' | 'vector' | 'knowledge' | 'graph'>('all');
  const [selectedChunk, setSelectedChunk] = useState<RetrievedChunk | null>(null);
  const [showRerankProcess, setShowRerankProcess] = useState(false);

  const allResults = [...vectorResults, ...knowledgeResults, ...graphResults];
  
  const getFilteredResults = () => {
    switch (activeSource) {
      case 'vector': return vectorResults;
      case 'knowledge': return knowledgeResults;
      case 'graph': return graphResults;
      default: return allResults;
    }
  };

  const getSourceIcon = (source: string) => {
    const icons: Record<string, string> = {
      vector: '📊',
      knowledge: '📚',
      graph: '🕸️'
    };
    return icons[source] || '📄';
  };

  const getSourceLabel = (source: string) => {
    const labels: Record<string, string> = {
      vector: '向量库',
      knowledge: '知识库',
      graph: '知识图谱'
    };
    return labels[source] || source;
  };

  return (
    <div className="retrieval-results-view">
      {/* 统计概览 */}
      <div className="retrieval-stats">
        <div className="stat-card">
          <span className="stat-icon">📊</span>
          <span className="stat-label">向量召回</span>
          <span className="stat-value">{vectorResults.length}</span>
        </div>
        <div className="stat-card">
          <span className="stat-icon">📚</span>
          <span className="stat-label">知识召回</span>
          <span className="stat-value">{knowledgeResults.length}</span>
        </div>
        <div className="stat-card">
          <span className="stat-icon">🕸️</span>
          <span className="stat-label">图谱召回</span>
          <span className="stat-value">{graphResults.length}</span>
        </div>
        <div className="stat-card highlight">
          <span className="stat-icon">⚖️</span>
          <span className="stat-label">精排后</span>
          <span className="stat-value">{rerankedResults.length}</span>
        </div>
      </div>

      {/* 精排过程可视化 */}
      {showRerankDetails && rerankedResults.length > 0 && (
        <div className="rerank-section">
          <div className="section-header">
            <span>⚖️ 精排过程</span>
            <button
              className="toggle-btn"
              onClick={() => setShowRerankProcess(!showRerankProcess)}
            >
              {showRerankProcess ? '收起' : '展开'}
            </button>
          </div>
          
          {showRerankProcess && (
            <div className="rerank-funnel">
              <div className="funnel-stage input">
                <div className="stage-label">粗排候选</div>
                <div className="stage-count">{allResults.length}</div>
              </div>
              <div className="funnel-arrow">→</div>
              <div className="funnel-stage process">
                <div className="stage-label">精排模型</div>
                <div className="stage-info">交叉编码器</div>
              </div>
              <div className="funnel-arrow">→</div>
              <div className="funnel-stage output">
                <div className="stage-label">精排结果</div>
                <div className="stage-count">{rerankedResults.length}</div>
              </div>
            </div>
          )}

          {/* 精排结果列表 */}
          <div className="reranked-list">
            {rerankedResults.slice(0, 5).map((item, index) => (
              <div
                key={item.chunk.id}
                className="reranked-item"
                onClick={() => setSelectedChunk(item.chunk)}
              >
                <div className="rank-badge">{index + 1}</div>
                <div className="rerank-info">
                  <div className="rerank-source">
                    {getSourceIcon(item.chunk.database)} {item.chunk.source}
                  </div>
                  <div className="rerank-preview">
                    {item.chunk.content.slice(0, 60)}...
                  </div>
                </div>
                <div className="rerank-scores">
                  <div className="score-row">
                    <span className="score-label">原始</span>
                    <span className="score-value">
                      {(item.chunk.score * 100).toFixed(1)}
                    </span>
                  </div>
                  <div className="score-row highlight">
                    <span className="score-label">精排</span>
                    <span className="score-value">
                      {(item.rerankScore * 100).toFixed(1)}
                    </span>
                  </div>
                </div>
                <div className="rank-change">
                  {item.originalRank > index + 1 ? (
                    <span className="rank-up">↑{item.originalRank - (index + 1)}</span>
                  ) : item.originalRank < index + 1 ? (
                    <span className="rank-down">↓{(index + 1) - item.originalRank}</span>
                  ) : (
                    <span className="rank-same">-</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 筛选标签 */}
      <div className="source-filter">
        <button
          className={`filter-btn ${activeSource === 'all' ? 'active' : ''}`}
          onClick={() => setActiveSource('all')}
        >
          全部 ({allResults.length})
        </button>
        <button
          className={`filter-btn ${activeSource === 'vector' ? 'active' : ''}`}
          onClick={() => setActiveSource('vector')}
        >
          📊 向量 ({vectorResults.length})
        </button>
        <button
          className={`filter-btn ${activeSource === 'knowledge' ? 'active' : ''}`}
          onClick={() => setActiveSource('knowledge')}
        >
          📚 知识 ({knowledgeResults.length})
        </button>
        <button
          className={`filter-btn ${activeSource === 'graph' ? 'active' : ''}`}
          onClick={() => setActiveSource('graph')}
        >
          🕸️ 图谱 ({graphResults.length})
        </button>
      </div>

      {/* 结果列表 */}
      <div className="results-list">
        {getFilteredResults().map((chunk) => (
          <div
            key={chunk.id}
            className={`result-item ${selectedChunk?.id === chunk.id ? 'selected' : ''}`}
            onClick={() => setSelectedChunk(chunk)}
          >
            <div className="result-header">
              <span className="result-source">
                {getSourceIcon(chunk.database)} {chunk.source}
              </span>
              <span className="result-score">
                {(chunk.score * 100).toFixed(1)}%
              </span>
            </div>
            <div className="result-content">
              {chunk.content.slice(0, 120)}
              {chunk.content.length > 120 && '...'}
            </div>
            <div className="result-meta">
              <span className="meta-db">{getSourceLabel(chunk.database)}</span>
              {chunk.metadata.page && (
                <span className="meta-page">p.{chunk.metadata.page}</span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* 选中详情 */}
      {selectedChunk && (
        <div className="chunk-detail">
          <div className="detail-header">
            <span>📄 文档详情</span>
            <button onClick={() => setSelectedChunk(null)}>×</button>
          </div>
          <div className="detail-content">
            <div className="detail-row">
              <span className="label">来源:</span>
              <span className="value">{selectedChunk.source}</span>
            </div>
            <div className="detail-row">
              <span className="label">相似度:</span>
              <span className="value">{(selectedChunk.score * 100).toFixed(2)}%</span>
            </div>
            <div className="detail-row">
              <span className="label">数据库:</span>
              <span className="value">{getSourceLabel(selectedChunk.database)}</span>
            </div>
            <div className="detail-fulltext">
              {selectedChunk.content}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

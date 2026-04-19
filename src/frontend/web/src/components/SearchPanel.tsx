import React, { useState } from 'react';
import { searchDocuments, SearchResult } from '../services/ragApi';

export const SearchPanel: React.FC = () => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [latency, setLatency] = useState(0);

  const handleSearch = async () => {
    if (!query.trim()) return;
    
    setLoading(true);
    try {
      const startTime = Date.now();
      const searchResults = await searchDocuments(query, { topK: 10 });
      setResults(searchResults);
      setLatency(Date.now() - startTime);
    } catch (error) {
      console.error('Search failed:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: '20px', maxWidth: '800px', margin: '0 auto' }}>
      <h2>🔍 文档检索</h2>
      
      <div style={{ display: 'flex', gap: '10px', marginBottom: '20px' }}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="输入搜索关键词..."
          style={{
            flex: 1,
            padding: '10px',
            fontSize: '16px',
            borderRadius: '4px',
            border: '1px solid #ccc'
          }}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
        />
        <button
          onClick={handleSearch}
          disabled={loading}
          style={{
            padding: '10px 20px',
            fontSize: '16px',
            backgroundColor: '#1890ff',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: loading ? 'not-allowed' : 'pointer'
          }}
        >
          {loading ? '搜索中...' : '搜索'}
        </button>
      </div>

      {latency > 0 && (
        <div style={{ marginBottom: '10px', color: '#666' }}>
          找到 {results.length} 个结果，耗时 {latency}ms
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {results.map((result, index) => (
          <div
            key={result.chunk_id}
            style={{
              padding: '15px',
              border: '1px solid #e8e8e8',
              borderRadius: '8px',
              backgroundColor: '#fafafa'
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
              <span style={{ fontWeight: 'bold', color: '#1890ff' }}>
                #{index + 1} 匹配度: {(result.score * 100).toFixed(2)}%
              </span>
              <span style={{ fontSize: '12px', color: '#999' }}>
                页码: {result.metadata?.page_number || 'N/A'}
              </span>
            </div>
            <div style={{ color: '#333', lineHeight: '1.6' }}>
              {result.content}
            </div>
            <div style={{ marginTop: '8px', fontSize: '12px', color: '#666' }}>
              文档: {result.doc_id} | 
              向量分: {(result.metadata?.vector_score || 0).toFixed(3)} | 
              关键词分: {(result.metadata?.keyword_score || 0).toFixed(3)}
            </div>
          </div>
        ))}
      </div>

      {results.length === 0 && !loading && query && (
        <div style={{ textAlign: 'center', color: '#999', padding: '40px' }}>
          未找到相关结果
        </div>
      )}
    </div>
  );
};

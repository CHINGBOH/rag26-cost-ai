/**
 * 文档检索页 — 在知识库中检索文档片段
 * 走 /api/v1/search
 */

import { useState } from 'react';
import { PageHeader } from '../components/common/PageHeader';
import './SearchPage.css';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

type SearchMode = 'hybrid' | 'vector' | 'keyword';

interface SearchResult {
  chunk_id: string;
  doc_id: string;
  content: string;
  score: number;
  metadata: Record<string, any>;
}

const MODES: { value: SearchMode; label: string }[] = [
  { value: 'hybrid', label: '混合' },
  { value: 'vector', label: '向量' },
  { value: 'keyword', label: '关键词' },
];

export const SearchPage: React.FC = () => {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<SearchMode>('hybrid');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [latency, setLatency] = useState(0);
  const [error, setError] = useState('');

  const handleSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError('');
    const start = Date.now();

    try {
      const res = await fetch(`${API_BASE}/api/v1/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query.trim(), top_k: 10, mode }),
      });

      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);

      const data = await res.json();
      const items = data.data?.results || data.results || [];
      setResults(items);
      setLatency(Date.now() - start);
    } catch (e: any) {
      setError(e.message || '检索失败');
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="search-page">
      <PageHeader title="文档检索" subtitle="在知识库中检索文档片段" />

      <div className="search-bar">
        <input
          className="search-input"
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder="输入检索关键词…"
        />
        <div className="mode-selector">
          {MODES.map((m) => (
            <button
              key={m.value}
              className={`mode-btn ${mode === m.value ? 'active' : ''}`}
              onClick={() => setMode(m.value)}
            >
              {m.label}
            </button>
          ))}
        </div>
        <button
          className="search-btn"
          onClick={handleSearch}
          disabled={loading || !query.trim()}
        >
          {loading ? '检索中…' : '检索'}
        </button>
      </div>

      {latency > 0 && !loading && (
        <div className="search-stats">
          找到 <strong>{results.length}</strong> 个结果 · 耗时 <strong>{latency}ms</strong>
        </div>
      )}

      {error && <div className="search-error">{error}</div>}

      <div className="results-list">
        {results.map((r, i) => (
          <div key={r.chunk_id || i} className="result-card">
            <div className="result-top">
              <span className="result-rank">#{i + 1}</span>
              <span className="result-score">{(r.score * 100).toFixed(1)}%</span>
            </div>
            <div className="result-body">{r.content}</div>
            <div className="result-footer">
              <span>{r.doc_id}</span>
              {r.metadata?.page_number && <span>p.{r.metadata.page_number}</span>}
            </div>
          </div>
        ))}
      </div>

      {results.length === 0 && !loading && query && !error && (
        <div className="empty-state">暂无匹配结果</div>
      )}
    </div>
  );
};

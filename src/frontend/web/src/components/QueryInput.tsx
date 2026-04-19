/**
 * 查询输入组件
 * 启动新的递归会话
 */

import { useState } from 'react';

interface QueryInputProps {
  onSubmit: (query: string) => void;
  disabled?: boolean;
}

export const QueryInput: React.FC<QueryInputProps> = ({ onSubmit, disabled }) => {
  const [query, setQuery] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim() && !disabled) {
      onSubmit(query.trim());
      setQuery('');
    }
  };

  return (
    <div className="query-input" style={{ padding: '1rem' }}>
      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '0.75rem' }}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="输入查询，启动递归检索..."
          disabled={disabled}
          style={{
            flex: 1,
            padding: '0.75rem 1rem',
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border-default)',
            borderRadius: '8px',
            color: 'var(--text-primary)',
            fontSize: '14px',
            outline: 'none'
          }}
        />
        <button 
          type="submit" 
          disabled={disabled || !query.trim()}
          style={{
            padding: '0.75rem 1.5rem',
            background: 'var(--color-primary)',
            border: 'none',
            borderRadius: '8px',
            color: 'var(--text-inverse)',
            fontSize: '14px',
            fontWeight: 500,
            cursor: disabled || !query.trim() ? 'not-allowed' : 'pointer',
            opacity: disabled || !query.trim() ? 0.5 : 1,
            transition: 'all 0.2s ease'
          }}
        >
          {disabled ? '处理中...' : '开始递归'}
        </button>
      </form>
    </div>
  );
};

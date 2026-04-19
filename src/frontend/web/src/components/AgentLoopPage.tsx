/**
 * Agent 多轮循环交互页面
 * 展示 Agent 的 Reasoning → Acting → Reflection 过程
 */

import { useState, useCallback } from 'react';
import { API_BASE } from '../services/llmApi';
import { authFetch } from '../utils/auth';

interface AgentIteration {
  iteration: number;
  type: 'reasoning' | 'acting' | 'reflection' | 'answer';
  content: string;
  timestamp: number;
  toolCalls?: Array<{
    id: string;
    name: string;
    args: any;
    result?: string;
  }>;
}

interface AgentState {
  status: 'idle' | 'running' | 'completed' | 'error';
  query: string;
  iterations: AgentIteration[];
  finalAnswer?: string;
  error?: string;
}

export const AgentLoopPage: React.FC = () => {
  const [query, setQuery] = useState('什么是 RAG (Retrieval-Augmented Generation)？');
  const [state, setState] = useState<AgentState>({
    status: 'idle',
    query: '',
    iterations: []
  });
  const [showJson, setShowJson] = useState(false);

  const addIteration = useCallback((iteration: AgentIteration) => {
    setState(prev => ({
      ...prev,
      iterations: [...prev.iterations, iteration]
    }));
  }, []);

  const runAgent = useCallback(async () => {
    if (!query.trim()) return;

    setState({
      status: 'running',
      query,
      iterations: []
    });

    try {
      const response = await authFetch(`${API_BASE}/api/agent/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, maxIterations: 3 })
      });

      if (!response.ok) {
        const error = await response.text();
        throw new Error(`Agent API 调用失败: ${response.status} - ${error}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error('无法读取响应流');
      }

      let finalAnswer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));

              if (data.type === 'final') {
                finalAnswer = data.result.answer;
                setState(prev => ({
                  ...prev,
                  status: 'completed',
                  finalAnswer
                }));
              } else if (data.type === 'error') {
                setState(prev => ({
                  ...prev,
                  status: 'error',
                  error: data.message
                }));
              } else {
                addIteration(data);
              }
            } catch {}
          }
        }
      }

    } catch (error) {
      setState(prev => ({
        ...prev,
        status: 'error',
        error: error instanceof Error ? error.message : '未知错误'
      }));
    }
  }, [query, addIteration]);

  const getTypeIcon = (type: string) => {
    const icons: Record<string, string> = {
      reasoning: '🧠',
      acting: '⚡',
      reflection: '🤔',
      answer: '✅'
    };
    return icons[type] || '📋';
  };

  const getTypeLabel = (type: string) => {
    const labels: Record<string, string> = {
      reasoning: 'Reasoning (推理)',
      acting: 'Acting (行动)',
      reflection: 'Reflection (反思)',
      answer: 'Answer (答案)'
    };
    return labels[type] || type;
  };

  const getTypeColor = (type: string) => {
    const colors: Record<string, string> = {
      reasoning: '#6366f1',
      acting: '#10b981',
      reflection: '#f59e0b',
      answer: '#8b5cf6'
    };
    return colors[type] || '#6b7280';
  };

  return (
    <div style={{
      padding: '24px',
      maxWidth: '1200px',
      margin: '0 auto',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    }}>
      {/* 标题 */}
      <div style={{ marginBottom: '24px' }}>
        <h1 style={{ 
          margin: '0 0 8px 0', 
          fontSize: '28px',
          fontWeight: '600'
        }}>
          🤖 Agent 多轮循环调试
        </h1>
        <p style={{ 
          margin: 0, 
          color: '#6b7280',
          fontSize: '14px'
        }}>
          观察 Agent 的 Reasoning → Acting → Reflection 过程
        </p>
      </div>

      {/* 输入区 */}
      <div style={{
        backgroundColor: '#f9fafb',
        border: '1px solid #e5e7eb',
        borderRadius: '12px',
        padding: '20px',
        marginBottom: '24px'
      }}>
        <div style={{ marginBottom: '12px' }}>
          <label style={{ 
            display: 'block', 
            marginBottom: '8px',
            fontWeight: '500',
            fontSize: '14px'
          }}>
            用户查询
          </label>
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="输入你的问题..."
            style={{
              width: '100%',
              padding: '12px',
              border: '1px solid #d1d5db',
              borderRadius: '8px',
              fontSize: '14px',
              minHeight: '80px',
              resize: 'vertical',
              fontFamily: 'inherit'
            }}
          />
        </div>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <button
            onClick={runAgent}
            disabled={state.status === 'running' || !query.trim()}
            style={{
              padding: '10px 24px',
              backgroundColor: state.status === 'running' ? '#9ca3af' : '#3b82f6',
              color: 'white',
              border: 'none',
              borderRadius: '8px',
              fontSize: '14px',
              fontWeight: '500',
              cursor: state.status === 'running' ? 'not-allowed' : 'pointer',
              transition: 'all 0.2s'
            }}
          >
            {state.status === 'running' ? '运行中...' : '🚀 运行 Agent'}
          </button>
          <div style={{ 
            display: 'flex', 
            alignItems: 'center', 
            gap: '8px',
            marginLeft: 'auto'
          }}>
            <label style={{ 
              display: 'flex', 
              alignItems: 'center', 
              gap: '6px',
              fontSize: '13px',
              cursor: 'pointer'
            }}>
              <input
                type="checkbox"
                checked={showJson}
                onChange={(e) => setShowJson(e.target.checked)}
              />
              显示 JSON 详情
            </label>
          </div>
        </div>
      </div>

      {/* 状态显示 */}
      {state.status !== 'idle' && (
        <div style={{
          backgroundColor: state.status === 'error' ? '#fef2f2' : 
                        state.status === 'completed' ? '#f0fdf4' : '#eff6ff',
          border: `1px solid ${state.status === 'error' ? '#fecaca' : 
                              state.status === 'completed' ? '#a7f3d0' : '#bfdbfe'}`,
          borderRadius: '12px',
          padding: '16px 20px',
          marginBottom: '24px',
          display: 'flex',
          alignItems: 'center',
          gap: '12px'
        }}>
          <span style={{ fontSize: '20px' }}>
            {state.status === 'running' && '⏳'}
            {state.status === 'completed' && '✅'}
            {state.status === 'error' && '❌'}
          </span>
          <div>
            <div style={{ fontWeight: '500', fontSize: '14px' }}>
              {state.status === 'running' && 'Agent 运行中...'}
              {state.status === 'completed' && 'Agent 运行完成！'}
              {state.status === 'error' && 'Agent 运行出错'}
            </div>
            {state.error && (
              <div style={{ fontSize: '13px', color: '#dc2626', marginTop: '4px' }}>
                {state.error}
              </div>
            )}
          </div>
          {state.iterations.length > 0 && (
            <div style={{ marginLeft: 'auto', fontSize: '13px', color: '#6b7280' }}>
              迭代次数: {Math.max(...state.iterations.map(i => i.iteration))}
            </div>
          )}
        </div>
      )}

      {/* 迭代过程 */}
      {state.iterations.length > 0 && (
        <div>
          <h2 style={{ 
            margin: '0 0 16px 0', 
            fontSize: '18px',
            fontWeight: '600'
          }}>
            🔄 迭代过程
          </h2>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {state.iterations.map((iteration, index) => (
              <div
                key={index}
                style={{
                  backgroundColor: 'white',
                  border: '1px solid #e5e7eb',
                  borderRadius: '12px',
                  padding: '16px',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.05)'
                }}
              >
                {/* 头部 */}
                <div style={{ 
                  display: 'flex', 
                  alignItems: 'center', 
                  gap: '12px',
                  marginBottom: '12px'
                }}>
                  <div style={{
                    backgroundColor: getTypeColor(iteration.type),
                    color: 'white',
                    width: '28px',
                    height: '28px',
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '14px',
                    fontWeight: '600'
                  }}>
                    {getTypeIcon(iteration.type)}
                  </div>
                  <div>
                    <div style={{ 
                      fontWeight: '600', 
                      fontSize: '14px',
                      color: getTypeColor(iteration.type)
                    }}>
                      {getTypeLabel(iteration.type)}
                    </div>
                    <div style={{ 
                      fontSize: '12px', 
                      color: '#9ca3af' 
                    }}>
                      迭代 {iteration.iteration} · {new Date(iteration.timestamp).toLocaleTimeString()}
                    </div>
                  </div>
                </div>

                {/* 内容 */}
                <div style={{ 
                  fontSize: '14px',
                  lineHeight: '1.6',
                  color: '#374151',
                  whiteSpace: 'pre-wrap'
                }}>
                  {iteration.content}
                </div>

                {/* 工具调用 */}
                {iteration.toolCalls && iteration.toolCalls.length > 0 && (
                  <div style={{ marginTop: '12px' }}>
                    <div style={{ 
                      fontSize: '12px', 
                      fontWeight: '500', 
                      color: '#6b7280',
                      marginBottom: '8px'
                    }}>
                      🛠️ 工具调用
                    </div>
                    {iteration.toolCalls.map((toolCall, tcIndex) => (
                      <div
                        key={tcIndex}
                        style={{
                          backgroundColor: '#f3f4f6',
                          border: '1px solid #e5e7eb',
                          borderRadius: '8px',
                          padding: '12px',
                          marginBottom: tcIndex < iteration.toolCalls!.length - 1 ? '8px' : 0
                        }}
                      >
                        <div style={{ 
                          display: 'flex', 
                          alignItems: 'center', 
                          gap: '8px',
                          marginBottom: '8px'
                        }}>
                          <span style={{ 
                            fontWeight: '600', 
                            fontSize: '13px',
                            color: '#059669'
                          }}>
                            {toolCall.name}
                          </span>
                          <span style={{ 
                            fontSize: '11px', 
                            color: '#9ca3af',
                            fontFamily: 'monospace'
                          }}>
                            {toolCall.id}
                          </span>
                        </div>
                        
                        <div style={{ fontSize: '12px' }}>
                          <div style={{ 
                            marginBottom: '8px',
                            color: '#6b7280'
                          }}>
                            <strong>参数:</strong>
                            <pre style={{
                              margin: '4px 0 0 0',
                              padding: '8px',
                              backgroundColor: 'white',
                              border: '1px solid #e5e7eb',
                              borderRadius: '4px',
                              fontSize: '11px',
                              overflow: 'auto'
                            }}>
                              {JSON.stringify(toolCall.args, null, 2)}
                            </pre>
                          </div>
                          
                          {toolCall.result && (
                            <div style={{ color: '#059669' }}>
                              <strong>结果:</strong>
                              {showJson ? (
                                <pre style={{
                                  margin: '4px 0 0 0',
                                  padding: '8px',
                                  backgroundColor: '#f0fdf4',
                                  border: '1px solid #a7f3d0',
                                  borderRadius: '4px',
                                  fontSize: '11px',
                                  overflow: 'auto'
                                }}>
                                  {toolCall.result}
                                </pre>
                              ) : (
                                <div style={{
                                  marginTop: '4px',
                                  padding: '8px',
                                  backgroundColor: '#f0fdf4',
                                  border: '1px solid #a7f3d0',
                                  borderRadius: '4px'
                                }}>
                                  结果已获取 (点击"显示 JSON 详情"查看完整内容)
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 最终答案 */}
      {state.finalAnswer && (
        <div style={{ marginTop: '32px' }}>
          <h2 style={{ 
            margin: '0 0 16px 0', 
            fontSize: '18px',
            fontWeight: '600'
          }}>
            📝 最终答案
          </h2>
          <div style={{
            backgroundColor: '#faf5ff',
            border: '1px solid #e9d5ff',
            borderRadius: '12px',
            padding: '24px'
          }}>
            <div style={{
              fontSize: '15px',
              lineHeight: '1.7',
              color: '#1f2937',
              whiteSpace: 'pre-wrap'
            }}>
              {state.finalAnswer}
            </div>
          </div>
        </div>
      )}

    </div>
  );
};

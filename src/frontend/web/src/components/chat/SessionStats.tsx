/**
 * 会话统计面板
 * 展示当前会话的统计信息
 */

import { useMemo } from 'react';
import { ChatSession } from '@rag/shared';
import { chatFlowConfig } from '../../config';
import './Chat.css';

const TOOLTIPS = chatFlowConfig.ui.tooltips;

interface SessionStatsProps {
  session: ChatSession | null;
  onExport?: () => void;
  onClear?: () => void;
}

export const SessionStats: React.FC<SessionStatsProps> = ({
  session,
  onExport,
  onClear
}) => {
  const stats = useMemo(() => {
    if (!session) return null;

    const messages = Array.from(session.messages.values());
    const userMessages = messages.filter(m => m.role === 'user');
    const assistantMessages = messages.filter(m => m.role === 'assistant');
    
    const totalTokens = messages.reduce((sum, m) => sum + (m.tokenCount || 0), 0);
    const totalLatency = assistantMessages.reduce((sum, m) => sum + (m.latency || 0), 0);
    const avgLatency = assistantMessages.length > 0 ? totalLatency / assistantMessages.length : 0;

    // RAG 统计
    const ragMessages = assistantMessages.filter(m => m.ragProcess && m.ragProcess.length > 0);
    const totalRetrievalCount = assistantMessages.reduce((sum, m) => {
      const refs = m.references?.length || 0;
      return sum + refs;
    }, 0);

    // 代码执行统计
    const codeExecutions = assistantMessages.filter(m => m.codeExecution).length;

    return {
      messageCount: messages.length,
      userMessageCount: userMessages.length,
      assistantMessageCount: assistantMessages.length,
      totalTokens,
      avgLatency,
      ragMessageCount: ragMessages.length,
      totalRetrievalCount,
      codeExecutions,
      duration: session.updatedAt - session.createdAt
    };
  }, [session]);

  if (!stats) return null;

  const formatDuration = (ms: number) => {
    const minutes = Math.floor(ms / 60000);
    const seconds = Math.floor((ms % 60000) / 1000);
    return minutes > 0 ? `${minutes}分${seconds}秒` : `${seconds}秒`;
  };

  return (
    <div className="session-stats-panel">
      <div className="stats-header">
        <span className="stats-title">📊 会话统计</span>
        <div className="stats-actions">
          {onExport && (
            <button className="stat-action-btn" onClick={onExport} title={TOOLTIPS.exportSession}>
              💾
            </button>
          )}
          {onClear && (
            <button className="stat-action-btn danger" onClick={onClear} title={TOOLTIPS.clearSession}>
              🗑️
            </button>
          )}
        </div>
      </div>

      <div className="stats-grid">
        <div className="stat-card primary">
          <span className="stat-icon">💬</span>
          <span className="stat-value">{stats.messageCount}</span>
          <span className="stat-label">总消息</span>
        </div>
        <div className="stat-card">
          <span className="stat-icon">👤</span>
          <span className="stat-value">{stats.userMessageCount}</span>
          <span className="stat-label">用户</span>
        </div>
        <div className="stat-card">
          <span className="stat-icon">🤖</span>
          <span className="stat-value">{stats.assistantMessageCount}</span>
          <span className="stat-label">AI</span>
        </div>
        <div className="stat-card">
          <span className="stat-icon">🪙</span>
          <span className="stat-value">{stats.totalTokens.toLocaleString()}</span>
          <span className="stat-label">Token</span>
        </div>
      </div>

      <div className="stats-details">
        <div className="detail-row">
          <span className="detail-icon">⏱️</span>
          <span className="detail-label">平均响应时间</span>
          <span className="detail-value">{stats.avgLatency.toFixed(0)}ms</span>
        </div>
        <div className="detail-row">
          <span className="detail-icon">🔍</span>
          <span className="detail-label">RAG检索次数</span>
          <span className="detail-value">{stats.ragMessageCount}</span>
        </div>
        <div className="detail-row">
          <span className="detail-icon">📚</span>
          <span className="detail-label">引用资料总数</span>
          <span className="detail-value">{stats.totalRetrievalCount}</span>
        </div>
        {stats.codeExecutions > 0 && (
          <div className="detail-row">
            <span className="detail-icon">🧮</span>
            <span className="detail-label">代码执行</span>
            <span className="detail-value">{stats.codeExecutions} 次</span>
          </div>
        )}
        <div className="detail-row">
          <span className="detail-icon">🕐</span>
          <span className="detail-label">会话时长</span>
          <span className="detail-value">{formatDuration(stats.duration)}</span>
        </div>
      </div>

      {/* Token 使用趋势（简化版） */}
      {stats.totalTokens > 0 && (
        <div className="token-trend">
          <div className="trend-header">
            <span>Token 使用</span>
            <span className="trend-value">{stats.totalTokens.toLocaleString()}</span>
          </div>
          <div className="trend-bar">
            <div 
              className="trend-fill"
              style={{ width: `${Math.min((stats.totalTokens / 8192) * 100, 100)}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
};

// 会话导出功能
export function exportSession(session: ChatSession): string {
  const exportData = {
    id: session.id,
    title: session.title,
    createdAt: new Date(session.createdAt).toISOString(),
    updatedAt: new Date(session.updatedAt).toISOString(),
    config: session.config,
    messages: Array.from(session.messages.values()).map(m => ({
      role: m.role,
      content: m.content,
      timestamp: new Date(m.timestamp).toISOString(),
      model: m.model,
      tokenCount: m.tokenCount,
      latency: m.latency,
      references: m.references?.map(r => ({
        index: r.index,
        source: r.chunk.source,
        relevanceScore: r.relevanceScore,
        usedInAnswer: r.usedInAnswer
      })),
      codeExecution: m.codeExecution
    }))
  };

  return JSON.stringify(exportData, null, 2);
}

// 下载会话
export function downloadSession(session: ChatSession) {
  const content = exportSession(session);
  const blob = new Blob([content], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `session-${session.id.slice(0, 8)}-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

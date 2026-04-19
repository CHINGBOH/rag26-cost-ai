/**
 * Token 使用量可视化条
 * 展示输入/输出 Token 消耗和成本估算
 */

import { useMemo } from 'react';
import { llmProviders, activeProvider } from '../../config';
import './Chat.css';

interface TokenUsageBarProps {
  inputTokens: number;
  outputTokens: number;
  contextWindow?: number;
  model?: string;
}

// 从配置获取模型定价
const getModelPricing = (model?: string) => {
  // 尝试找到匹配的 provider
  for (const [, provider] of Object.entries(llmProviders)) {
    if (provider.defaultModel === model || provider.models.some(m => m.id === model)) {
      return provider.pricing;
    }
  }
  
  // 回退到当前激活 provider 的定价
  const currentProvider = llmProviders[activeProvider as keyof typeof llmProviders];
  return currentProvider?.pricing || { input: 0.003, output: 0.006, currency: '¥' };
};

export const TokenUsageBar: React.FC<TokenUsageBarProps> = ({
  inputTokens,
  outputTokens,
  contextWindow = 8192,
  model = 'default'
}) => {
  const totalTokens = inputTokens + outputTokens;
  const usagePercent = Math.min((totalTokens / contextWindow) * 100, 100);
  
  const pricing = getModelPricing(model);
  const cost = useMemo(() => {
    const inputCost = (inputTokens / 1000) * pricing.input;
    const outputCost = (outputTokens / 1000) * pricing.output;
    return {
      input: inputCost.toFixed(4),
      output: outputCost.toFixed(4),
      total: (inputCost + outputCost).toFixed(4)
    };
  }, [inputTokens, outputTokens, pricing]);

  const getUsageColor = () => {
    if (usagePercent < 50) return 'var(--color-success)';
    if (usagePercent < 80) return 'var(--color-warning)';
    return 'var(--color-error)';
  };

  return (
    <div className="token-usage-bar">
      <div className="usage-header">
        <div className="usage-stats">
          <span className="stat-item">
            <span className="stat-label">输入</span>
            <span className="stat-value input">{inputTokens.toLocaleString()}</span>
          </span>
          <span className="stat-separator">+</span>
          <span className="stat-item">
            <span className="stat-label">输出</span>
            <span className="stat-value output">{outputTokens.toLocaleString()}</span>
          </span>
          <span className="stat-separator">=</span>
          <span className="stat-item total">
            <span className="stat-label">总计</span>
            <span className="stat-value">{totalTokens.toLocaleString()}</span>
          </span>
        </div>
        <div className="cost-estimate">
          <span className="cost-label">预估成本</span>
          <span className="cost-value">
            {pricing.currency}{cost.total}
          </span>
        </div>
      </div>

      <div className="usage-visualization">
        <div className="usage-track">
          <div 
            className="usage-fill input-fill"
            style={{ 
              width: `${(inputTokens / contextWindow) * 100}%`,
              background: 'var(--color-primary)'
            }}
            title={`输入: ${inputTokens} tokens`}
          />
          <div 
            className="usage-fill output-fill"
            style={{ 
              width: `${(outputTokens / contextWindow) * 100}%`,
              left: `${(inputTokens / contextWindow) * 100}%`,
              background: 'var(--color-success)'
            }}
            title={`输出: ${outputTokens} tokens`}
          />
        </div>
        <div className="usage-percentage" style={{ color: getUsageColor() }}>
          {usagePercent.toFixed(1)}%
        </div>
      </div>

      <div className="usage-context-info">
        <span>上下文窗口: {contextWindow.toLocaleString()} tokens</span>
        <span className="remaining">
          剩余: {(contextWindow - totalTokens).toLocaleString()} tokens
        </span>
      </div>

      {/* 详细成本分解 */}
      <div className="cost-breakdown">
        <div className="cost-item">
          <span className="cost-dot" style={{ background: 'var(--color-primary)' }} />
          <span className="cost-label">输入:</span>
          <span className="cost-value">{pricing.currency}{cost.input}</span>
        </div>
        <div className="cost-item">
          <span className="cost-dot" style={{ background: 'var(--color-success)' }} />
          <span className="cost-label">输出:</span>
          <span className="cost-value">{pricing.currency}{cost.output}</span>
        </div>
      </div>
    </div>
  );
};

// 简化的 Token 指示器（用于消息内嵌）
export const TokenBadge: React.FC<{
  tokens: number;
  type?: 'input' | 'output';
}> = ({ tokens, type = 'output' }) => {
  return (
    <span className={`token-badge-inline ${type}`}>
      <span className="token-icon">🪙</span>
      <span className="token-count">{tokens}</span>
    </span>
  );
};

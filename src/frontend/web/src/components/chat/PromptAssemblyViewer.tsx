/**
 * Prompt 组装可视化组件
 * 展示系统提示、上下文、查询如何组装成最终 Prompt
 */

import { useState } from 'react';
import { PromptAssembly } from '@rag/shared';
import './Chat.css';

interface PromptAssemblyViewerProps {
  assembly: PromptAssembly;
  tokenCount?: number;
  contextLength?: number;
}

export const PromptAssemblyViewer: React.FC<PromptAssemblyViewerProps> = ({
  assembly,
  tokenCount,
  contextLength
}) => {
  const [activeTab, setActiveTab] = useState<'full' | 'system' | 'context' | 'query'>('full');
  const [showTokenized, setShowTokenized] = useState(false);

  // 计算各部分占比
  const systemTokens = estimateTokens(assembly.systemPrompt);
  const contextTokens = estimateTokens(assembly.contextPrompt);
  const queryTokens = estimateTokens(assembly.queryPrompt);
  const instructionTokens = estimateTokens(assembly.instructionPrompt);
  const totalTokens = tokenCount || (systemTokens + contextTokens + queryTokens + instructionTokens);

  const sections = [
    { key: 'system', label: '系统提示', content: assembly.systemPrompt, tokens: systemTokens, color: 'var(--color-success)' },
    { key: 'context', label: '上下文', content: assembly.contextPrompt, tokens: contextTokens, color: 'var(--color-primary)' },
    { key: 'query', label: '查询', content: assembly.queryPrompt, tokens: queryTokens, color: 'var(--color-warning)' },
    { key: 'instruction', label: '指令', content: assembly.instructionPrompt, tokens: instructionTokens, color: '#7c3aed' }
  ];

  const getFullPrompt = () => {
    return `${assembly.systemPrompt}\n\n${assembly.contextPrompt}\n\n${assembly.queryPrompt}\n\n${assembly.instructionPrompt}`;
  };

  return (
    <div className="prompt-assembly-viewer">
      {/* Token 统计条 */}
      <div className="token-visualization">
        <div className="token-bar">
          {sections.map((section) => (
            <div
              key={section.key}
              className="token-segment"
              style={{
                width: `${(section.tokens / totalTokens) * 100}%`,
                background: section.color
              }}
              title={`${section.label}: ${section.tokens} tokens`}
            />
          ))}
        </div>
        <div className="token-legend">
          {sections.map((section) => (
            <div key={section.key} className="legend-item">
              <span className="legend-color" style={{ background: section.color }} />
              <span className="legend-label">{section.label}</span>
              <span className="legend-value">{section.tokens}</span>
            </div>
          ))}
        </div>
        <div className="token-total">
          总 Token: <strong>{totalTokens}</strong>
          {contextLength && (
            <span className="context-info"> / 上下文长度: {contextLength}</span>
          )}
        </div>
      </div>

      {/* 标签切换 */}
      <div className="assembly-tabs">
        <button
          className={`assembly-tab ${activeTab === 'full' ? 'active' : ''}`}
          onClick={() => setActiveTab('full')}
        >
          完整 Prompt
        </button>
        {sections.map((section) => (
          <button
            key={section.key}
            className={`assembly-tab ${activeTab === section.key ? 'active' : ''}`}
            style={{ '--tab-color': section.color } as React.CSSProperties}
            onClick={() => setActiveTab(section.key as any)}
          >
            {section.label}
          </button>
        ))}
      </div>

      {/* 内容区域 */}
      <div className="assembly-content">
        <div className="content-header">
          <label className="tokenize-toggle">
            <input
              type="checkbox"
              className="tokenize-checkbox"
              checked={showTokenized}
              onChange={(e) => setShowTokenized(e.target.checked)}
            />
            显示 Token 边界
          </label>
        </div>

        {activeTab === 'full' ? (
          <div className="prompt-section">
            <div className="section-header">
              <span className="section-tag" style={{ background: 'var(--text-muted)' }}>
                完整 Prompt
              </span>
            </div>
            <pre className={`prompt-text ${showTokenized ? 'tokenized' : ''}`}>
              {formatPrompt(getFullPrompt(), showTokenized)}
            </pre>
          </div>
        ) : (
          sections
            .filter(s => s.key === activeTab)
            .map((section) => (
              <div key={section.key} className="prompt-section">
                <div className="section-header">
                  <span className="section-tag" style={{ background: section.color }}>
                    {section.label}
                  </span>
                  <span className="section-tokens">{section.tokens} tokens</span>
                </div>
                <pre className={`prompt-text ${showTokenized ? 'tokenized' : ''}`}>
                  {formatPrompt(section.content, showTokenized)}
                </pre>
              </div>
            ))
        )}
      </div>

      {/* Prompt 技巧提示 */}
      <div className="prompt-tips">
        <div className="tips-header">💡 Prompt 组装策略</div>
        <ul className="tips-list">
          <li>系统提示定义了 AI 的角色和行为准则</li>
          <li>上下文提供了检索到的相关知识</li>
          <li>查询是用户的原始问题</li>
          <li>指令指导 AI 如何组织答案</li>
        </ul>
      </div>
    </div>
  );
};

// 估算 token 数（简单估算：英文 1 word ≈ 1.3 tokens，中文 1 字 ≈ 2 tokens）
function estimateTokens(text: string): number {
  const chineseChars = (text.match(/[\u4e00-\u9fa5]/g) || []).length;
  const englishWords = text.split(/\s+/).filter(w => /[a-zA-Z]/.test(w)).length;
  const otherChars = text.length - chineseChars - englishWords;
  return Math.ceil(chineseChars * 2 + englishWords * 1.3 + otherChars * 0.5);
}

// 格式化 Prompt 显示
function formatPrompt(text: string, showTokenized: boolean): string {
  if (!showTokenized) return text;
  
  // 简单的 token 可视化：每 10 个字符加一个分隔
  return text.split('').map((char, i) => {
    if (i > 0 && i % 10 === 0) {
      return `|${char}`;
    }
    return char;
  }).join('');
}

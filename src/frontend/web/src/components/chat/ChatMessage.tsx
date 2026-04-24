/**
 * 聊天消息组件
 * 支持 Markdown、代码块、引用标记、RAG流程展示
 */

import { useMemo } from 'react';
import {
  ChatMessage as ChatMessageType,
  ChatReference
} from '@rag/shared';
import { ExecutableCodeBlock, detectCodeBlocks } from './CodeExecutor';
import { InlineReference } from './ReferencePanel';
import { StatusBadge } from '../charts';
import { uiConfig } from '../../config';
import AgentThoughtChain from './AgentThoughtChain';
import './Chat.css';

interface ChatMessageProps {
  message: ChatMessageType;
  references?: ChatReference[];
  isStreaming?: boolean;
  onReferenceClick?: (index: number) => void;
}

export const ChatMessage: React.FC<ChatMessageProps> = ({
  message,
  references = [],
  isStreaming
}) => {
  const isUser = message.role === 'user';
  
  // 解析内容，提取代码块和引用标记
  const contentParts = useMemo(() => {
    const parts: Array<{
      type: 'text' | 'code' | 'reference';
      content: string;
      language?: string;
      refIndex?: number;
    }> = [];
    
    let remaining = message.content;
    
    // 检测代码块
    const codeBlocks = detectCodeBlocks(message.content);
    
    if (codeBlocks.length === 0 && references.length === 0) {
      // 没有特殊内容，直接返回文本
      return [{ type: 'text' as const, content: message.content }];
    }
    
    // 简单的解析：先处理代码块
    let lastIndex = 0;
    codeBlocks.forEach((block) => {
      // 代码块前的文本
      if (block.index > lastIndex) {
        const textBefore = remaining.slice(lastIndex, block.index);
        // 处理文本中的引用标记
        parts.push(...parseReferencesInText(textBefore, references));
      }
      
      // 代码块
      parts.push({
        type: 'code',
        content: block.code,
        language: block.language
      });
      
      // Full match length: 3(```) + lang.length + 1(\n) + match[2].length + 3(```)
      // block.code is match[2].trim(), match[2] usually has a trailing \n → +1
      // So: 3 + lang.length + 1 + (code.length + 1) + 3 = code.length + lang.length + 8
      lastIndex = block.index + block.code.length + 8 + (block.language?.length || 0);
    });
    
    // 剩余文本
    if (lastIndex < remaining.length) {
      const textAfter = remaining.slice(lastIndex);
      parts.push(...parseReferencesInText(textAfter, references));
    }
    
    return parts.length > 0 ? parts : [{ type: 'text' as const, content: message.content }];
  }, [message.content, references]);

  return (
    <div className={`chat-message ${message.role} ${isStreaming ? 'streaming' : ''}`}>
      {/* 头像和角色 */}
      <div className="message-avatar">
        {isUser ? '👤' : message.model ? '🤖' : '🔄'}
      </div>
      
      <div className="message-content-wrapper">
        {/* 头部信息 */}
        <div className="message-header">
          <span className="message-role">
            {isUser ? '用户' : message.model || 'AI'}
          </span>
          <span className="message-time">
            {new Date(message.timestamp).toLocaleTimeString()}
          </span>
          {message.latency && (
            <span className="message-latency">{message.latency}ms</span>
          )}
          {message.tokenCount && (
            <span className="message-tokens">{message.tokenCount} tokens</span>
          )}
        </div>

        {/* Agent 思考链 — 显示在回答内容上方 */}
        {!isUser && message.ragProcess && message.ragProcess.length > 0 && (
          <AgentThoughtChain steps={message.ragProcess} isStreaming={isStreaming} />
        )}

        {/* 消息内容 */}
        <div className="message-body">
          {contentParts.map((part, index) => {
            switch (part.type) {
              case 'code':
                return (
                  <ExecutableCodeBlock
                    key={index}
                    code={part.content}
                    language={part.language || 'text'}
                    autoRun={!isUser && (part.language === 'python' || part.language === 'py')}
                  />
                );
              
              case 'reference':
                const ref = references.find(r => r.index === part.refIndex);
                return (
                  <InlineReference
                    key={index}
                    index={part.refIndex!}
                    reference={ref}
                  />
                );
              
              default:
                return (
                  <MarkdownText key={index} content={part.content} />
                );
            }
          })}
          
          {/* 流式指示器 */}
          {isStreaming && <span className="streaming-cursor">▊</span>}
        </div>

        {/* 代码执行结果 */}
        {message.codeExecution && (
          <div className="message-code-result">
            <div className={`code-result-badge ${message.codeExecution.status}`}>
              {message.codeExecution.status === 'success' ? '✓' : '✗'} 
              代码执行{message.codeExecution.status === 'success' ? '成功' : '失败'}
              <span className="exec-time">({message.codeExecution.executionTime}ms)</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

// 解析文本中的引用标记 [1], [2] 等
function parseReferencesInText(
  text: string, 
  references: ChatReference[]
): Array<{ type: 'text' | 'reference'; content: string; refIndex?: number }> {
  const parts: Array<{ type: 'text' | 'reference'; content: string; refIndex?: number }> = [];
  const regex = new RegExp(uiConfig.reference.pattern, 'g');
  let lastIndex = 0;
  let match;
  
  while ((match = regex.exec(text)) !== null) {
    // 引用前的文本
    if (match.index > lastIndex) {
      parts.push({
        type: 'text',
        content: text.slice(lastIndex, match.index)
      });
    }
    
    // 引用标记
    const refIndex = parseInt(match[1], 10);
    if (references.some(r => r.index === refIndex)) {
      parts.push({
        type: 'reference',
        content: match[0],
        refIndex
      });
    } else {
      parts.push({
        type: 'text',
        content: match[0]
      });
    }
    
    lastIndex = match.index + match[0].length;
  }
  
  // 剩余文本
  if (lastIndex < text.length) {
    parts.push({
      type: 'text',
      content: text.slice(lastIndex)
    });
  }
  
  return parts.length > 0 ? parts : [{ type: 'text', content: text }];
}

// Markdown 文本渲染（支持粗体、斜体、行内代码、表格、换行）
const MarkdownText: React.FC<{ content: string }> = ({ content }) => {
  const parts = useMemo(() => renderMarkdown(content), [content]);
  // Must be <div>, not <span>: renderMarkdown returns block elements (h2, table, ul)
  // which are invalid inside an inline <span> and break browser layout.
  return <div className="markdown-text">{parts}</div>;
};

function renderMarkdown(content: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const lines = content.split('\n');
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Headings: ## and ###
    const h3Match = line.match(/^### (.+)/);
    const h2Match = line.match(/^## (.+)/);
    const h1Match = line.match(/^# (.+)/);
    if (h3Match) { nodes.push(<h3 key={i} className="md-h3">{inlineMarkdown(h3Match[1])}</h3>); i++; continue; }
    if (h2Match) { nodes.push(<h2 key={i} className="md-h2">{inlineMarkdown(h2Match[1])}</h2>); i++; continue; }
    if (h1Match) { nodes.push(<h1 key={i} className="md-h1">{inlineMarkdown(h1Match[1])}</h1>); i++; continue; }

    // Markdown 表格检测：连续行以 | 开头，第二行含 ---
    if (line.startsWith('|') && lines[i + 1]?.includes('---')) {
      const tableLines: string[] = [];
      while (i < lines.length && lines[i].startsWith('|')) {
        tableLines.push(lines[i]);
        i++;
      }
      const headers = tableLines[0].split('|').map(s => s.trim()).filter(Boolean);
      const rows = tableLines.slice(2).map(l => l.split('|').map(s => s.trim()).filter(Boolean));
      nodes.push(
        <table key={`tbl-${i}`} className="markdown-table">
          <thead>
            <tr>{headers.map((h, j) => <th key={j}>{inlineMarkdown(h)}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} className={ri % 2 === 0 ? 'even' : 'odd'}>
                {row.map((cell, ci) => <td key={ci}>{inlineMarkdown(cell)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      );
      continue;
    }

    // Unordered list: lines starting with "- " or "* "
    if (/^[-*] /.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*] /.test(lines[i])) {
        items.push(lines[i].replace(/^[-*] /, ''));
        i++;
      }
      nodes.push(<ul key={`ul-${i}`} className="md-ul">{items.map((it, j) => <li key={j}>{inlineMarkdown(it)}</li>)}</ul>);
      continue;
    }

    // Ordered list: lines starting with "1. " "2. " etc.
    if (/^\d+\. /.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\. /.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\. /, ''));
        i++;
      }
      nodes.push(<ol key={`ol-${i}`} className="md-ol">{items.map((it, j) => <li key={j}>{inlineMarkdown(it)}</li>)}</ol>);
      continue;
    }

    // Horizontal rule
    if (/^---+$/.test(line.trim())) {
      nodes.push(<hr key={i} className="md-hr" />);
      i++;
      continue;
    }

    // 普通行
    nodes.push(<span key={i}>{inlineMarkdown(line)}<br /></span>);
    i++;
  }
  return nodes;
}

function inlineMarkdown(text: string): React.ReactNode {
  // 粗体 **text**
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith('**') && p.endsWith('**')) return <strong key={i}>{p.slice(2, -2)}</strong>;
        if (p.startsWith('`') && p.endsWith('`')) return <code key={i}>{p.slice(1, -1)}</code>;
        return p;
      })}
    </>
  );
}

// 系统消息
export const SystemMessage: React.FC<{ content: string }> = ({ content }) => {
  return (
    <div className="chat-message system">
      <div className="message-content-wrapper">
        <div className="system-content">
          <StatusBadge status="unknown" size="small" text={content} />
        </div>
      </div>
    </div>
  );
};

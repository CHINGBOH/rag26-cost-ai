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
      
      lastIndex = block.index + block.code.length + 6 + (block.language?.length || 0);
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

        {/* RAG 流程指示器 */}
        {message.ragProcess && message.ragProcess.length > 0 && (
          <div className="message-rag-indicator">
            <RagProcessMini steps={message.ragProcess} />
          </div>
        )}

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

// Markdown 文本渲染
const MarkdownText: React.FC<{ content: string }> = ({ content }) => {
  // 简单的 Markdown 处理
  const formatted = useMemo(() => {
    return content
      // 粗体
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      // 斜体
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      // 行内代码
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      // 换行
      .replace(/\n/g, '<br/>');
  }, [content]);

  return (
    <span 
      className="markdown-text"
      dangerouslySetInnerHTML={{ __html: formatted }}
    />
  );
};

// RAG 流程迷你指示器
const RagProcessMini: React.FC<{ steps: import('@rag/shared').RagProcessStep[] }> = ({ steps }) => {
  const completedSteps = steps.filter(s => s.status === 'completed').length;
  const runningStep = steps.find(s => s.status === 'running');
  
  const stepLabels: Record<string, string> = {
    intent_recognition: '意图',
    task_decomposition: '拆解',
    query_generation: '查询',
    vector_retrieval: '向量',
    knowledge_retrieval: '知识',
    graph_retrieval: '图谱',
    reranking: '精排',
    prompt_assembly: '组装',
    llm_generation: '生成',
    answer_formatting: '格式化'
  };

  return (
    <div className="rag-mini-indicator">
      <div className="rag-progress-bar">
        <div 
          className="rag-progress-fill"
          style={{ width: `${(completedSteps / steps.length) * 100}%` }}
        />
      </div>
      <div className="rag-steps">
        {steps.slice(0, uiConfig.messages.maxRagStepsDisplay).map((step) => (
          <span 
            key={step.type} 
            className={`rag-step ${step.status}`}
            title={stepLabels[step.type]}
          >
            {step.status === 'completed' ? '✓' : 
             step.status === 'running' ? '◐' : '○'}
          </span>
        ))}
        {steps.length > uiConfig.messages.maxRagStepsDisplay && (
          <span className="rag-step-more">+{steps.length - uiConfig.messages.maxRagStepsDisplay}</span>
        )}
      </div>
      {runningStep && (
        <span className="rag-current">
          {stepLabels[runningStep.type]}...
        </span>
      )}
    </div>
  );
};

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

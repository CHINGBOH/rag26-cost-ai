/**
 * 聊天界面主组件 - 看板式重构
 * 对话为核心，基础设施状态为看板，任务管道实时可视化
 */

import { useState, useRef, useEffect } from 'react';
import { useChatStore } from '../../stores/chatStore';
import { ChatMessage } from './ChatMessage';
import { ChatInput, QuickPromptButtons } from './ChatInput';
import { ChatControlPanel } from './ChatControlPanel';
import { InlineReferences } from './InlineReferences';
import { TokenUsageBar } from './TokenUsageBar';
import { InfrastructureDashboard } from './InfrastructureDashboard';
import { TaskPipelineVisual } from './TaskPipelineVisual';
import { ChatMessage as ChatMessageType, ChatConfig, RagProcessStep, LLMProviderType } from '@rag/shared';
import { sendLLMRequest, LLMMessage } from '../../services/llmApi';
import { 
  getActiveLLMConfig, 
  capabilities,
  branding,
  activeProvider,
  shouldUseRAG,
  retrievalConfig,
  retrieveDocuments,
  uiConfig,
  chatFlowConfig
} from '../../config';
import './Chat.css';

// 任务阶段定义
export type PipelineStage = 
  | 'idle'
  | 'intent_analysis'
  | 'query_decomposition'
  | 'vector_retrieval'
  | 'knowledge_retrieval'
  | 'graph_retrieval'
  | 'reranking'
  | 'context_assembly'
  | 'llm_generation'
  | 'complete';

interface PipelineState {
  stage: PipelineStage;
  progress: number;
  status: 'pending' | 'running' | 'completed' | 'error';
  details?: string;
  metrics?: Record<string, number>;
}

export const ChatInterface: React.FC = () => {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  
  // Store 状态
  const sessions = useChatStore(state => state.sessions);
  const activeSessionId = useChatStore(state => state.activeSessionId);
  const isLoading = useChatStore(state => state.isLoading);
  const streamingMessageId = useChatStore(state => state.streamingMessageId);
  
  const createSession = useChatStore(state => state.createSession);
  const setActiveSession = useChatStore(state => state.setActiveSession);
  const addMessage = useChatStore(state => state.addMessage);
  const setSessionConfig = useChatStore(state => state.setSessionConfig);
  
  // 本地状态
  const [isControlPanelOpen, setIsControlPanelOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [pipeline, setPipeline] = useState<PipelineState>({
    stage: 'idle',
    progress: 0,
    status: 'pending'
  });
  const [activeTask, setActiveTask] = useState<{
    query: string;
    startTime: number;
  } | null>(null);
  
  // 获取当前会话
  const activeSession = activeSessionId ? sessions.get(activeSessionId) : null;
  const messages = activeSession?.messages || [];
  const config = activeSession?.config || getDefaultConfig();
  
  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingMessageId]);
  
  // 应用 UI 配置到 CSS 变量
  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty('--sidebar-width', `${uiConfig.sidebar.expandedWidth}px`);
    root.style.setProperty('--sidebar-collapsed-width', `${uiConfig.sidebar.collapsedWidth}px`);
    root.style.setProperty('--content-max-width', `${uiConfig.mainContent.maxWidth}px`);
    root.style.setProperty('--content-padding-x', `${uiConfig.mainContent.paddingX}px`);
    root.style.setProperty('--input-min-height', `${uiConfig.inputArea.minHeight}px`);
    root.style.setProperty('--input-max-height', `${uiConfig.inputArea.maxHeight}px`);
    root.style.setProperty('--anim-fast', `${uiConfig.animations.hoverTransform}ms`);
    root.style.setProperty('--anim-normal', `${uiConfig.animations.messageFadeIn}ms`);
    root.style.setProperty('--anim-slow', `${uiConfig.animations.sidebarTransition}ms`);
    root.style.setProperty('--anim-pulse', `${uiConfig.animations.stagePulse}ms`);
    root.style.setProperty('--panel-width', `${uiConfig.controlPanel.width}px`);
    root.style.setProperty('--panel-overlay-opacity', `${uiConfig.controlPanel.overlayOpacity}`);
    root.style.setProperty('--panel-z-index', `${uiConfig.controlPanel.zIndex}`);
    
    // Input controls
    root.style.setProperty('--slider-height', '5px');
    root.style.setProperty('--slider-thumb-size', '17px');
    root.style.setProperty('--toggle-width', '48px');
    root.style.setProperty('--toggle-height', '26px');
    root.style.setProperty('--toggle-thumb-size', '20px');
    
    // Button sizes
    root.style.setProperty('--btn-icon-size', '32px');
    root.style.setProperty('--btn-icon-size-sm', '20px');
    root.style.setProperty('--new-chat-icon-size', '18px');
    root.style.setProperty('--collapse-btn-size', '32px');
    root.style.setProperty('--send-btn-size', '52px');
    
    // Spacing
    root.style.setProperty('--spacing-xs', '4px');
    root.style.setProperty('--spacing-sm', '8px');
    root.style.setProperty('--spacing-md', '12px');
    root.style.setProperty('--spacing-lg', '16px');
    root.style.setProperty('--spacing-xl', '20px');
    root.style.setProperty('--spacing-2xl', '24px');
    root.style.setProperty('--spacing-3xl', '40px');
    root.style.setProperty('--spacing-4xl', '48px');
    
    // Border radius
    root.style.setProperty('--radius-sm', '4px');
    root.style.setProperty('--radius-md', '6px');
    root.style.setProperty('--radius-lg', '8px');
    root.style.setProperty('--radius-xl', '10px');
    root.style.setProperty('--radius-2xl', '12px');
    root.style.setProperty('--radius-full', '50%');
    
    // Font sizes
    root.style.setProperty('--text-xs', '10px');
    root.style.setProperty('--text-sm', '11px');
    root.style.setProperty('--text-md', '12px');
    root.style.setProperty('--text-base', '13px');
    root.style.setProperty('--text-lg', '14px');
    root.style.setProperty('--text-xl', '15px');
    root.style.setProperty('--text-2xl', '16px');
    root.style.setProperty('--text-3xl', '18px');
    root.style.setProperty('--text-4xl', '20px');
    root.style.setProperty('--text-5xl', '24px');
    root.style.setProperty('--text-6xl', '28px');
    
    // Pipeline
    root.style.setProperty('--pipeline-progress-height', '2px');
    root.style.setProperty('--pipeline-query-padding-y', '8px');
    root.style.setProperty('--pipeline-query-padding-x', '12px');
    root.style.setProperty('--pipeline-stage-gap', '6px');
    root.style.setProperty('--pipeline-stage-padding', '6px 10px');
    
    // Grid layouts
    root.style.setProperty('--services-grid-min-width', `${uiConfig.grid.servicesGrid.minColumnWidth}px`);
    root.style.setProperty('--services-grid-gap', `${uiConfig.grid.servicesGrid.gap}px`);
    root.style.setProperty('--quick-prompts-columns', `${uiConfig.grid.quickPromptsGrid.columns}`);
    root.style.setProperty('--quick-prompts-columns-tablet', `${uiConfig.grid.quickPromptsGrid.columnsTablet}`);
    root.style.setProperty('--quick-prompts-columns-mobile', `${uiConfig.grid.quickPromptsGrid.columnsMobile}`);
    root.style.setProperty('--quick-prompts-gap', `${uiConfig.grid.quickPromptsGrid.gap}px`);
    root.style.setProperty('--provider-grid-columns', `${uiConfig.grid.providerGrid.columns}`);
    root.style.setProperty('--provider-grid-gap', `${uiConfig.grid.providerGrid.gap}px`);
    
    // Flex layouts
    root.style.setProperty('--sessions-list-gap', `${uiConfig.flex.sessionsList.gap}px`);
    root.style.setProperty('--capabilities-gap', `${uiConfig.flex.capabilities.gap}px`);
    root.style.setProperty('--messages-list-gap', `${uiConfig.flex.messagesList.gap}px`);
    root.style.setProperty('--input-area-gap', `${uiConfig.flex.inputArea.gap}px`);
    root.style.setProperty('--model-info-row-gap', `${uiConfig.flex.modelInfoRow.gap}px`);
    root.style.setProperty('--msg-avatar-size', `${uiConfig.messages.avatarSize}px`);
    root.style.setProperty('--msg-border-radius', `${uiConfig.messages.borderRadius}px`);
    root.style.setProperty('--msg-gap', `${uiConfig.messages.gap}px`);
    root.style.setProperty('--welcome-title-size', `${uiConfig.welcome.titleSize}px`);
    root.style.setProperty('--welcome-subtitle-size', `${uiConfig.welcome.subtitleSize}px`);
  }, []);

  // 默认配置 - 从配置文件读取
  function getDefaultConfig(): ChatConfig {
    const activeLLM = getActiveLLMConfig();
    return {
      provider: activeLLM.id as LLMProviderType,
      model: activeLLM.defaultModel,
      temperature: activeLLM.defaultParams.temperature,
      maxTokens: activeLLM.defaultParams.maxTokens,
      topP: activeLLM.defaultParams.topP,
      frequencyPenalty: 0,
      presencePenalty: 0,
      enableRag: true,
      ragParams: {
        topK: 100,
        threshold: 0.7,
        rerank: true,
        maxReferences: 5,
        contextWindow: 4000
      }
    };
  }

  // 创建新会话
  const handleNewSession = () => {
    const id = createSession();
    setActiveSession(id);
    resetPipeline();
  };

  // 重置管道
  const resetPipeline = () => {
    setPipeline({ stage: 'idle', progress: 0, status: 'pending' });
    setActiveTask(null);
  };

  // 模拟RAG任务流程 - 实时更新
  const executeRAGPipeline = async (query: string) => {
    const stages: { stage: PipelineStage; duration: number; details: string }[] = [
      { stage: 'intent_analysis', duration: 600, details: '分析查询意图' },
      { stage: 'query_decomposition', duration: 800, details: '分解子查询' },
      { stage: 'vector_retrieval', duration: 1200, details: '向量库检索中...' },
      { stage: 'knowledge_retrieval', duration: 1000, details: '知识库检索中...' },
      { stage: 'graph_retrieval', duration: 800, details: '图数据库查询...' },
      { stage: 'reranking', duration: 700, details: '精排筛选结果' },
      { stage: 'context_assembly', duration: 500, details: '组装上下文' },
      { stage: 'llm_generation', duration: 2500, details: '生成回答...' },
    ];

    setActiveTask({ query, startTime: Date.now() });
    
    for (let i = 0; i < stages.length; i++) {
      const { stage, duration, details } = stages[i];
      const progress = ((i + 1) / (stages.length + 1)) * 100;
      
      setPipeline({
        stage,
        progress,
        status: 'running',
        details,
        metrics: generateStageMetrics(stage)
      });
      
      await new Promise(resolve => setTimeout(resolve, duration));
    }

    setPipeline({
      stage: 'complete',
      progress: 100,
      status: 'completed',
      details: '任务完成'
    });

    setTimeout(() => {
      resetPipeline();
    }, 2000);
  };

  // 生成阶段指标
  const generateStageMetrics = (stage: PipelineStage): Record<string, number> => {
    switch (stage) {
      case 'vector_retrieval':
        return { retrieved: 156, filtered: 89 };
      case 'knowledge_retrieval':
        return { articles: 23, entities: 45 };
      case 'graph_retrieval':
        return { nodes: 12, relationships: 28 };
      case 'reranking':
        return { input: 89, output: 15, topScore: 0.94 };
      case 'llm_generation':
        return { tokensPerSecond: 45, tokensGenerated: 0 };
      default:
        return {};
    }
  };

  // 发送消息 - 真实 LLM API
  const handleSendMessage = async (content: string) => {
    // 自动创建会话：如果没有活动会话，根据配置决定是否自动创建
    let sessionId = activeSessionId;
    if (!sessionId && chatFlowConfig.autoCreateSession) {
      sessionId = createSession();
    }
    
    if (!sessionId) return; // 如果仍未创建成功，不继续
    const startTime = Date.now();
    
    // 添加用户消息
    const userMessage: ChatMessageType = {
      id: `msg-${Date.now()}-user`,
      role: 'user',
      content,
      timestamp: startTime
    };
    addMessage(sessionId, userMessage);
    
    // 智能路由：判断是否需要走 RAG 流程
    const useRAG = shouldUseRAG(content);
    
    if (useRAG) {
      // 执行完整 RAG 流程动画
      await executeRAGPipeline(content);
    } else {
      // 简单查询：显示快速生成状态
      setPipeline({
        stage: 'llm_generation',
        progress: 50,
        status: 'running',
        details: '直接生成回答...',
        metrics: { directMode: 1 }
      });
    }
    
    try {
      // 1. 检索相关文档
      const references = useRAG ? await generateReferences(content) : [];
      const hasReferences = references.length >= retrievalConfig.minReferences;
      
      // 2. 构建消息历史
      const historyMessages: LLMMessage[] = messages
        .filter(m => m.id !== userMessage.id)
        .map(m => ({
          role: m.role as 'user' | 'assistant',
          content: m.content
        }));
      
      // 3. 构建系统提示
      let systemPrompt = '你是一个智能助手，请帮助用户解答问题。';
      
      if (useRAG) {
        if (hasReferences) {
          // 有参考资料：要求基于资料回答
          const contextText = references
            .map((ref, i) => `[${i + 1}] ${ref.chunk.content}`)
            .join('\n\n');
          systemPrompt += `\n\n请基于以下参考资料回答用户问题。如果资料不足以回答问题，请明确说明。\n\n参考资料：\n${contextText}`;
        } else {
          // 无参考资料：明确告知不要瞎编
          systemPrompt += `\n\n${retrievalConfig.noReferencesPrompt}\n\n重要：如果问题涉及专业知识且你不太确定，请明确告知用户"未在知识库中找到相关资料"，不要编造具体数据或标准。`;
        }
      }
      
      // 4. 构建提示
      const messagesToSend: LLMMessage[] = [
        { role: 'system', content: systemPrompt },
        ...historyMessages.slice(-4),
        { role: 'user', content }
      ];
      
      // 5. 调用真实 LLM API
      const response = await sendLLMRequest(messagesToSend, {
        temperature: config?.temperature ?? 0.7,
        maxTokens: config?.maxTokens ?? 2000,
        topP: config?.topP ?? 0.9
      });
      
      const aiContent = response.choices[0]?.message?.content || '抱歉，无法生成回复';
      const latency = Date.now() - startTime;
      
      // 6. 添加AI回复
      const assistantMessage: ChatMessageType = {
        id: `msg-${Date.now()}-assistant`,
        role: 'assistant',
        content: aiContent,
        timestamp: Date.now(),
        model: getActiveLLMConfig().defaultModel,
        tokenCount: response.usage?.completion_tokens || Math.ceil(aiContent.length / 4),
        latency,
        references: hasReferences ? references : [],
        ragProcess: generateRagProcess(hasReferences)
      };
      addMessage(sessionId, assistantMessage);
      
      // 完成 pipeline
      setPipeline({
        stage: 'complete',
        progress: 100,
        status: 'completed',
        details: '完成'
      });
      
      setTimeout(() => {
        resetPipeline();
      }, chatFlowConfig.pipeline.autoResetDelay);
      
    } catch (error) {
      console.error('LLM API Error:', error);
      
      // 添加错误消息
      const errorMessage: ChatMessageType = {
        id: `msg-${Date.now()}-error`,
        role: 'assistant',
        content: chatFlowConfig.errorMessages.apiError(
          error instanceof Error ? error.message : chatFlowConfig.errorMessages.genericError
        ),
        timestamp: Date.now(),
        model: 'error'
      };
      addMessage(sessionId, errorMessage);
    }
  };

  // 清除对话
  const handleClear = () => {
    if (activeSessionId && confirm(chatFlowConfig.confirmDialog.clearChat)) {
      // TODO: 清除消息
      resetPipeline();
    }
  };

  return (
    <div className="chat-dashboard">
      {/* 顶部基础设施看板 */}
      <InfrastructureDashboard 
        activeProvider={config?.provider || activeProvider}
        activeEngine={config?.engine || 'default'}
      />

      {/* 主内容区 */}
      <div className="chat-main-layout">
        {/* 左侧边栏 - 可折叠 */}
        <aside className={`chat-sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
          <div className="sidebar-header">
            <button className="new-chat-btn" onClick={handleNewSession}>
              <span>{chatFlowConfig.newChatButton.icon}</span>
              {!sidebarCollapsed && chatFlowConfig.newChatButton.text}
            </button>
            <button 
              className="collapse-btn"
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            >
              {sidebarCollapsed ? chatFlowConfig.collapseButton.collapsedIcon : chatFlowConfig.collapseButton.expandedIcon}
            </button>
          </div>
          
          {!sidebarCollapsed && (
            <div className="sessions-list">
              {Array.from(sessions.values())
                .sort((a, b) => b.updatedAt - a.updatedAt)
                .map(session => (
                  <div
                    key={session.id}
                    className={`session-item ${session.id === activeSessionId ? 'active' : ''}`}
                    onClick={() => setActiveSession(session.id)}
                  >
                    <span className="session-icon">{chatFlowConfig.ui.sessionList.sessionIcon}</span>
                    <span className="session-title">{session.title}</span>
                  </div>
                ))}
            </div>
          )}
        </aside>

        {/* 对话核心区域 */}
        <main className="chat-core">
          {/* 任务管道可视化 - 处理时显示在顶部 */}
          {(pipeline.stage !== 'idle' || activeTask) && (
            <TaskPipelineVisual 
              state={pipeline}
              query={activeTask?.query}
              onCancel={() => resetPipeline()}
            />
          )}

          {/* 消息区域 */}
          <div className="messages-area">
            {messages.length === 0 ? (
              <div className="welcome-center">
                <div className="welcome-content">
                  <h1 className="welcome-title">
                    <span className="gradient-text">{branding.name}</span>
                  </h1>
                  <p className="welcome-subtitle">
                    {branding.subtitle}
                  </p>
                  
                  {/* 快速提示 */}
                  <div className="quick-prompts-container">
                    <QuickPromptButtons onSelect={handleSendMessage} />
                  </div>

                  {/* 能力展示 - 从配置读取 */}
                  <div className="capabilities">
                    {capabilities.map((cap, idx) => (
                      <div key={idx} className="capability">
                        <span className="cap-icon">{cap.icon}</span>
                        <span>{cap.title}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="messages-list">
                {messages.map((message, index) => (
                  <div key={message.id} className="message-wrapper">
                    <ChatMessage
                      message={message}
                      isStreaming={message.id === streamingMessageId}
                    />
                    
                    {message.role === 'assistant' && message.references && (
                      <InlineReferences references={message.references} />
                    )}
                    
                    {message.role === 'assistant' && message.tokenCount && (
                      <div className="message-meta">
                        <TokenUsageBar
                          inputTokens={Math.ceil((messages[index - 1]?.content?.length || 0) / 4)}
                          outputTokens={message.tokenCount}
                          model={message.model}
                        />
                      </div>
                    )}
                  </div>
                ))}
                <div ref={messagesEndRef} />
              </div>
            )}
          </div>

          {/* 底部输入区 - 固定 */}
          <div className="input-area-fixed">
            <div className="input-container">
              <ChatInput
                onSend={handleSendMessage}
                onClear={handleClear}
                disabled={isLoading || pipeline.stage !== 'idle' && pipeline.stage !== 'complete'}
                isLoading={isLoading || pipeline.stage !== 'idle' && pipeline.stage !== 'complete'}
                placeholder={activeSessionId 
                  ? chatFlowConfig.placeholders.withSession 
                  : chatFlowConfig.placeholders.noSession}
                // 模型和温度控制 - 绑定到会话配置（无会话时自动创建）
                selectedModel={config.model}
                onModelChange={(model) => {
                  console.log('模型变更:', model, '当前会话:', activeSessionId);
                  let sessionId = activeSessionId;
                  if (!sessionId) {
                    sessionId = createSession();
                    console.log('创建新会话:', sessionId);
                  }
                  if (sessionId) {
                    setSessionConfig(sessionId, { model });
                    console.log('设置模型完成');
                  }
                }}
                temperature={config.temperature}
                onTemperatureChange={(temperature) => {
                  console.log('温度变更:', temperature, '当前会话:', activeSessionId);
                  let sessionId = activeSessionId;
                  if (!sessionId) {
                    sessionId = createSession();
                    console.log('创建新会话:', sessionId);
                  }
                  if (sessionId) {
                    setSessionConfig(sessionId, { temperature });
                    console.log('设置温度完成');
                  }
                }}
                onSettingsClick={() => setIsControlPanelOpen(true)}
              />
            </div>
          </div>
        </main>
      </div>

      {/* 右侧设置面板 - 滑出式 */}
      <ChatControlPanel
        config={config}
        onConfigChange={(newConfig) => {
          if (activeSessionId) {
            setSessionConfig(activeSessionId, newConfig);
          }
        }}
        isOpen={isControlPanelOpen}
        onClose={() => setIsControlPanelOpen(false)}
      />
    </div>
  );
};

// 生成引用 - 实际应调用向量检索
async function generateReferences(query: string): Promise<import('@rag/shared').ChatReference[]> {
  // 调用检索函数
  const result = await retrieveDocuments(query);
  
  if (!result.found || result.references.length === 0) {
    return []; // 没有找到相关资料
  }
  
  // 过滤低于阈值的文档
  const validRefs = result.references
    .filter(ref => ref.score >= retrievalConfig.similarityThreshold)
    .slice(0, retrievalConfig.maxReferences);
  
  if (validRefs.length < retrievalConfig.minReferences) {
    return []; // 相关文档不足
  }
  
  // 转换为 ChatReference 格式
  return validRefs.map((ref, index) => ({
    id: ref.id,
    index: index + 1,
    chunk: {
      id: ref.id,
      content: ref.content,
      source: ref.source,
      database: 'vector',
      score: ref.score,
      metadata: {}
    },
    relevanceScore: ref.score,
    usedInAnswer: true
  }));
}

// 生成RAG流程
function generateRagProcess(hasReferences: boolean): RagProcessStep[] {
  const now = Date.now();
  
  if (!hasReferences) {
    // 无相关文档的流程
    return [
      {
        type: 'intent_recognition',
        status: 'completed',
        startTime: now - 3000,
        endTime: now - 2600,
        latency: 400,
        data: { intentType: 'general_query', confidence: 0.88 }
      },
      {
        type: 'vector_retrieval',
        status: 'completed',
        startTime: now - 2600,
        endTime: now - 2000,
        latency: 600,
        data: { dbType: 'qdrant', resultCount: 0 }
      },
      {
        type: 'reranking',
        status: 'completed',
        startTime: now - 2000,
        endTime: now - 1800,
        latency: 200,
        data: { inputCount: 0, outputCount: 0 }
      },
      {
        type: 'prompt_assembly',
        status: 'completed',
        startTime: now - 1800,
        endTime: now - 1700,
        latency: 100,
        data: { tokenCount: 500, contextLength: 0 }
      },
      {
        type: 'llm_generation',
        status: 'completed',
        startTime: now - 1700,
        endTime: now,
        latency: 1700,
        data: { tokensGenerated: 280, tokensPerSecond: 42 }
      }
    ];
  }
  
  // 有相关文档的完整流程
  return [
    {
      type: 'intent_recognition',
      status: 'completed',
      startTime: now - 5000,
      endTime: now - 4600,
      latency: 400,
      data: { intentType: 'knowledge_query', confidence: 0.94 }
    },
    {
      type: 'task_decomposition',
      status: 'completed',
      startTime: now - 4600,
      endTime: now - 4100,
      latency: 500,
      data: { subQueries: [
        { id: 'sq-1', query: '相关概念检索', targetDB: 'vector', status: 'completed' }
      ]}
    },
    {
      type: 'vector_retrieval',
      status: 'completed',
      startTime: now - 4100,
      endTime: now - 3200,
      latency: 900,
      data: { dbType: 'qdrant', resultCount: 12 }
    },
    {
      type: 'reranking',
      status: 'completed',
      startTime: now - 3200,
      endTime: now - 2700,
      latency: 500,
      data: { inputCount: 12, outputCount: 3, topScore: 0.92 }
    },
    {
      type: 'prompt_assembly',
      status: 'completed',
      startTime: now - 2700,
      endTime: now - 2600,
      latency: 100,
      data: { tokenCount: 1200, contextLength: 3000 }
    },
    {
      type: 'llm_generation',
      status: 'completed',
      startTime: now - 2600,
      endTime: now,
      latency: 2600,
      data: { tokensGenerated: 380, tokensPerSecond: 45 }
    }
  ];
}

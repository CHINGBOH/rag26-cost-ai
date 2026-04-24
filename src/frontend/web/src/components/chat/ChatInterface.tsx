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
import { 
  getActiveLLMConfig,
  capabilities,
  branding,
  activeProvider,
  uiConfig,
  chatFlowConfig
} from '../../config';
import './Chat.css';
import { PipelineState } from './types';

export const ChatInterface: React.FC = () => {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  
  // Store 状态
  const sessions = useChatStore(state => state.sessions);
  const activeSessionId = useChatStore(state => state.activeSessionId);
  const isLoading = useChatStore(state => state.isLoading);
  const streamingMessageId = useChatStore(state => state.streamingMessageId);
  
  const createSession = useChatStore(state => state.createSession);
  const clearMessages = useChatStore(state => state.clearMessages);
  const setActiveSession = useChatStore(state => state.setActiveSession);
  const addMessage = useChatStore(state => state.addMessage);
  const setSessionConfig = useChatStore(state => state.setSessionConfig);
  const updateMessage = useChatStore(state => state.updateMessage);
  const setStreaming = useChatStore(state => state.setStreaming);
  const appendMessageContent = useChatStore(state => state.appendMessageContent);
  
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

  const abortControllerRef = useRef<AbortController | null>(null);

  // 组件卸载时终止进行中的请求
  useEffect(() => {
    return () => { abortControllerRef.current?.abort(); };
  }, []);
  const activeSession = activeSessionId ? sessions[activeSessionId] : null;
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

  // 重置管道（新会话/清除时用）
  const resetPipeline = () => {
    setPipeline({ stage: 'idle', progress: 0, status: 'pending' });
    setActiveTask(null);
    abortControllerRef.current?.abort();
  };

  // 发送消息 - Agent SSE 流式接入
  const handleSendMessage = async (content: string) => {
    let sessionId = activeSessionId;
    if (!sessionId && chatFlowConfig.autoCreateSession) {
      sessionId = createSession();
    }
    if (!sessionId) return;

    const startTime = Date.now();

    // 添加用户消息
    addMessage(sessionId, {
      id: `msg-${startTime}-user`,
      role: 'user',
      content,
      timestamp: startTime,
    });

    // 创建 Agent 占位回复（立即显示进度）
    const assistantMsgId = `msg-${startTime}-assistant`;
    addMessage(sessionId, {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      ragProcess: [{ type: 'intent_recognition', status: 'running', startTime, data: { label: '理解问题中...' } }],
    });
    setStreaming(assistantMsgId);

    // 中止上一个请求
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    // 本地状态：追踪 ragProcess 步骤
    const ragSteps: RagProcessStep[] = [{ type: 'intent_recognition', status: 'running', startTime, data: { label: '理解问题中...' } }];
    let hasAnswer = false;

    const intentLabels: Record<string, string> = {
      comparison: '对比分析', price: '价格查询', calculation: '计算分析',
      trend_chart: '趋势分析', fact: '事实查询', chitchat: '闲聊', off_topic: '话题外',
    };
    const toolLabels: Record<string, string> = {
      text_search: '全文检索', vector_search: '向量检索', keyword_search: '关键词检索',
      price_query: '价格查询', price_trend: '价格走势', category_search: '目录检索',
      calculator: '计算器', python_eval: '代码执行',
    };

    // 同步当前步骤到消息（不修改 content）
    const syncSteps = (extra: Partial<ChatMessageType> = {}) => {
      updateMessage(sessionId!, assistantMsgId, {
        ragProcess: [...ragSteps],
        ...extra,
      });
    };

    try {
      const res = await fetch('/api/v1/agent/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: content, max_iterations: 3, score_threshold: 0.6, top_k: 8 }),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split('\n\n');
        buffer = blocks.pop() ?? '';

        for (const block of blocks) {
          if (!block.trim()) continue;
          let evtType = 'message';
          let evtData = '';
          for (const line of block.split('\n')) {
            if (line.startsWith('event: ')) evtType = line.slice(7).trim();
            else if (line.startsWith('data: ')) evtData = line.slice(6).trim();
          }
          if (!evtData) continue;
          let data: Record<string, any>;
          try { data = JSON.parse(evtData); } catch { continue; }

          switch (evtType) {
            case 'query_analysis': {
              const intent = (data.intent as string) || '';
              const label = intentLabels[intent] || intent;
              ragSteps[0] = { type: 'intent_recognition', status: 'completed', endTime: Date.now(), data: { label: `问题理解${label ? `：${label}` : '完成'}` } };
              // 闲聊/话题外：直接等 token，无 plan 事件
              if (intent === 'chitchat' || intent === 'off_topic') {
                ragSteps.push({ type: 'llm_generation', status: 'running', startTime: Date.now(), data: { label: '生成回答中...' } });
              } else {
                ragSteps.push({ type: 'task_decomposition', status: 'running', startTime: Date.now(), data: { label: '制定检索计划...' } });
              }
              syncSteps();
              break;
            }

            case 'plan': {
              const steps = (data.steps as string[]) || [];
              const tdIdx = ragSteps.findIndex(s => s.type === 'task_decomposition');
              const planSteps = steps.map(s => {
                const qMatch = s.match(/query="([^"]+)"/);
                return qMatch ? `检索："${qMatch[1]}"` : s;
              });
              if (tdIdx >= 0) {
                ragSteps[tdIdx] = {
                  ...ragSteps[tdIdx],
                  status: 'completed',
                  endTime: Date.now(),
                  data: { label: `检索计划（共 ${steps.length} 步）`, planSteps },
                };
              }
              ragSteps.push({ type: 'knowledge_retrieval', status: 'running', startTime: Date.now(), data: { label: '执行检索中...' } });
              syncSteps();
              break;
            }

            case 'tool_call_end': {
              const tool = (data.tool as string) || '';
              const summary = ((data.result_summary as string) || '').slice(0, 60);
              const durationMs = (data.duration_ms as number) | 0;
              const label = toolLabels[tool] || tool;
              // Mark last running step complete
              for (let i = ragSteps.length - 1; i >= 0; i--) {
                if (ragSteps[i].status === 'running') {
                  ragSteps[i] = {
                    ...ragSteps[i],
                    status: 'completed',
                    endTime: Date.now(),
                    latency: durationMs || undefined,
                    data: { label: `${label}${summary ? `：${summary}` : ''}` },
                  };
                  ragSteps.push({ type: 'knowledge_retrieval', status: 'running', startTime: Date.now(), data: { label: '继续检索中...' } });
                  break;
                }
              }
              syncSteps();
              break;
            }

            case 'token': {
              const delta = (data.delta as string) || '';
              if (!delta) break;
              if (!hasAnswer) {
                hasAnswer = true;
                // Mark all running as completed, add llm_generation running
                ragSteps.forEach((s, i) => {
                  if (s.status === 'running') ragSteps[i] = { ...s, status: 'completed', endTime: Date.now() };
                });
                ragSteps.push({ type: 'llm_generation', status: 'running', startTime: Date.now(), data: { label: '综合分析中...' } });
                updateMessage(sessionId!, assistantMsgId, {
                  content: delta,
                  ragProcess: [...ragSteps],
                });
              } else {
                appendMessageContent(sessionId!, assistantMsgId, delta);
              }
              break;
            }

            case 'done': {
              ragSteps.forEach((s, i) => {
                if (s.status === 'running') ragSteps[i] = { ...s, status: 'completed', endTime: Date.now() };
              });
              ragSteps.push({ type: 'answer_formatting', status: 'completed', startTime: Date.now(), endTime: Date.now(), data: { label: '回答完成' } });
              updateMessage(sessionId!, assistantMsgId, {
                ragProcess: [...ragSteps],
                latency: Date.now() - startTime,
                model: 'deepseek-chat',
              });
              setStreaming(null);
              break;
            }

            case 'error': {
              const errMsg = (data.message as string) || '未知错误';
              ragSteps.forEach((s, i) => {
                if (s.status === 'running') ragSteps[i] = { ...s, status: 'failed' as const, data: { label: `错误：${errMsg}` } };
              });
              updateMessage(sessionId!, assistantMsgId, {
                content: `❌ 出错了：${errMsg}`,
                ragProcess: [...ragSteps],
              });
              setStreaming(null);
              break;
            }
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        updateMessage(sessionId!, assistantMsgId, {
          content: `❌ 请求失败：${(err as Error).message}`,
        });
      }
      setStreaming(null);
    }
  };

  // 清除对话
  const handleClear = () => {
    if (activeSessionId && confirm(chatFlowConfig.confirmDialog.clearChat)) {
      clearMessages(activeSessionId);
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
              {Object.values(sessions)
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
                  let sessionId = activeSessionId;
                  if (!sessionId) {
                    sessionId = createSession();
                  }
                  if (sessionId) {
                    setSessionConfig(sessionId, { model });
                  }
                }}
                temperature={config.temperature}
                onTemperatureChange={(temperature) => {
                  let sessionId = activeSessionId;
                  if (!sessionId) {
                    sessionId = createSession();
                  }
                  if (sessionId) {
                    setSessionConfig(sessionId, { temperature });
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

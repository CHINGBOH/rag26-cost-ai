// @ts-nocheck
import { useState, useEffect, useRef } from 'react';
import './RAGChat.css';

/**
 * 现代化RAG聊天组件
 * 基于WebSocket的实时交互架构
 */
const RAGChat = () => {
  const [messages, setMessages] = useState<any[]>([]);
  const [input, setInput] = useState('');
  const [isConnected, setIsConnected] = useState(false);
  const [activeTask, setActiveTask] = useState<any>(null);
  const [taskStages, setTaskStages] = useState<Record<string, any>>({});
  const wsRef = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const userId = useRef(`user_${Date.now()}_${crypto.randomUUID().slice(0, 9)}`);

  // WebSocket连接
  useEffect(() => {
    connectWebSocket();
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, activeTask]);

  const connectWebSocket = () => {
    const wsUrl = import.meta.env.VITE_WS_URL || `ws://${window.location.host}/ws?room=${userId.current}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      console.log('WebSocket connected');
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      handleWebSocketMessage(data);
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      setIsConnected(false);
    };

    ws.onclose = () => {
      console.log('WebSocket disconnected');
      setIsConnected(false);
      // 自动重连
      setTimeout(connectWebSocket, 3000);
    };
  };

  const handleWebSocketMessage = (data) => {
    switch (data.event) {
      case 'init':
        // 初始化已有任务
        data.data.tasks.forEach(task => {
          setMessages(prev => [...prev, {
            id: task.id,
            type: 'user',
            content: task.query,
            timestamp: task.metadata.createdAt
          }]);
          
          if (task.status === 'completed') {
            setMessages(prev => [...prev, {
              id: `${task.id}_response`,
              type: 'assistant',
              content: task.results.answer,
              timestamp: task.metadata.completedAt,
              sources: task.results.rerankedDocs.slice(0, 3)
            }]);
          }
        });
        break;

      case 'task:created':
        setActiveTask(data.data);
        setTaskStages(data.data.stages);
        break;

      case 'task:started':
        setActiveTask(data.data);
        break;

      case 'stage:updated':
        setTaskStages(prev => ({
          ...prev,
          [data.data.stage]: {
            status: data.data.status,
            progress: data.data.progress
          }
        }));
        break;

      case 'generation:progress':
        // 实时显示生成的内容
        setActiveTask(prev => ({
          ...prev,
          progress: data.data.progress,
          partialAnswer: prev.partialAnswer ? prev.partialAnswer + data.data.chunk : data.data.chunk
        }));
        break;

      case 'task:completed':
        setActiveTask(null);
        setTaskStages({});
        
        // 添加完整回答
        setMessages(prev => [...prev, {
          id: `${data.data.id}_response`,
          type: 'assistant',
          content: data.data.results.answer,
          timestamp: data.data.metadata.completedAt,
          sources: data.data.results.rerankedDocs.slice(0, 3),
          processingTime: data.data.metadata.processingTime
        }]);
        break;

      case 'task:failed':
        setActiveTask(null);
        setTaskStages({});
        
        setMessages(prev => [...prev, {
          id: `${data.data.id}_error`,
          type: 'error',
          content: `处理失败: ${data.data.error}`,
          timestamp: new Date()
        }]);
        break;
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || !isConnected) return;

    const query = input.trim();
    setInput('');

    // 添加用户消息
    setMessages(prev => [...prev, {
      id: Date.now(),
      type: 'user',
      content: query,
      timestamp: new Date()
    }]);

    // 发送任务请求
    wsRef.current.send(JSON.stringify({
      action: 'create_task',
      query: query,
      options: {
        use_rerank: true,
        top_k: 10,
        context_window: 4000
      }
    }));
  };

  const getStageIcon = (stageName, stage) => {
    if (stage.status === 'completed') return '✅';
    if (stage.status === 'running') return '⏳';
    if (stage.status === 'failed') return '❌';
    return '⏸️';
  };

  const getStageLabel = (stageName) => {
    const labels = {
      task_recognition: '任务识别',
      query_decomposition: '查询分解',
      retrieval: '文档检索',
      reranking: '精确重排',
      context_construction: '上下文构建',
      llm_generation: '答案生成'
    };
    return labels[stageName] || stageName;
  };

  return (
    <div className="rag-chat-container">
      {/* 连接状态指示器 */}
      <div className={`connection-status ${isConnected ? 'connected' : 'disconnected'}`}>
        <span className="status-dot"></span>
        {isConnected ? '已连接' : '连接中...'}
      </div>

      {/* 消息列表 */}
      <div className="messages-container">
        {messages.length === 0 && (
          <div className="welcome-message">
            <h2>🤖 RAG智能助手</h2>
            <p>基于深度学习的智能问答系统</p>
            <div className="features">
              <span>📚 智能检索</span>
              <span>🎯 精确重排</span>
              <span>💬 实时对话</span>
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <div key={msg.id} className={`message ${msg.type}`}>
            <div className="message-content">
              {msg.content}
            </div>
            
            {msg.sources && (
              <div className="message-sources">
                <div className="sources-title">参考来源:</div>
                {msg.sources.map((source, idx) => (
                  <div key={idx} className="source-item">
                    <span className="source-score">
                      {(source.final_score * 100).toFixed(0)}%
                    </span>
                    <span className="source-doc">
                      文档{source.document_id}第{source.page_number}页
                    </span>
                    <span className="source-content">
                      {source.content.substring(0, 50)}...
                    </span>
                  </div>
                ))}
              </div>
            )}

            {msg.processingTime && (
              <div className="message-meta">
                处理时间: {(msg.processingTime / 1000).toFixed(2)}秒
              </div>
            )}
          </div>
        ))}

        {/* 任务处理进度 */}
        {activeTask && (
          <div className="task-progress">
            <div className="progress-header">
              <span className="progress-title">正在处理您的问题...</span>
              <span className="progress-query">{activeTask.query}</span>
            </div>
            
            <div className="stages-container">
              {Object.entries(taskStages).map(([stageName, stage]) => (
                <div key={stageName} className={`stage ${stage.status}`}>
                  <div className="stage-icon">
                    {getStageIcon(stageName, stage)}
                  </div>
                  <div className="stage-info">
                    <div className="stage-label">{getStageLabel(stageName)}</div>
                    <div className="stage-progress-bar">
                      <div 
                        className="progress-fill" 
                        style={{ width: `${stage.progress}%` }}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {activeTask.partialAnswer && (
              <div className="partial-answer">
                <div className="partial-label">正在生成回答:</div>
                <div className="partial-content">
                  {activeTask.partialAnswer}
                  <span className="cursor"></span>
                </div>
              </div>
            )}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* 输入区域 */}
      <form onSubmit={handleSubmit} className="input-container">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="输入您的问题..."
          disabled={!isConnected}
          className="message-input"
        />
        <button 
          type="submit" 
          disabled={!isConnected || !input.trim()}
          className="send-button"
        >
          发送
        </button>
      </form>
    </div>
  );
};

export default RAGChat;
/**
 * 聊天状态管理
 */

import { create } from 'zustand';
import {
  ChatSession,
  ChatMessage,
  ChatConfig,
  RagProcessStep,
  DEFAULT_CHAT_CONFIG
} from '@rag/shared';

interface ChatStore {
  // 状态
  sessions: Record<string, ChatSession>;
  activeSessionId: string | null;
  isLoading: boolean;
  streamingMessageId: string | null;
  
  // Actions
  createSession: () => string;
  deleteSession: (id: string) => void;
  clearMessages: (sessionId: string) => void;
  setActiveSession: (id: string | null) => void;
  addMessage: (sessionId: string, message: ChatMessage) => void;
  updateMessage: (sessionId: string, messageId: string, updates: Partial<ChatMessage>) => void;
  setSessionConfig: (sessionId: string, config: Partial<ChatConfig>) => void;
  updateRagProcess: (sessionId: string, messageId: string, steps: RagProcessStep[]) => void;
  setStreaming: (messageId: string | null) => void;
  appendMessageContent: (sessionId: string, messageId: string, content: string) => void;
  
  // Getters
  getActiveSession: () => ChatSession | undefined;
  getSessionMessages: (sessionId: string) => ChatMessage[];
}

export const useChatStore = create<ChatStore>((set, get) => ({
  sessions: {},
  activeSessionId: null,
  isLoading: false,
  streamingMessageId: null,

  createSession: () => {
    const id = `chat-${Date.now()}-${crypto.randomUUID().slice(0, 9)}`;
    const session: ChatSession = {
      id,
      title: '新对话',
      createdAt: Date.now(),
      updatedAt: Date.now(),
      messages: [],
      config: { ...DEFAULT_CHAT_CONFIG },
      status: 'idle'
    };
    
    set((state) => ({ 
      sessions: { ...state.sessions, [id]: session },
      activeSessionId: id 
    }));
    
    return id;
  },

  deleteSession: (id) => set((state) => {
    const { [id]: _, ...rest } = state.sessions;
    return { 
      sessions: rest,
      activeSessionId: state.activeSessionId === id ? null : state.activeSessionId
    };
  }),

  clearMessages: (sessionId) => set((state) => {
    const session = state.sessions[sessionId];
    if (!session) return state;
    return { 
      sessions: { 
        ...state.sessions, 
        [sessionId]: { ...session, messages: [], updatedAt: Date.now() } 
      } 
    };
  }),

  setActiveSession: (id) => set({ activeSessionId: id }),

  addMessage: (sessionId, message) => set((state) => {
    const session = state.sessions[sessionId];
    if (!session) return state;
    
    const newMessages = [...session.messages, message];
    const newSession = { 
      ...session, 
      messages: newMessages,
      updatedAt: Date.now()
    };
    
    // 自动更新标题（第一条用户消息）
    if (message.role === 'user' && newMessages.filter(m => m.role === 'user').length === 1) {
      newSession.title = message.content.slice(0, 30) + (message.content.length > 30 ? '...' : '');
    }
    
    return { sessions: { ...state.sessions, [sessionId]: newSession } };
  }),

  updateMessage: (sessionId, messageId, updates) => set((state) => {
    const session = state.sessions[sessionId];
    if (!session) return state;
    
    const newMessages = session.messages.map(m => 
      m.id === messageId ? { ...m, ...updates } : m
    );
    
    return { sessions: { ...state.sessions, [sessionId]: { ...session, messages: newMessages } } };
  }),

  setSessionConfig: (sessionId, config) => set((state) => {
    const session = state.sessions[sessionId];
    if (!session) return state;
    
    return {
      sessions: {
        ...state.sessions,
        [sessionId]: { ...session, config: { ...session.config, ...config } }
      }
    };
  }),

  updateRagProcess: (sessionId, messageId, steps) => set((state) => {
    const session = state.sessions[sessionId];
    if (!session) return state;
    
    const newMessages = session.messages.map(m => 
      m.id === messageId ? { ...m, ragProcess: steps } : m
    );
    
    return { sessions: { ...state.sessions, [sessionId]: { ...session, messages: newMessages } } };
  }),

  setStreaming: (messageId) => set({ 
    streamingMessageId: messageId,
    isLoading: messageId !== null 
  }),

  appendMessageContent: (sessionId, messageId, content) => set((state) => {
    const session = state.sessions[sessionId];
    if (!session) return state;
    
    const newMessages = session.messages.map(m => 
      m.id === messageId 
        ? { ...m, content: m.content + content } 
        : m
    );
    
    return { sessions: { ...state.sessions, [sessionId]: { ...session, messages: newMessages } } };
  }),

  getActiveSession: () => {
    const { activeSessionId, sessions } = get();
    return activeSessionId ? sessions[activeSessionId] : undefined;
  },

  getSessionMessages: (sessionId) => {
    return get().sessions[sessionId]?.messages ?? [];
  }
}));

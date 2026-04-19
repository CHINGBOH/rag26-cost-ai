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
  sessions: Map<string, ChatSession>;
  activeSessionId: string | null;
  isLoading: boolean;
  streamingMessageId: string | null;
  
  // Actions
  createSession: () => string;
  deleteSession: (id: string) => void;
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
  sessions: new Map(),
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
    
    set((state) => {
      const newSessions = new Map(state.sessions);
      newSessions.set(id, session);
      return { 
        sessions: newSessions, 
        activeSessionId: id 
      };
    });
    
    return id;
  },

  deleteSession: (id) => set((state) => {
    const newSessions = new Map(state.sessions);
    newSessions.delete(id);
    return { 
      sessions: newSessions,
      activeSessionId: state.activeSessionId === id ? null : state.activeSessionId
    };
  }),

  setActiveSession: (id) => set({ activeSessionId: id }),

  addMessage: (sessionId, message) => set((state) => {
    const session = state.sessions.get(sessionId);
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
    
    const newSessions = new Map(state.sessions);
    newSessions.set(sessionId, newSession);
    return { sessions: newSessions };
  }),

  updateMessage: (sessionId, messageId, updates) => set((state) => {
    const session = state.sessions.get(sessionId);
    if (!session) return state;
    
    const newMessages = session.messages.map(m => 
      m.id === messageId ? { ...m, ...updates } : m
    );
    
    const newSession = { ...session, messages: newMessages };
    const newSessions = new Map(state.sessions);
    newSessions.set(sessionId, newSession);
    return { sessions: newSessions };
  }),

  setSessionConfig: (sessionId, config) => set((state) => {
    const session = state.sessions.get(sessionId);
    if (!session) return state;
    
    const newSession = {
      ...session,
      config: { ...session.config, ...config }
    };
    
    const newSessions = new Map(state.sessions);
    newSessions.set(sessionId, newSession);
    return { sessions: newSessions };
  }),

  updateRagProcess: (sessionId, messageId, steps) => set((state) => {
    const session = state.sessions.get(sessionId);
    if (!session) return state;
    
    const newMessages = session.messages.map(m => 
      m.id === messageId ? { ...m, ragProcess: steps } : m
    );
    
    const newSession = { ...session, messages: newMessages };
    const newSessions = new Map(state.sessions);
    newSessions.set(sessionId, newSession);
    return { sessions: newSessions };
  }),

  setStreaming: (messageId) => set({ 
    streamingMessageId: messageId,
    isLoading: messageId !== null 
  }),

  appendMessageContent: (sessionId, messageId, content) => set((state) => {
    const session = state.sessions.get(sessionId);
    if (!session) return state;
    
    const newMessages = session.messages.map(m => 
      m.id === messageId 
        ? { ...m, content: m.content + content } 
        : m
    );
    
    const newSession = { ...session, messages: newMessages };
    const newSessions = new Map(state.sessions);
    newSessions.set(sessionId, newSession);
    return { sessions: newSessions };
  }),

  getActiveSession: () => {
    const { activeSessionId, sessions } = get();
    return activeSessionId ? sessions.get(activeSessionId) : undefined;
  },

  getSessionMessages: (sessionId) => {
    const session = get().sessions.get(sessionId);
    return session?.messages || [];
  }
}));

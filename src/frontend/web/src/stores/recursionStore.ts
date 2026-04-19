/**
 * Zustand Store
 * 管理递归会话状态
 */

import { create } from 'zustand';
import {
  RecursionSession,
  DashboardEvent,
  RecursionState
} from '@rag/shared';

interface RecursionStore {
  // 所有会话
  sessions: Map<string, RecursionSession>;
  
  // 当前活跃的会话ID
  activeSessionId: string | null;
  
  // 事件日志
  eventLog: DashboardEvent[];
  
  // 状态流历史 (用于可视化)
  stateHistory: { timestamp: number; state: RecursionState; sessionId: string }[];
  
  // Actions
  setActiveSession: (id: string | null) => void;
  updateSession: (session: RecursionSession) => void;
  addEvent: (event: DashboardEvent) => void;
  getSession: (id: string) => RecursionSession | undefined;
  getActiveSession: () => RecursionSession | undefined;
}

export const useRecursionStore = create<RecursionStore>((set, get) => ({
  sessions: new Map(),
  activeSessionId: null,
  eventLog: [],
  stateHistory: [],

  setActiveSession: (id) => set({ activeSessionId: id }),

  updateSession: (session) => set((state) => {
    const newSessions = new Map(state.sessions);
    newSessions.set(session.id, session);
    return { sessions: newSessions };
  }),

  addEvent: (event) => set((state) => {
    // 添加到事件日志
    const newEventLog = [event, ...state.eventLog].slice(0, 1000); // 保留最近1000条
    
    // 如果是状态变更，添加到历史
    const newStateHistory = [...state.stateHistory];
    if (event.type === 'state_change' || event.type === 'recursion_round_start') {
      const session = state.sessions.get(event.sessionId);
      if (session) {
        newStateHistory.push({
          timestamp: event.timestamp,
          state: session.currentState,
          sessionId: event.sessionId
        });
      }
    }
    
    return { 
      eventLog: newEventLog,
      stateHistory: newStateHistory.slice(-100) // 保留最近100个状态
    };
  }),

  getSession: (id) => get().sessions.get(id),
  
  getActiveSession: () => {
    const { activeSessionId, sessions } = get();
    return activeSessionId ? sessions.get(activeSessionId) : undefined;
  }
}));

/**
 * 系统性能状态管理
 */

import { create } from 'zustand';
import { SystemPerformance } from '@rag/shared';

interface SystemState {
  performance: SystemPerformance | null;
  uptime: number;
  version: string;
  
  // Actions
  setPerformance: (perf: SystemPerformance) => void;
  updateUptime: () => void;
  
  // Getters
  getAvgLatency: () => number;
  getThroughputStatus: () => 'good' | 'warning' | 'critical';
}

export const useSystemStore = create<SystemState>((set, get) => ({
  performance: null,
  uptime: 0,
  version: '0.1.0',

  setPerformance: (perf) => set({ performance: perf }),
  
  updateUptime: () => set((state) => ({ 
    uptime: state.uptime + 1 
  })),

  getAvgLatency: () => {
    const perf = get().performance;
    if (!perf) return 0;
    return perf.latency.total;
  },
  
  getThroughputStatus: () => {
    const perf = get().performance;
    if (!perf) return 'good';
    if (perf.queues.queryQueue > 100) return 'critical';
    if (perf.queues.queryQueue > 50) return 'warning';
    return 'good';
  }
}));

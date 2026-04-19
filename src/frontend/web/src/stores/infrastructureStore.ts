/**
 * 基础设施状态管理
 * 管理 LLM、数据库、服务、管道等组件状态
 */

import { create } from 'zustand';
import {
  LLMProvider,
  VectorDB,
  GraphDB,
  KnowledgeBase,
  EmbeddingService,
  RerankService,
  DataPipeline,
  RetrievalEngine,
  DataConsistency,
  InfrastructureOverview,
  Alert
} from '@rag/shared';

interface InfrastructureState {
  // 数据
  llmProviders: LLMProvider[];
  vectorDBs: VectorDB[];
  graphDBs: GraphDB[];
  knowledgeBases: KnowledgeBase[];
  embeddingServices: EmbeddingService[];
  rerankServices: RerankService[];
  dataPipelines: DataPipeline[];
  retrievalEngines: RetrievalEngine[];
  dataConsistency: DataConsistency | null;
  overview: InfrastructureOverview | null;
  alerts: Alert[];
  
  // Actions
  setLLMProviders: (providers: LLMProvider[]) => void;
  setVectorDBs: (dbs: VectorDB[]) => void;
  setGraphDBs: (dbs: GraphDB[]) => void;
  setKnowledgeBases: (kbs: KnowledgeBase[]) => void;
  setEmbeddingServices: (services: EmbeddingService[]) => void;
  setRerankServices: (services: RerankService[]) => void;
  setDataPipelines: (pipelines: DataPipeline[]) => void;
  setRetrievalEngines: (engines: RetrievalEngine[]) => void;
  setDataConsistency: (consistency: DataConsistency) => void;
  setOverview: (overview: InfrastructureOverview) => void;
  setAlerts: (alerts: Alert[]) => void;
  addAlert: (alert: Alert) => void;
  acknowledgeAlert: (id: string) => void;
  resolveAlert: (id: string) => void;
  
  // Getters
  getHealthyCount: () => number;
  getCriticalAlerts: () => Alert[];
}

export const useInfrastructureStore = create<InfrastructureState>((set, get) => ({
  // 初始状态
  llmProviders: [],
  vectorDBs: [],
  graphDBs: [],
  knowledgeBases: [],
  embeddingServices: [],
  rerankServices: [],
  dataPipelines: [],
  retrievalEngines: [],
  dataConsistency: null,
  overview: null,
  alerts: [],

  // Actions
  setLLMProviders: (providers) => set({ llmProviders: providers }),
  setVectorDBs: (dbs) => set({ vectorDBs: dbs }),
  setGraphDBs: (dbs) => set({ graphDBs: dbs }),
  setKnowledgeBases: (kbs) => set({ knowledgeBases: kbs }),
  setEmbeddingServices: (services) => set({ embeddingServices: services }),
  setRerankServices: (services) => set({ rerankServices: services }),
  setDataPipelines: (pipelines) => set({ dataPipelines: pipelines }),
  setRetrievalEngines: (engines) => set({ retrievalEngines: engines }),
  setDataConsistency: (consistency) => set({ dataConsistency: consistency }),
  setOverview: (overview) => set({ overview }),
  setAlerts: (alerts) => set({ alerts }),
  
  addAlert: (alert) => set((state) => ({
    alerts: [alert, ...state.alerts].slice(0, 100)
  })),
  
  acknowledgeAlert: (id) => set((state) => ({
    alerts: state.alerts.map(a => 
      a.id === id ? { ...a, acknowledged: true } : a
    )
  })),
  
  resolveAlert: (id) => set((state) => ({
    alerts: state.alerts.map(a => 
      a.id === id ? { ...a, resolved: true, resolvedAt: Date.now() } : a
    )
  })),

  // Getters
  getHealthyCount: () => {
    const state = get();
    let count = 0;
    state.llmProviders.forEach(p => { if (p.status === 'healthy') count++; });
    state.vectorDBs.forEach(d => { if (d.status === 'connected') count++; });
    state.graphDBs.forEach(d => { if (d.status === 'connected') count++; });
    return count;
  },
  
  getCriticalAlerts: () => {
    return get().alerts.filter(a => a.level === 'critical' && !a.resolved);
  }
}));

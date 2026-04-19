/**
 * 基础设施状态类型定义
 * 包含 LLM、数据库、服务、数据管道等全链路组件
 */

// ==================== LLM 提供者 ====================

export type InfrastructureProviderType = 'kimi' | 'openai' | 'azure' | 'anthropic' | 'deepseek' | 'llama.cpp' | 'vllm' | 'local' | 'custom';

export type ServiceStatus = 'healthy' | 'degraded' | 'down' | 'unknown';

export interface LLMProvider {
  id: string;
  name: string;
  type: InfrastructureProviderType;
  status: ServiceStatus;
  baseUrl?: string;
  model: string;
  modelVersion: string;
  contextWindow: number;
  // 性能指标
  latency: {
    p50: number;  // ms
    p95: number;
    p99: number;
  };
  queueLength: number;
  tokenThroughput: number;  // tokens/sec
  requestSuccessRate: number;  // 0-1
  // 成本
  costPer1KTokens?: number;
  totalTokensConsumed: number;
  // 元数据
  lastUsed: number;
  capabilities: string[];  // ['chat', 'embedding', 'rerank']
}

export interface ModelLoadMetrics {
  provider: string;
  model: string;
  // GPU 状态
  gpuUsage: number;  // 0-100
  vramUsed: number;  // MB
  vramTotal: number;
  // 模型加载状态
  loadProgress: number;  // 0-100
  status: 'loading' | 'ready' | 'unloading' | 'error';
  // 批处理
  batchSize: number;
  maxBatchSize: number;
}

// ==================== 向量数据库 ====================

export type VectorDBType = 'qdrant' | 'milvus' | 'weaviate' | 'pgvector' | 'chroma';

export interface VectorDB {
  id: string;
  name: string;
  type: VectorDBType;
  status: 'connected' | 'disconnected' | 'degraded';
  version: string;
  // 数据量
  collections: number;
  vectorCount: number;
  storageSize: number;  // MB
  // 性能
  queryLatency: {
    p50: number;
    p95: number;
    p99: number;
  };
  throughput: number;  // queries/sec
  // 索引
  indexStatus: 'ready' | 'building' | 'optimizing' | 'error';
  indexProgress?: number;  // 0-100
  // 连接信息
  host: string;
  port: number;
  lastConnected: number;
}

export interface VectorCollection {
  id: string;
  name: string;
  dbId: string;
  vectorSize: number;
  distance: 'cosine' | 'euclidean' | 'dot';
  vectorCount: number;
  indexedCount: number;
  storageSize: number;
  // 统计
  avgVectorSize: number;
  lastOptimized: number;
}

// ==================== 图数据库 ====================

export type GraphDBType = 'neo4j' | 'nebula' | 'janusgraph' | 'dgraph';

export interface GraphDB {
  id: string;
  name: string;
  type: GraphDBType;
  status: 'connected' | 'disconnected';
  version: string;
  // 数据规模
  nodeCount: number;
  edgeCount: number;
  labelTypes: number;
  relationTypes: number;
  // 性能
  queryLatency: number;
  throughput: number;
  // 维护
  lastBackup: number;
  backupStatus: 'success' | 'failed' | 'in_progress';
  // 连接
  host: string;
  port: number;
}

// ==================== 知识库/文档存储 ====================

export interface KnowledgeBase {
  id: string;
  name: string;
  type: 'postgres' | 'mysql' | 'mongodb' | 'elasticsearch';
  status: ServiceStatus;
  // 数据量
  documentCount: number;
  chunkCount: number;
  storageSize: number;
  // 索引
  indexSize: number;
  lastIndexed: number;
  // 性能
  queryLatency: number;
  indexLag: number;  // 索引延迟秒数
}

// ==================== Embedding 服务 ====================

export interface EmbeddingService {
  id: string;
  model: string;
  provider: string;
  dimensions: number;
  status: ServiceStatus;
  // 性能
  batchSize: number;
  maxBatchSize: number;
  throughput: number;  // vectors/sec
  latency: number;  // ms per batch
  // 缓存
  cacheEnabled: boolean;
  cacheHitRate: number;  // 0-1
  cacheSize: number;  // MB
  // 资源
  memoryUsage: number;  // MB
  cpuUsage: number;  // 0-100
}

// ==================== Rerank 服务 ====================

export interface RerankService {
  id: string;
  model: string;
  provider: string;
  status: ServiceStatus;
  // 性能
  maxCandidates: number;
  latency: number;  // ms
  throughput: number;  // docs/sec
  // 效果
  avgScore: number;
  scoreDistribution: {
    high: number;  // >0.8
    medium: number;  // 0.5-0.8
    low: number;  // <0.5
  };
}

// ==================== 数据处理管道 ====================

export type PipelineStage = 
  | 'upload' 
  | 'ocr' 
  | 'layout' 
  | 'clean' 
  | 'chunk' 
  | 'embed' 
  | 'index' 
  | 'review';

export interface DataPipeline {
  id: string;
  name: string;
  status: 'running' | 'paused' | 'error';
  // 队列
  queueLength: number;
  processingRate: number;  // docs/min
  // OCR
  ocrAccuracy: number;  // 0-1
  ocrModel: string;
  supportedLanguages: string[];
  // 审核
  pendingReview: number;
  reviewPassRate: number;
  // 统计
  totalProcessed: number;
  totalFailed: number;
  avgProcessingTime: number;  // seconds
}

export interface PipelineStageStatus {
  stage: PipelineStage;
  status: 'idle' | 'processing' | 'error';
  queueLength: number;
  processingRate: number;
  errorCount: number;
  avgLatency: number;
}

// ==================== 检索引擎 ====================

export interface RetrievalEngine {
  id: string;
  name: string;
  status: ServiceStatus;
  // 查询统计
  totalQueries: number;
  avgQueryTime: number;
  cacheHitRate: number;
  // 召回
  avgRecallCount: number;
  recallLatency: number;
  // 精排
  rerankLatency: number;
  // 策略
  strategy: string;
  topK: number;
  rerankTopK: number;
}

// ==================== 四库一致性 ====================

export interface DataConsistency {
  // 跨库同步状态
  vectorToKnowledgeLag: number;  // seconds
  knowledgeToGraphLag: number;
  // 一致性检查
  lastCheckTime: number;
  inconsistenciesFound: number;
  // 同步状态
  syncStatus: 'synced' | 'syncing' | 'lagging' | 'error';
  syncProgress?: number;
}

// ==================== 系统整体状态 ====================

export interface InfrastructureOverview {
  // 汇总状态
  overallHealth: 'healthy' | 'degraded' | 'critical';
  healthyComponents: number;
  totalComponents: number;
  // 告警
  activeAlerts: number;
  criticalAlerts: number;
  // 各层状态
  llmStatus: ServiceStatus;
  retrievalStatus: ServiceStatus;
  storageStatus: ServiceStatus;
  pipelineStatus: ServiceStatus;
  // 时间戳
  lastUpdated: number;
}

// ==================== 告警 ====================

export type AlertLevel = 'info' | 'warning' | 'critical';

export type AlertCategory = 
  | 'llm' 
  | 'retrieval' 
  | 'storage' 
  | 'pipeline' 
  | 'performance' 
  | 'availability';

export interface Alert {
  id: string;
  level: AlertLevel;
  category: AlertCategory;
  component: string;
  title: string;
  message: string;
  timestamp: number;
  acknowledged: boolean;
  resolved: boolean;
  resolvedAt?: number;
  metadata?: Record<string, any>;
}

// ==================== 系统性能 ====================

export interface SystemPerformance {
  // 延迟分解
  latency: {
    decomposition: number;  // 查询拆解
    retrieval: number;      // 召回
    reranking: number;      // 精排
    generation: number;     // 生成
    evaluation: number;     // 评估
    total: number;          // 端到端
  };
  // 吞吐量
  throughput: {
    queriesPerSecond: number;
    tokensPerSecond: number;
    vectorsPerSecond: number;
  };
  // 资源使用
  resources: {
    cpuUsage: number;      // 0-100
    memoryUsage: number;   // MB
    diskUsage: number;     // MB
    networkIO: number;     // MB/s
  };
  // 队列
  queues: {
    queryQueue: number;
    embeddingQueue: number;
    indexQueue: number;
  };
  // 缓存
  cache: {
    queryCacheHitRate: number;
    embeddingCacheHitRate: number;
    resultCacheHitRate: number;
  };
}

/**
 * Pipeline 组件共享类型
 * 提取自 DataPipelineDashboard.tsx，用于消除循环依赖
 */

export interface UploadFile {
  id: string;
  file: File;
  name: string;
  size: number;
  status: 'pending' | 'uploading' | 'processing' | 'completed' | 'failed';
  progress: number;
  stage?: string;
  result?: any;
  error?: string;
  startTime: number;
  endTime?: number;
}

export interface PipelineStats {
  totalFiles: number;
  completedFiles: number;
  failedFiles: number;
  processingFiles: number;
  averageProcessingTime: number;
  queueLength: number;
  throughput: number;
}

export interface DatabaseHealth {
  vector: { status: 'healthy' | 'degraded' | 'down'; latency: number; count: number };
  keyword: { status: 'healthy' | 'degraded' | 'down'; latency: number; count: number };
  graph: { status: 'healthy' | 'degraded' | 'down'; latency: number; count: number };
  cache: { status: 'healthy' | 'degraded' | 'down'; latency: number; count: number };
}

export interface EvaluationMetrics {
  embedding: {
    averageTime: number;
    successRate: number;
    queueSize: number;
    batchSize: number;
  };
  rerank: {
    averageTime: number;
    successRate: number;
    crossEncoderLatency: number;
    fusionScoreAccuracy: number;
  };
}

/**
 * RAG Backend API 服务
 * 连接统一检索后端
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export interface SearchResult {
  chunk_id: string;
  doc_id: string;
  content: string;
  score: number;
  metadata: {
    vector_score: number;
    keyword_score: number;
    rerank_score: number;
    page_number?: number;
    section?: string;
  };
}

export interface SearchResponse {
  status?: string;
  data?: {
    request_id: string;
    query: string;
    results: SearchResult[];
    latency_ms: number;
    stats: Record<string, any>;
  };
  query?: string;
  results?: SearchResult[];
  total_candidates?: number;
  processing_time?: number;
  search_stats?: Record<string, any>;
}

export interface HealthStatus {
  status: string;
  services: {
    vector: string;
    keyword: string;
    graph: string;
    cache: string;
  };
  timestamp: string;
}

export interface PipelineHealth {
  status: string;
  services: {
    vector: { status: string; latency: number; count: number };
    keyword: { status: string; latency: number; count: number };
    graph: { status: string; latency: number; count: number };
    cache: { status: string; latency: number; count: number };
  };
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

export interface EvaluationResult {
  completeness: number;
  consistency: number;
  confidence: number;
  information_gain: number;
  source_diversity: number;
  fact_consistency: number;
  coverage_estimate: number;
}

export interface DecomposeResult {
  sub_queries: Array<{
    id: string;
    query: string;
    targetDB: string;
    status: string;
  }>;
  original_query: string;
}

/**
 * 搜索文档
 */
export async function searchDocuments(
  query: string,
  options: {
    topK?: number;
    mode?: 'vector' | 'keyword' | 'graph' | 'hybrid';
    filters?: Record<string, any>;
  } = {}
): Promise<SearchResult[]> {
  try {
    const response = await fetch(`${API_BASE}/api/search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        query,
        top_k: options.topK || 10,
        mode: options.mode || 'hybrid',
        filters: options.filters || {}
      })
    });

    if (!response.ok) {
      throw new Error(`Search failed: ${response.status}`);
    }

    const result: SearchResponse = await response.json();

    const results = result.data?.results || result.results || [];

    return results.map((item: any) => ({
      chunk_id: item.chunk_id || item.id || `chunk-${crypto.randomUUID()}`,
      doc_id: item.doc_id || item.source || 'unknown',
      content: item.content,
      score: item.score || 0,
      metadata: {
        vector_score: item.metadata?.vector_score || item.score || 0,
        keyword_score: item.metadata?.keyword_score || 0,
        rerank_score: item.metadata?.rerank_score || item.score || 0,
        page_number: item.metadata?.page_number,
        section: item.metadata?.section
      }
    }));
  } catch (error) {
    console.error('Search error:', error);
    return [];
  }
}

/**
 * v1搜索文档
 */
export async function searchDocumentsV1(
  query: string,
  options: {
    topK?: number;
    filters?: Record<string, any>;
  } = {}
): Promise<SearchResult[]> {
  try {
    const response = await fetch(`${API_BASE}/api/v1/search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        query,
        top_k: options.topK || 10,
        filters: options.filters || {}
      })
    });

    if (!response.ok) {
      throw new Error(`Search failed: ${response.status}`);
    }

    const result: SearchResponse = await response.json();

    const results = result.data?.results || result.results || [];

    return results.map((item: any) => ({
      chunk_id: item.chunk_id || item.id || `chunk-${crypto.randomUUID()}`,
      doc_id: item.doc_id || item.source || 'unknown',
      content: item.content,
      score: item.score || 0,
      metadata: {
        vector_score: item.metadata?.vector_score || item.score || 0,
        keyword_score: item.metadata?.keyword_score || 0,
        rerank_score: item.metadata?.rerank_score || item.score || 0,
        page_number: item.metadata?.page_number,
        section: item.metadata?.section
      }
    }));
  } catch (error) {
    console.error('Search error:', error);
    return [];
  }
}

/**
 * 检查后端健康状态
 * 适配多种后端格式：Python Legacy / Go Gateway
 */
export async function checkHealth(): Promise<HealthStatus> {
  try {
    const response = await fetch(`${API_BASE}/health`);
    if (!response.ok) {
      throw new Error('Health check failed');
    }
    const result = await response.json();

    // Python Legacy 格式：{ services: { qdrant, elasticsearch, neo4j, redis } }
    if (result.services?.qdrant !== undefined || result.services?.vector_store !== undefined) {
      return {
        status: result.status || 'unknown',
        services: {
          vector: result.services?.qdrant || result.services?.vector_store || 'unknown',
          keyword: result.services?.elasticsearch || result.services?.keyword_store || 'unknown',
          graph: result.services?.neo4j || result.services?.graph_store || 'unknown',
          cache: result.services?.redis || 'healthy'
        },
        timestamp: result.timestamp || new Date().toISOString()
      };
    }

    // Go Gateway 格式：{ services: { nodejs, python, ocr, retrieval, llm, websocket } }
    // 映射到基础设施维度
    const svc = result.services || {};
    return {
      status: result.status || 'unknown',
      services: {
        vector: svc.retrieval || svc.qdrant || 'unknown',
        keyword: svc.python || svc.elasticsearch || 'unknown',
        graph: svc.python || svc.neo4j || 'unknown',
        cache: svc.nodejs || svc.redis || 'unknown'
      },
      timestamp: result.timestamp || new Date().toISOString()
    };
  } catch (error) {
    console.error('Health check error:', error);
    return {
      status: 'error',
      services: {
        vector: 'unknown',
        keyword: 'unknown',
        graph: 'unknown',
        cache: 'unknown'
      },
      timestamp: new Date().toISOString()
    };
  }
}

/**
 * 检查管道健康状态
 */
export async function checkPipelineHealth(): Promise<PipelineHealth> {
  try {
    const response = await fetch(`${API_BASE}/api/pipeline/health`);
    if (!response.ok) {
      throw new Error('Pipeline health check failed');
    }
    const result = await response.json();
    return result.data || result;
  } catch (error) {
    console.error('Pipeline health check error:', error);
    return {
      status: 'error',
      services: {
        vector: { status: 'unknown', latency: 0, count: 0 },
        keyword: { status: 'unknown', latency: 0, count: 0 },
        graph: { status: 'unknown', latency: 0, count: 0 },
        cache: { status: 'unknown', latency: 0, count: 0 }
      }
    };
  }
}

/**
 * 获取管道统计
 */
export async function getPipelineStats(): Promise<PipelineStats> {
  try {
    const response = await fetch(`${API_BASE}/api/pipeline/stats`);
    if (!response.ok) {
      throw new Error('Failed to get pipeline stats');
    }
    const result = await response.json();
    return result.data || result;
  } catch (error) {
    console.error('Pipeline stats error:', error);
    return {
      totalFiles: 0,
      completedFiles: 0,
      failedFiles: 0,
      processingFiles: 0,
      averageProcessingTime: 0,
      queueLength: 0,
      throughput: 0
    };
  }
}

/**
 * 获取评估指标
 */
export async function getEvaluation(): Promise<EvaluationResult> {
  try {
    const response = await fetch(`${API_BASE}/api/pipeline/evaluation`);
    if (!response.ok) {
      throw new Error('Failed to get evaluation');
    }
    const result = await response.json();
    return result.data || result;
  } catch (error) {
    console.error('Evaluation error:', error);
    return {
      completeness: 0,
      consistency: 0,
      confidence: 0,
      information_gain: 0,
      source_diversity: 0,
      fact_consistency: 0,
      coverage_estimate: 0
    };
  }
}

/**
 * 查询分解
 */
export async function decomposeQuery(query: string): Promise<DecomposeResult> {
  try {
    const response = await fetch(`${API_BASE}/api/v1/decompose`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ query })
    });

    if (!response.ok) {
      throw new Error(`Decompose failed: ${response.status}`);
    }

    const result = await response.json();
    return result.data || result;
  } catch (error) {
    console.error('Decompose error:', error);
    return {
      sub_queries: [{
        id: `sq_${Date.now()}`,
        query: `${query} 基础概念`,
        targetDB: 'vector',
        status: 'pending'
      }],
      original_query: query
    };
  }
}

/**
 * 上传文档
 */
export async function uploadDocument(
  file: File,
  _onProgress?: (progress: number) => void
): Promise<{ doc_id: string; status: string; message?: string }> {
  try {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('title', file.name);

    const response = await fetch(`${API_BASE}/api/pipeline/upload`, {
      method: 'POST',
      body: formData
    });

    if (!response.ok) {
      throw new Error(`Upload failed: ${response.status}`);
    }

    const result = await response.json();
    return result.data || result;
  } catch (error) {
    console.error('Upload error:', error);
    return {
      doc_id: `doc-${Date.now()}`,
      status: 'error',
      message: error instanceof Error ? error.message : 'Upload failed'
    };
  }
}

/**
 * 获取系统统计
 */
export async function getStats(): Promise<any> {
  try {
    const response = await fetch(`${API_BASE}/api/stats`);
    if (!response.ok) {
      throw new Error('Failed to get stats');
    }
    const result = await response.json();
    return result.data || result;
  } catch (error) {
    console.error('Stats error:', error);
    return {};
  }
}

/**
 * WebSocket 连接
 */
export function createWebSocketConnection(): WebSocket {
  const wsUrl = import.meta.env.VITE_WS_URL || `ws://${window.location.host}/ws?room=dashboard`;
  const ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log('WebSocket connected');
  };

  ws.onerror = (error) => {
    console.error('WebSocket error:', error);
  };

  return ws;
}

// 默认导出
export default {
  searchDocuments,
  searchDocumentsV1,
  checkHealth,
  checkPipelineHealth,
  getPipelineStats,
  getEvaluation,
  decomposeQuery,
  uploadDocument,
  getStats,
  createWebSocketConnection
};
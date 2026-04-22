/**
 * RAG Agent API — 对接 retrieval-service /api/v1/agent
 * 唯一的问答 API 入口
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export interface AgentChunk {
  chunk_id: string;
  doc_id: string;
  content: string;
  score: number;
  source?: string;
  metadata?: Record<string, any>;
}

export interface AgentEvaluation {
  passed: boolean;
  confidence: number;
  completeness?: number;
  consistency?: number;
}

export interface AgentToolCall {
  tool: string;
  args: Record<string, any>;
  result_summary?: string;
}

export interface AgentResponse {
  session_id: string;
  query: string;
  answer: string;
  chunks: AgentChunk[];
  evaluation: AgentEvaluation;
  iterations: number;
  tool_calls?: AgentToolCall[];
  error?: string;
}

export interface HealthResponse {
  status: string;
  services: Record<string, string>;
  timestamp: string;
}

/**
 * 发送问答请求到 RAG Agent
 */
export async function askAgent(
  query: string,
  options?: { maxIterations?: number; sessionId?: string }
): Promise<AgentResponse> {
  const response = await fetch(`${API_BASE}/api/v1/agent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      max_iterations: options?.maxIterations ?? 3,
      session_id: options?.sessionId,
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Agent API 错误: ${response.status} - ${text}`);
  }

  return response.json();
}

/**
 * 检查后端健康状态
 */
export async function checkHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) throw new Error('Health check failed');
  return response.json();
}

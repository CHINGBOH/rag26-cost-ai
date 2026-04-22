/**
 * Metrics API — ops dashboard endpoints
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export interface ServiceHealth {
  status: 'healthy' | 'degraded' | 'unhealthy';
  latency_ms: number;
}

export interface HealthDetailResponse {
  services: Record<string, ServiceHealth>;
  timestamp: string;
}

export interface LlmMetricsResponse {
  status: string;
  raw?: string;
  message?: string;
}

export async function getHealthDetail(): Promise<HealthDetailResponse> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/health/detail`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  } catch {
    return { services: {}, timestamp: new Date().toISOString() };
  }
}

export async function getLlmMetrics(): Promise<LlmMetricsResponse> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/metrics/llm`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  } catch (e) {
    return { status: 'error', message: e instanceof Error ? e.message : 'unknown' };
  }
}

export async function submitFeedback(data: {
  session_id: string;
  message_id: string;
  rating: number;
  comment?: string;
  query?: string;
  answer_summary?: string;
}): Promise<{ status: string; message_id: string }> {
  const res = await fetch(`${API_BASE}/api/v1/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Feedback API error: ${res.status}`);
  return res.json();
}

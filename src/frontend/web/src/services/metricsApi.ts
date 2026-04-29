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

// ── Ops Metrics ──────────────────────────────────────────────────────────────

export interface OpsMetricsResponse {
  window_sec: number;
  requests: number;
  qps: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  error_rate: number;
  by_status: Record<string, number>;
  top_paths: Array<{ path: string; count: number }>;
  qps_buckets: number[];
  total_recorded?: number;
}

export async function getOpsMetrics(windowSec = 60): Promise<OpsMetricsResponse | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/ops/metrics?window_sec=${windowSec}`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

// ── Learning ─────────────────────────────────────────────────────────────────

export interface LearningRun {
  ts: string;
  query: string;
  query_type: string;
  answer: string;
  iterations: number;
  chunks_count: number;
  tools_used: string[];
  evaluation: {
    confidence: number;
    information_gain: number;
    completeness: number;
    consistency: number;
  };
  quality: 'good' | 'weak' | 'failure' | string;
  refused: boolean;
  runtime: { provider?: string; model?: string };
}

export interface LearningSummary {
  total_runs: number;
  by_quality: Record<string, number>;
  refused_count: number;
  avg_confidence: number;
  tool_frequency: Record<string, number>;
  type_frequency: Record<string, number>;
  feedback: { positive: number; negative: number; total: number };
}

export interface LearningGap {
  query: string;
  ts: string;
  quality: string;
  refused: boolean;
  chunks_count: number;
  confidence: number;
  answer_preview: string;
}

export async function getLearningSummary(): Promise<LearningSummary | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/learning/summary`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function getLearningRuns(limit = 50, quality?: string): Promise<LearningRun[]> {
  try {
    const q = new URLSearchParams({ limit: String(limit) });
    if (quality) q.set('quality', quality);
    const res = await fetch(`${API_BASE}/api/v1/learning/runs?${q}`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.runs || [];
  } catch {
    return [];
  }
}

export async function getLearningGaps(limit = 30): Promise<LearningGap[]> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/learning/gaps?limit=${limit}`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.gaps || [];
  } catch {
    return [];
  }
}

// ── System ───────────────────────────────────────────────────────────────────

export interface SystemVersion {
  git_sha: string;
  git_branch: string;
  python_version: string;
  platform: string;
  service_start_ts: number;
}

export interface SystemConfig {
  llm: { provider: string; model: string; route?: string; base_url?: string; max_tokens?: number; temperature?: number };
  embedding: { model: string; backend?: string; dim?: number };
  retrieval: { default_top_k?: number; score_threshold?: number; max_iterations?: number; rrf_k?: number };
  stores: Record<string, string>;
}

export interface SystemKb {
  chunks_total: number | null;
  documents_total: number | null;
  concepts_total: number | null;
  relations_total: number | null;
  price_records_total: number | null;
  chunks_by_source: Array<{ source: string; count: number }>;
  latest_chunk_ts: string | null;
  error?: string;
}

export async function getSystemVersion(): Promise<SystemVersion | null> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/system/version`);
    return r.ok ? r.json() : null;
  } catch { return null; }
}
export async function getSystemConfig(): Promise<SystemConfig | null> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/system/config`);
    return r.ok ? r.json() : null;
  } catch { return null; }
}
export async function getSystemKb(): Promise<SystemKb | null> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/system/kb`);
    return r.ok ? r.json() : null;
  } catch { return null; }
}

// ── Blind-spot clusters ──────────────────────────────────────────────────────

export interface BlindspotCluster {
  representative: string;
  size: number;
  members: Array<{ query: string; ts: string; quality: string; confidence: number }>;
  diagnosis: string;
}

export interface BlindspotResponse {
  clusters: BlindspotCluster[];
  total_bad: number;
  note?: string;
}

export async function getLearningBlindspots(minSize = 2): Promise<BlindspotResponse | null> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/learning/blindspots?min_size=${minSize}`);
    return r.ok ? r.json() : null;
  } catch { return null; }
}

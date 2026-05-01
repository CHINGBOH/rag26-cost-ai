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
  queries: string[];
  refused_count?: number;
  avg_chunks?: number;
  avg_confidence?: number;
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

// ── Agent traces (R9) ────────────────────────────────────────────────────────

export interface AgentTraceSummary {
  trace_id: string;
  query: string;
  started_ts: number;
  ended_ts?: number;
  duration_ms?: number;
  node_count: number;
  answer_preview?: string;
  query_type?: string;
  iterations?: number;
}

export interface AgentTraceNode {
  version: number;
  node: string;
  ts: number;
  latency_ms: number;
  iteration_at_entry?: number;
  delta_keys: string[];
  delta_summary: Record<string, unknown>;
  tool_calls: Array<{ tool: string; args?: unknown; status?: string; duration_ms?: number }>;
  error?: string;
}

export interface AgentTrace {
  trace_id: string;
  query: string;
  started_ts: number;
  ended_ts?: number;
  duration_ms?: number;
  nodes: AgentTraceNode[];
  query_type?: string;
  iterations?: number;
  answer_preview?: string;
}

export async function getAgentTraces(limit = 30): Promise<AgentTraceSummary[]> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/agent/traces?limit=${limit}`);
    if (!r.ok) return [];
    const d = await r.json();
    return d.traces || [];
  } catch { return []; }
}

export async function getAgentTrace(id: string): Promise<AgentTrace | null> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/agent/trace/${id}`);
    return r.ok ? r.json() : null;
  } catch { return null; }
}

// ── Pipeline jobs (R10) ──────────────────────────────────────────────────────

export interface PipelineJob {
  job_id: string;
  file_name: string;
  file_size?: number;
  status: 'queued' | 'ocr' | 'chunk' | 'embed' | 'ingest' | 'done' | 'failed';
  created_at?: string;
  updated_at?: string;
  duration_ms?: number;
  ocr_pages?: number;
  text_chars?: number;
  chunks_total?: number;
  chunks_inserted?: number;
  doc_id?: string;
  error?: string;
  ocr_unavailable?: boolean;
}

export async function pipelineUpload(file: File): Promise<{ ok: boolean; job_id?: string; error?: string }> {
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await fetch(`${API_BASE}/api/v1/pipeline/upload`, { method: 'POST', body: fd });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) return { ok: false, error: d.detail || `HTTP ${r.status}` };
    return { ok: true, job_id: d.job_id };
  } catch (e: any) {
    return { ok: false, error: e?.message || 'network error' };
  }
}

export async function getPipelineJobs(limit = 50): Promise<PipelineJob[]> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/pipeline/jobs?limit=${limit}`);
    if (!r.ok) return [];
    const d = await r.json();
    return d.jobs || [];
  } catch { return []; }
}

export async function getPipelineJob(id: string): Promise<PipelineJob | null> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/pipeline/job/${id}`);
    return r.ok ? r.json() : null;
  } catch { return null; }
}

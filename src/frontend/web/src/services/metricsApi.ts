/**
 * Metrics API — ops dashboard endpoints
 */

import { getApiBaseUrl } from '../config/runtime';

const API_BASE = getApiBaseUrl();

export interface ServiceHealth {
  status: 'healthy' | 'degraded' | 'unhealthy' | 'not_running';
  latency_ms: number;
  critical?: boolean;
  role?: string;
  status_code?: number;
  error?: string;
}

export interface HealthSummary {
  overall: 'ok' | 'degraded' | 'down';
  critical_total: number;
  critical_healthy: number;
}

export interface SystemMetrics {
  load_1m?: number;
  load_5m?: number;
  load_15m?: number;
  mem_total_mb?: number;
  mem_available_mb?: number;
  mem_used_pct?: number;
  cpu_count?: number;
}

export interface HealthDetailResponse {
  services: Record<string, ServiceHealth>;
  summary?: HealthSummary;
  system?: SystemMetrics;
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

export interface FeedbackDetail {
  session_id: string;
  message_id: string;
  rating: number;
  comment?: string;
  query?: string;
  answer_summary?: string;
  overall_rating?: number;
  rating_relevance?: number;
  rating_accuracy?: number;
  rating_completeness?: number;
  praise?: string;
  criticism?: string;
  suggestion?: string;
  tags?: string[];
}

export interface ConversationTurn {
  id: number;
  session_id: string;
  turn_index: number;
  user_content: string;
  assistant_content: string;
  source: string;
  status: string;
  latency_ms: number | null;
  ts: number | string;
}

export interface FeedbackRecord {
  ts: number | string;
  session_id: string;
  message_id: string;
  rating: number;
  overall_rating: number | null;
  rating_relevance: number | null;
  rating_accuracy: number | null;
  rating_completeness: number | null;
  praise: string | null;
  criticism: string | null;
  suggestion: string | null;
  tags: string[] | null;
  query: string | null;
  answer_summary: string | null;
}

export interface FeedbackStats {
  records: FeedbackRecord[];
  summary: {
    positive: number;
    negative: number;
    total: number;
    avg_overall_rating: number | null;
  };
  trend: Array<{ day: string; positive: number; total: number }>;
  error?: string;
}

export async function submitFeedback(data: FeedbackDetail): Promise<{ status: string; message_id: string }> {
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
  kind?: 'interaction' | 'learning_loop' | string;
  run_id?: string;
  session_id?: string;
  ts: number | string;
  query?: string;
  query_type?: string;
  answer?: string;
  iterations?: number;
  chunks_count?: number;
  tools_used?: string[];
  evaluation?: {
    confidence: number;
    information_gain: number;
    completeness: number;
    consistency: number;
  };
  quality: 'good' | 'weak' | 'failure' | string;
  refused?: boolean;
  runtime?: { provider?: string; model?: string };
  channel?: string;
  status?: string;
  outcome_family?: string;
  outcome_code?: string;
  learning_eligible?: boolean;
  early_exit?: boolean;
  request_id?: string;
  trace_id?: string;
  latency_ms?: number;
  run_type?: string;
  event_type?: string;
  signal_summary?: Record<string, number>;
  problems_count?: number;
  severity_score?: number;
  reason?: string;
  error?: string;
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
  gap_key?: string;
  problem_id?: string | null;
  query: string;
  ts: number | string;
  quality: string;
  status: string;
  refused: boolean;
  chunks_count: number;
  confidence: number;
  answer_preview: string;
  description?: string;
  source?: string;
  affected_route?: string | null;
  resolution_plan?: string | null;
  resolved_at?: number | string | null;
  verified_at?: number | string | null;
  observation_until?: number | string | null;
  last_reopened_at?: number | string | null;
  scope_type?: 'user' | 'agent' | 'project' | 'global' | string;
  scope_id?: string | null;
  cluster_id?: string | null;
  cause_type?: string | null;
  priority?: number;
  owner?: string | null;
  reopen_count?: number;
  linked_event_id?: number | null;
  first_seen_at?: number | string | null;
  last_seen_at?: number | string | null;
  frequency?: number;
  sample_queries?: string[];
  current_outcome_code?: string | null;
  current_decision?: string | null;
}

export interface LearningGapPresentation {
  quality: string;
  refused: boolean;
  chunks_count: number;
  confidence: number;
  badge: string;
  reason: string;
}

export interface LearningGapEvidence {
  id: number;
  gap_key: string;
  evidence_type: string;
  source_type?: string | null;
  actor: string;
  query: string;
  answer_preview?: string | null;
  quality?: string | null;
  outcome_code?: string | null;
  http_status?: number | null;
  chunks_count?: number | null;
  confidence?: number | null;
  refused?: boolean | null;
  generic_answer?: boolean | null;
  latency_ms?: number | null;
  run_id?: string | null;
  session_id?: string | null;
  recorded_at: number | string;
}

export interface LearningGapRepairTask {
  id: number;
  gap_key: string;
  task_type: string;
  status: string;
  actor: string;
  reason: string;
  latest_evidence_ids: number[];
  issue_number?: number | null;
  issue_url?: string | null;
  created_at: number | string;
  updated_at: number | string;
  resolved_at?: number | string | null;
}

export interface LearningGapWorkbenchItem {
  gap: LearningGap;
  bucket: 'active' | 'observing' | 'blocked' | 'resolved';
  allowed_actions: string[];
  latest_evidence?: LearningGapEvidence | null;
  repair_task?: LearningGapRepairTask | null;
  presentation?: LearningGapPresentation;
}

export interface LearningGapWorkbench {
  generated_at: string;
  counts: {
    total: number;
    active: number;
    observing: number;
    blocked: number;
    resolved: number;
    by_status: Record<string, number>;
  };
  buckets: Record<'active' | 'observing' | 'blocked' | 'resolved', LearningGapWorkbenchItem[]>;
  last_retest_run?: LearningRun | null;
}

export interface LearningDashboardAlert {
  severity: 'warning' | 'critical';
  message: string;
  created_at: number;
  acknowledged: boolean;
}

export interface LearningDashboardTrend {
  date: string;
  rate: number;
  problems: number;
  fixed: number;
}

export interface LearningDashboardEvent {
  timestamp: number | null;
  route: string;
  description: string;
  status: 'pending_review' | 'approved' | 'verified' | 'applied' | 'reverted' | 'rejected' | 'pending';
}

export interface ProjectionDriftProjection {
  drift_count: number;
  ledger_count?: number;
  projection_count?: number;
  missing_in_projection?: string[];
  stale_in_projection?: string[];
  mismatches?: Array<{ run_id: string; fields: string[] }>;
}

export interface LearningProjectionDriftSummary {
  run_id?: string | null;
  total_drift_count: number;
  drifted_projections: string[];
  projections: Record<string, ProjectionDriftProjection>;
}

export interface LearningProjectionReconcileSummary {
  run_id?: string | null;
  rebuilt_total: number;
  remaining_drift_count: number;
  projections: Record<string, { rebuilt: number; after?: { drift_count?: number } }>;
}

export interface LearningProjectionReconcileAuditSummary {
  run_id?: string | null;
  scope?: string | null;
  rebuilt_total: number;
  remaining_drift_count: number;
  occurred_at?: number | string;
}

export interface LearningDashboard {
  health: {
    status: 'good' | 'warning' | 'critical';
    score: number;
    last_check: number;
  };
  key_metrics: {
    last_run: number | null;
    next_run: number | null;
    running: boolean;
    pending_approvals: number;
  };
  improvement_trend: LearningDashboardTrend[];
  alerts: LearningDashboardAlert[];
  recent_events: LearningDashboardEvent[];
  projection_drift?: LearningProjectionDriftSummary;
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

export async function getLearningDashboard(): Promise<LearningDashboard | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/learning/dashboard`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function getLearningProjectionDrift(
  runId?: string,
): Promise<LearningProjectionDriftSummary | null> {
  try {
    const qs = runId ? `?run_id=${encodeURIComponent(runId)}` : '';
    const res = await fetch(`${API_BASE}/api/v1/learning/projections/drift${qs}`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function reconcileLearningProjections(
  runId?: string,
): Promise<LearningProjectionReconcileSummary | null> {
  try {
    const qs = runId ? `?run_id=${encodeURIComponent(runId)}` : '';
    const res = await fetch(`${API_BASE}/api/v1/learning/projections/reconcile${qs}`, {
      method: 'POST',
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function getLearningRuns(
  limit = 50,
  quality?: string,
  kind: 'interaction' | 'learning_loop' | 'all' = 'interaction',
): Promise<LearningRun[]> {
  try {
    const q = new URLSearchParams({ limit: String(limit), kind });
    if (quality) q.set('quality', quality);
    const res = await fetch(`${API_BASE}/api/v1/learning/runs?${q}`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.runs || [];
  } catch {
    return [];
  }
}

export async function getLearningGaps(
  limit = 30,
  options: { activeOnly?: boolean } = {},
): Promise<LearningGap[]> {
  try {
    const q = new URLSearchParams({ limit: String(limit) });
    if (options.activeOnly) q.set('active_only', 'true');
    const res = await fetch(`${API_BASE}/api/v1/learning/gaps?${q}`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.gaps || [];
  } catch {
    return [];
  }
}

export async function getLearningGapWorkbench(
  limit = 200,
  includeResolved = false,
): Promise<LearningGapWorkbench | null> {
  try {
    const q = new URLSearchParams({
      limit: String(limit),
      include_resolved: String(includeResolved),
    });
    const res = await fetch(`${API_BASE}/api/v1/learning/gaps/workbench?${q}`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
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

export interface ArchitectureStore {
  role?: string;
  available: boolean;
  version?: string;
  chunk_count?: number;
  collections?: string[];
  collection_count?: number;
  cluster_status?: string;
  nodes?: number;
  index?: string;
  index_exists?: boolean;
  extensions?: Record<string, boolean>;
  error?: string;
  [k: string]: unknown;
}

export interface ArchitectureLive {
  generated_at: string;
  stores: Record<string, ArchitectureStore>;
  summary?: { available?: number; total?: number };
}

export async function getArchitectureLive(): Promise<ArchitectureLive | null> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/architecture/live`);
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

// ── Learning Loop: conversations + feedback stats ─────────────────────────────

export async function getConversations(limit = 50, source?: string): Promise<ConversationTurn[]> {
  try {
    const qs = source ? `?limit=${limit}&source=${source}` : `?limit=${limit}`;
    const r = await fetch(`${API_BASE}/api/v1/learning/conversations${qs}`);
    if (!r.ok) return [];
    const d = await r.json();
    return d.turns || [];
  } catch { return []; }
}

export async function getFeedbackStats(limit = 100): Promise<FeedbackStats | null> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/learning/feedback-stats?limit=${limit}`);
    if (!r.ok) return null;
    return r.json();
  } catch { return null; }
}

export interface LearningEngineStatus {
  trigger_mode: string;
  trigger_description: string;
  trigger_conditions: Array<{ name: string; active: boolean; command?: string; note?: string }>;
  last_run: {
    ts?: number | string;
    file?: string;
    file_mtime?: string;
    summary?: { total?: number; passed?: number; ok?: number; avg_confidence?: number };
    result_count?: number;
    error?: string;
  };
  signals_24h: {
    weak_or_failed_runs: number;
    pending_negative_feedback_with_text: number;
  };
  projection_drift?: LearningProjectionDriftSummary | null;
  last_projection_reconcile?: LearningProjectionReconcileAuditSummary | null;
  next_actions: string[];
}

export async function getLearningEngine(): Promise<LearningEngineStatus | null> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/learning/engine`);
    if (!r.ok) return null;
    return r.json();
  } catch { return null; }
}

// ── Signal Collector Integration (Layer 1 + Layer 2) ──────────────────────────

export interface FeedbackSignal {
  session_id: string;
  message_id: string;
  rating: number;
  tags: string[];
  feedback_text: string;
  ts: number;
}

export interface FailureSignal {
  session_id: string;
  turn_index: number;
  status: string;
  latency_ms: number;
  context: Record<string, any>;
  ts: number;
}

export interface RepeatSignal {
  session_id: string;
  repeat_count: number;
  original_turn: number;
  latest_turn: number;
  similarity: number;
  ts: number;
}

export interface ViolationSignal {
  run_id: string;
  contract_name: string;
  violation_code: string;
  payload: Record<string, any>;
  ts: number;
}

export interface TopoSignal {
  edge_id: string;
  from_node: string;
  to_node: string;
  anomaly_type: string;
  last_traversed_at: string;
  traversal_count: number;
  ts: number;
}

export interface SignalAggregation {
  timestamp: number;
  feedback_signals: FeedbackSignal[];
  failure_signals: FailureSignal[];
  repeat_signals: RepeatSignal[];
  violation_signals: ViolationSignal[];
  topo_signals: TopoSignal[];
  total_count: number;
  severity_score: number;
  collection_time_ms: number;
}

export interface SignalSummary {
  last_collection: number;
  next_scheduled: number;
  signal_counts: {
    feedback: number;
    failures: number;
    repeats: number;
    violations: number;
    topo: number;
  };
  severity_trend: number[];
  health_status: 'good' | 'warning' | 'critical';
}

export async function getLatestSignals(limit = 100): Promise<SignalAggregation | null> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/learning/signals?limit=${limit}`);
    if (!r.ok) return null;
    return r.json();
  } catch { return null; }
}

export async function getSignalsSummary(): Promise<SignalSummary | null> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/learning/signals-summary`);
    if (!r.ok) return null;
    return r.json();
  } catch { return null; }
}

// ── Problem Analysis & Root Cause ────────────────────────────────────────────

export interface ProblemReport {
  problem_id: string;
  category: string;  // 'prompt_issue' | 'tool_failure' | 'routing_error' | 'low_quality' | 'diversity'
  severity: 'low' | 'medium' | 'high';
  affected_route: string;  // R1-R5
  description: string;
  evidence: string[];
  confidence: number;  // 0-1
  created_at: number;
  status: 'open' | 'analyzing' | 'pending_review';
}

export interface RootCauseAnalysis {
  problem_id: string;
  root_cause: string;
  confidence: number;
  evidence: Record<string, string[]>;
  suggested_fixes: RepairSuggestion[];
}

export interface RepairSuggestion {
  strategy_id: string;
  action_type: string;
  description: string;
  route: string;
  risk_level: 'low' | 'mid' | 'high';
  estimated_impact: number;
  decision: 'auto_apply' | 'pending_review' | 'manual_only';
}

export interface RepairStrategy {
  strategy_id: string;
  action_type: string;
  description: string;
  route: string;
  risk_level: 'low' | 'mid' | 'high';
  estimated_impact: number;
  decision: 'auto_apply' | 'pending_review' | 'manual_only';
}

export interface ImprovementEvent {
  event_id: number;
  timestamp: number;
  created_at?: number | null;
  applied_at?: number | null;
  verified_at?: number | null;
  problem_id: string;
  route: string;
  action: string;
  status: 'pending_review' | 'approved' | 'applied' | 'verified' | 'reverted' | 'failed' | 'rejected';
  before_rate: number;
  after_rate: number;
  delta: number;
  improvement_pct: number;
  execution_time: number;
  reverted_at?: number;
  revert_reason?: string;
  source?: {
    kind?: 'auto' | 'human' | 'external' | string;
    actor?: string | null;
    source_run_id?: string | null;
  };
  strategy?: {
    id?: string | null;
    type?: string | null;
    decision?: 'auto_apply' | 'pending_review' | 'manual_only' | string | null;
    risk_level?: 'low' | 'medium' | 'high' | string | null;
    estimated_impact?: string | null;
    root_cause_type?: string | null;
    reversible_by?: string | null;
  };
  review?: {
    status?: 'pending_review' | 'approved' | 'rejected' | string | null;
    reviewer?: string | null;
    note?: string | null;
    updated_at?: number | null;
  };
  verification?: {
    status?: 'pending' | 'applied' | 'verified' | 'failed' | string | null;
    success?: boolean | null;
    improved?: boolean | null;
    error?: string | null;
    failed_at?: number | null;
  };
  gap?: {
    gap_key?: string | null;
    status?: 'open' | 'in_progress' | 'observing' | 'resolved' | 'blocked' | string | null;
    owner?: string | null;
    scope_type?: 'user' | 'agent' | 'project' | 'global' | string | null;
    cluster_id?: string | null;
    verified_at?: number | null;
    observation_until?: number | null;
    last_reopened_at?: number | null;
    reopen_count?: number;
  } | null;
}

export async function getDetectedProblems(
  status?: string,
  limit: number = 50
): Promise<{ problems: ProblemReport[]; total: number; high_count: number; medium_count: number; low_count: number }> {
  try {
    const url = status ? `/api/v1/learning/problems?status=${status}&limit=${limit}` : `/api/v1/learning/problems?limit=${limit}`;
    const response = await fetch(`${API_BASE}${url}`);
    if (!response.ok) throw new Error('Failed to fetch problems');
    return response.json();
  } catch {
    return { problems: [], total: 0, high_count: 0, medium_count: 0, low_count: 0 };
  }
}

export async function analyzeRootCause(problemId: string): Promise<RootCauseAnalysis | null> {
  try {
    const response = await fetch(`${API_BASE}/api/v1/learning/analyze-problem?problem_id=${problemId}`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error('Failed to analyze problem');
    return response.json();
  } catch { return null; }
}

export async function getRepairStrategies(problemId: string): Promise<{ strategies: RepairStrategy[]; recommended: string; all_auto_apply: boolean }> {
  try {
    const response = await fetch(`${API_BASE}/api/v1/learning/strategies?problem_id=${problemId}`);
    if (!response.ok) throw new Error('Failed to get strategies');
    return response.json();
  } catch {
    return { strategies: [], recommended: '', all_auto_apply: false };
  }
}

export async function approveFix(eventId: number, comments?: string): Promise<{ event_id: number; status: string; message: string }> {
  try {
    const response = await fetch(`${API_BASE}/api/v1/learning/approve-fix`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_id: eventId, comments, approved_by: 'user' }),
    });
    if (!response.ok) throw new Error('Failed to approve fix');
    return response.json();
  } catch {
    return { event_id: eventId, status: 'error', message: 'Failed to approve' };
  }
}

export async function rejectFix(eventId: number, reason: string): Promise<{ event_id: number; status: string; reason: string }> {
  try {
    const response = await fetch(`${API_BASE}/api/v1/learning/reject-fix`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_id: eventId, reason, rejected_by: 'user' }),
    });
    if (!response.ok) throw new Error('Failed to reject fix');
    return response.json();
  } catch {
    return { event_id: eventId, status: 'error', reason };
  }
}

export async function getImprovementHistory(days: number = 30, route?: string): Promise<{ period: string; events: ImprovementEvent[]; summary: any }> {
  try {
    let url = `/api/v1/learning/history?days=${days}`;
    if (route) url += `&route=${route}`;
    const response = await fetch(`${API_BASE}${url}`);
    if (!response.ok) throw new Error('Failed to fetch history');
    return response.json();
  } catch {
    return { period: '', events: [], summary: {} };
  }
}

export async function getLearningStats(): Promise<any> {
  try {
    const response = await fetch(`${API_BASE}/api/v1/learning/stats`);
    if (!response.ok) throw new Error('Failed to fetch stats');
    return response.json();
  } catch { return {}; }
}

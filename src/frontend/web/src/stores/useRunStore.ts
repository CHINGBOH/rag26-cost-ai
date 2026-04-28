/**
 * Ephemeral run state — NOT persisted to localStorage.
 * Cleared on each new query. Used by the right-panel process visualization.
 */
import { create } from 'zustand';

export interface QueryAnalysis {
  intent: string;
  entities: Record<string, unknown>;
  sub_queries?: string[];
}

export interface RetrievalChunk {
  chunk_id: string;
  doc_id: string;
  page?: number;
  score: number;
  content: string;
  passed_threshold: boolean;
}

export interface ToolCall {
  call_id: string;
  tool: string;
  args: Record<string, unknown>;
  result?: unknown;
  duration_ms?: number;
  status: 'running' | 'done' | 'error';
}

export interface SandboxExec {
  code: string;
  stdout: string;
  result: string;
  duration_ms: number;
  safe: boolean;
}

export interface LoopState {
  iteration: number;
  eval_score: number;
  rewrite_reason?: string;
  max_iterations: number;
}

export interface EvalScores {
  completeness: number;
  consistency: number;
  confidence: number;
  information_gain: number;
  source_diversity: number;
  fact_consistency: number;
  coverage_estimate: number;
}

export interface RuntimeInfo {
  provider?: string;
  model?: string;
  engine?: string;
  routeMode?: string;
}

export interface PresentationPoint {
  label: string;
  value: number;
  min_value?: number;
  max_value?: number;
  count?: number;
  pages?: number[];
  sources?: string[];
}

export interface PresentationHighlight {
  label?: string;
  kind?: string;
  value: string;
}

export interface PresentationSection {
  label?: string;
  kind?: string;
  body: string;
}

export interface PresentationCalculationStep {
  order: number;
  title: string;
  formula: string;
  substituted: string;
  result: string;
  result_text: string;
  unit?: string;
  copy_expression: string;
}

export interface PresentationSource {
  index: number;
  title: string;
  page: string;
}

export type PresentationBlockHint = 'paragraph' | 'list' | 'callout' | 'inline' | 'table';

export interface PresentationBlock {
  id: string;
  title: string;
  body: string;
  hint?: PresentationBlockHint;
}

export interface PresentationPayload {
  type: 'price_comparison' | 'price_trend' | 'price_snapshot' | 'answer_sections' | 'calculation_steps';
  query_type?: string;
  title: string;
  support_kicker?: string;
  unit?: string;
  points?: PresentationPoint[];
  delta?: number | null;
  delta_percent?: number | null;
  note?: string;
  summary?: string;
  highlights?: PresentationHighlight[];
  sections?: PresentationSection[];
  layout?: PresentationBlock[];
  steps?: PresentationCalculationStep[];
  sources?: PresentationSource[];
  support_label?: string;
}

export interface RunState {
  runId: string | null;
  isStreaming: boolean;
  streamingAnswer: string;
  statusMessage: string;
  runtimeInfo: RuntimeInfo | null;

  queryAnalysis: QueryAnalysis | null;
  planSteps: string[];
  retrievalChunks: RetrievalChunk[];
  toolCalls: ToolCall[];
  sandboxExecs: SandboxExec[];
  loopStates: LoopState[];
  evalScores: EvalScores | null;
  presentation: PresentationPayload | null;

  finalIterations: number;
  finalLatencyMs: number;
  tokensIn: number;
  tokensOut: number;
  tokensThink: number;

  startRun: (runId: string) => void;
  setStreamingAnswer: (text: string) => void;
  appendToken: (delta: string) => void;
  setStatusMessage: (text: string) => void;
  setRuntimeInfo: (runtime: RuntimeInfo) => void;
  setQueryAnalysis: (qa: QueryAnalysis) => void;
  setPlanSteps: (steps: string[]) => void;
  addRetrievalChunk: (chunk: RetrievalChunk) => void;
  startToolCall: (tc: Omit<ToolCall, 'status'>) => void;
  endToolCall: (call_id: string, result: unknown, duration_ms: number) => void;
  addSandboxExec: (exec: SandboxExec) => void;
  addLoopState: (ls: LoopState) => void;
  setEvalScores: (scores: EvalScores) => void;
  setPresentation: (payload: PresentationPayload | null) => void;
  finishRun: (data: {
    answer: string;
    iterations: number;
    latency_ms: number;
    tokens_in?: number;
    tokens_out?: number;
    tokens_think?: number;
    presentation?: PresentationPayload | null;
  }) => void;
  clearRun: () => void;
}

export const useRunStore = create<RunState>((set) => ({
  runId: null,
  isStreaming: false,
  streamingAnswer: '',
  statusMessage: '',
  runtimeInfo: null,
  queryAnalysis: null,
  planSteps: [],
  retrievalChunks: [],
  toolCalls: [],
  sandboxExecs: [],
  loopStates: [],
  evalScores: null,
  presentation: null,
  finalIterations: 0,
  finalLatencyMs: 0,
  tokensIn: 0,
  tokensOut: 0,
  tokensThink: 0,

  startRun: (runId) =>
    set({
      runId,
      isStreaming: true,
      streamingAnswer: '',
      statusMessage: '正在理解问题...',
      runtimeInfo: null,
      queryAnalysis: null,
      planSteps: [],
      retrievalChunks: [],
      toolCalls: [],
      sandboxExecs: [],
      loopStates: [],
      evalScores: null,
      presentation: null,
      finalIterations: 0,
      finalLatencyMs: 0,
      tokensIn: 0,
      tokensOut: 0,
      tokensThink: 0,
    }),

  setStreamingAnswer: (text) => set({ streamingAnswer: text }),
  appendToken: (delta) => set((s) => ({ streamingAnswer: s.streamingAnswer + delta })),
  setStatusMessage: (text) => set({ statusMessage: text }),
  setRuntimeInfo: (runtime) => set((s) => ({ runtimeInfo: { ...s.runtimeInfo, ...runtime } })),
  setQueryAnalysis: (qa) => set({ queryAnalysis: qa }),
  setPlanSteps: (steps) => set({ planSteps: steps }),
  addRetrievalChunk: (chunk) => set((s) => ({ retrievalChunks: [...s.retrievalChunks, chunk] })),

  startToolCall: (tc) =>
    set((s) => ({
      toolCalls: [...s.toolCalls, { ...tc, status: 'running' as const }],
    })),

  endToolCall: (call_id, result, duration_ms) =>
    set((s) => ({
      toolCalls: s.toolCalls.map((tc) =>
        tc.call_id === call_id ? { ...tc, result, duration_ms, status: 'done' as const } : tc
      ),
    })),

  addSandboxExec: (exec) => set((s) => ({ sandboxExecs: [...s.sandboxExecs, exec] })),
  addLoopState: (ls) => set((s) => ({ loopStates: [...s.loopStates, ls] })),
  setEvalScores: (scores) => set({ evalScores: scores }),
  setPresentation: (payload) => set({ presentation: payload }),

  finishRun: (data) =>
    set({
      isStreaming: false,
      streamingAnswer: data.answer,
      statusMessage: '',
      finalIterations: data.iterations,
      finalLatencyMs: data.latency_ms,
      tokensIn: data.tokens_in ?? 0,
      tokensOut: data.tokens_out ?? 0,
      tokensThink: data.tokens_think ?? 0,
      presentation: data.presentation ?? null,
    }),

  clearRun: () =>
    set({
      runId: null,
      isStreaming: false,
      streamingAnswer: '',
      statusMessage: '',
      runtimeInfo: null,
      queryAnalysis: null,
      planSteps: [],
      retrievalChunks: [],
      toolCalls: [],
      sandboxExecs: [],
      loopStates: [],
      evalScores: null,
      presentation: null,
    }),
}));

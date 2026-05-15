/**
 * Agent 交互 Hook — SSE streaming via fetch() + AbortController
 * 
 * State split:
 * - useChatStore (persisted): finalized messages
 * - useRunStore (ephemeral): live streaming visualization data
 */

import { useCallback, useRef } from 'react';
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import {
  useRunStore,
  QueryAnalysis,
  RetrievalChunk,
  EvalScores,
  ToolCall,
  SandboxExec,
  LoopState,
  RuntimeInfo,
  PresentationPayload,
  FollowupSuggestion,
} from '../stores/useRunStore';
import { AgentChunk, AgentEvaluation } from '../services/agentApi';
import { getApiBaseUrl } from '../config/runtime';
import { createClientId } from '../utils/id';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  sessionId?: string;
  runId?: string;
  chunks?: AgentChunk[];
  evaluation?: AgentEvaluation;
  iterations?: number;
  latencyMs?: number;
  evalScores?: EvalScores | null;
  provider?: string;
  model?: string;
  engine?: string;
  routeMode?: string;
  error?: string;
  presentation?: PresentationPayload | null;
  followups?: FollowupSuggestion[];
}

// Issue #125 fix: Import unified schema from @rag/shared
import { type AgentConfig as SharedAgentConfig, resolveLLMProvider } from '@rag/shared';

// Re-export for backward compatibility
export type AgentConfig = SharedAgentConfig;

interface ChatStore {
  messages: ChatMessage[];
  isLoading: boolean;
  sessionId: string | null;
  _addMessage: (msg: ChatMessage) => void;
  _replaceLastAssistant: (patch: Partial<ChatMessage>) => void;
  _setLoading: (loading: boolean) => void;
  _setMessages: (msgs: ChatMessage[]) => void;
  _setSessionId: (id: string | null) => void;
}

const MAX_MESSAGES = 200;

const useChatStore = create<ChatStore>()(
  persist(
    (set) => ({
      messages: [],
      isLoading: false,
      sessionId: null,
      _addMessage: (msg) =>
        set((state) => ({
          messages: [...state.messages, msg].slice(-MAX_MESSAGES),
        })),
      _replaceLastAssistant: (patch) =>
        set((state) => {
          const idx = (() => {
            for (let i = state.messages.length - 1; i >= 0; i -= 1) {
              if (state.messages[i].role === 'assistant') return i;
            }
            return -1;
          })();
          if (idx < 0) return state;
          const next = state.messages.slice();
          next[idx] = { ...next[idx], ...patch };
          return { messages: next };
        }),
      _setLoading: (loading) => set({ isLoading: loading }),
      _setMessages: (msgs) => set({ messages: msgs }),
      _setSessionId: (id) => set({ sessionId: id }),
    }),
    {
      name: 'rag-chat-messages',
      partialize: (state) => ({ messages: state.messages, sessionId: state.sessionId }),
    }
  )
);

const API_BASE = getApiBaseUrl();

// Strip Chinese filler words / temporal noise that breaks embedding retrieval.
// Used only for the /api/v1/rag fallback when the Agent loop yielded no_data.
function simplifyQueryForFallback(raw: string): string {
  let q = raw;
  q = q.replace(/根据|请|帮我|帮忙|能否|可以|麻烦|告诉我|想知道|问下|问一下/g, '');
  q = q.replace(/分析[一]?下?|说[一]?下|看[一]?下/g, '');
  q = q.replace(/从[\s\S]{0,15}?(开始|起|至今|到现在|到目前)/g, '');
  q = q.replace(/至今|到现在|到目前|目前|当前|最近/g, '');
  q = q.replace(/\d{2,4}\s*年|\d{1,2}\s*月|去年|今年|往年/g, '');
  q = q.replace(/走势|趋势|变化|情况|历史|过去/g, '');
  q = q.replace(/[，。、,.]/g, ' ');
  q = q.replace(/\s+/g, ' ').trim();
  return q || raw;
}

function buildPresentationFallbackText(presentation: PresentationPayload | null | undefined): string {
  if (!presentation) return '';

  if (presentation.type === 'answer_sections') {
    return presentation.summary || '';
  }

  if (presentation.type === 'calculation_steps') {
    return presentation.summary || presentation.title || '';
  }

  const points = presentation.points ?? [];
  if (presentation.type === 'price_comparison' && points.length >= 2) {
    const from = points[0];
    const to = points[points.length - 1];
    const unitSuffix = presentation.unit ? ` 元/${presentation.unit}` : '';
    if (presentation.delta != null) {
      return `${to.label} 相比 ${from.label}${presentation.delta >= 0 ? '上涨' : '下降'} ${Math.abs(presentation.delta).toFixed(2)}${unitSuffix}。`;
    }
  }

  if (presentation.type === 'price_trend' && points.length >= 2) {
    const start = points[0];
    const end = points[points.length - 1];
    const unitSuffix = presentation.unit ? ` 元/${presentation.unit}` : '';
    return `${presentation.title}：从 ${start.label} 的 ${start.value.toFixed(2)}${unitSuffix} 变化到 ${end.label} 的 ${end.value.toFixed(2)}${unitSuffix}。`;
  }

  if (presentation.type === 'price_snapshot' && points.length > 0) {
    const point = points[0];
    const unitSuffix = presentation.unit ? ` 元/${presentation.unit}` : '';
    return `${presentation.title}：${point.label} 为 ${point.value.toFixed(2)}${unitSuffix}。`;
  }

  return presentation.title || '';
}

export function useAgent() {
  const messages = useChatStore((s) => s.messages);
  const sessionId = useChatStore((s) => s.sessionId);
  const isLoading = useChatStore((s) => s.isLoading);
  const _addMessage = useChatStore((s) => s._addMessage);
  const _replaceLastAssistant = useChatStore((s) => s._replaceLastAssistant);
  const _setLoading = useChatStore((s) => s._setLoading);
  const _setMessages = useChatStore((s) => s._setMessages);
  const _setSessionId = useChatStore((s) => s._setSessionId);

  const abortControllerRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(
    async (query: string, config?: AgentConfig) => {
      if (!query.trim() || isLoading) return;

      // Cancel any in-flight request
      abortControllerRef.current?.abort();
      abortControllerRef.current = new AbortController();
      const { signal } = abortControllerRef.current;

      const runId = `run-${Date.now()}`;
      const currentSessionId = sessionId || createClientId();
      if (!sessionId) _setSessionId(currentSessionId);

      _addMessage({
        id: `user-${Date.now()}`,
        role: 'user',
        content: query.trim(),
        timestamp: Date.now(),
      });
      _setLoading(true);

      const runStore = useRunStore.getState();
      runStore.startRun(runId);

      try {
        let finalized = false;
        let currentEventType = '';
        let currentDataLines: string[] = [];

        const finalizeAssistantMessage = (payload?: Record<string, unknown>) => {
          if (finalized) return;

          const finalRunStore = useRunStore.getState();
          const presentation =
            (payload?.presentation as PresentationPayload | null | undefined) ?? finalRunStore.presentation;
          const followups =
            (payload?.followup_suggestions as FollowupSuggestion[] | undefined) ?? finalRunStore.followups;
          const content =
            ((payload?.answer as string | undefined) || finalRunStore.streamingAnswer || '').trim()
            || buildPresentationFallbackText(presentation);

          if (!content && !presentation && finalRunStore.retrievalChunks.length === 0) {
            return;
          }

          _addMessage({
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content,
            timestamp: Date.now(),
            sessionId: currentSessionId,
            runId,
            iterations: (payload?.iterations as number | undefined) ?? finalRunStore.finalIterations,
            latencyMs: (payload?.latency_ms as number | undefined) ?? finalRunStore.finalLatencyMs,
            chunks: finalRunStore.retrievalChunks as AgentChunk[],
            evalScores: finalRunStore.evalScores,
            provider: (payload?.provider as string | undefined) ?? finalRunStore.runtimeInfo?.provider,
            model: (payload?.model as string | undefined) ?? finalRunStore.runtimeInfo?.model,
            engine: (payload?.engine as string | undefined) ?? finalRunStore.runtimeInfo?.engine,
            routeMode: (payload?.route_mode as string | undefined) ?? finalRunStore.runtimeInfo?.routeMode,
            presentation,
            followups,
          });
          finalized = true;
        };

        const flushEvent = () => {
          if (!currentEventType || currentDataLines.length === 0) return;
          const dataStr = currentDataLines.join('\n');
          try {
            const data = JSON.parse(dataStr);
            handleSSEEvent(currentEventType, data);

            if (currentEventType === 'done') {
              finalizeAssistantMessage(data);
              useRunStore.getState().finishRun({
                answer:
                  ((data.answer as string | undefined) || useRunStore.getState().streamingAnswer || '').trim()
                  || buildPresentationFallbackText(
                    (data.presentation as PresentationPayload | null | undefined)
                    ?? useRunStore.getState().presentation
                  ),
                iterations: (data.iterations as number) ?? 0,
                latency_ms: (data.latency_ms as number) ?? 0,
                presentation:
                  (data.presentation as PresentationPayload | null | undefined)
                  ?? useRunStore.getState().presentation,
                followups:
                  (data.followup_suggestions as FollowupSuggestion[] | undefined)
                  ?? useRunStore.getState().followups,
              });
            }
          } catch (e) {
            console.error('SSE parse error', e, dataStr);
          }
          currentEventType = '';
          currentDataLines = [];
        };

        // Issue #125 fix: Resolve llmProvider if not explicitly provided
        const resolvedProvider = config?.llmProvider || resolveLLMProvider({
          ...(config || {}),
          llmRoute: config?.llmRoute ?? 'deepseek',
        } as SharedAgentConfig);

        const response = await fetch(`${API_BASE}/api/v1/agent/stream`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            query: query.trim(),
            session_id: currentSessionId,
            max_iterations: config?.maxIterations ?? 3,
            score_threshold: config?.scoreThreshold ?? 0.6,
            top_k: config?.topK ?? 8,
            search_mode: config?.searchMode ?? 'hybrid',
            doc_types: config?.docTypes ?? [],
            llm_route: config?.llmRoute ?? 'deepseek',
            llm_provider: resolvedProvider,  // ✅ Now guaranteed to have a value
            llm_model: config?.llmModel,
            llm_engine: config?.llmEngine,
          }),
          signal,
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        if (!response.body) throw new Error('No response body');

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';

          for (const line of lines) {
            if (line.startsWith('event: ')) {
              currentEventType = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              currentDataLines.push(line.slice(6));
            } else if (line === '') {
              flushEvent();
            }
          }
        }

        buffer += decoder.decode();
        if (buffer.trim()) {
          for (const line of buffer.split('\n')) {
            if (line.startsWith('event: ')) {
              currentEventType = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              currentDataLines.push(line.slice(6));
            } else if (line === '') {
              flushEvent();
            }
          }
        }
        flushEvent();

        if (!finalized) {
          const partialRunStore = useRunStore.getState();
          finalizeAssistantMessage();
          partialRunStore.finishRun({
            answer: partialRunStore.streamingAnswer || buildPresentationFallbackText(partialRunStore.presentation),
            iterations: partialRunStore.finalIterations,
            latency_ms: partialRunStore.finalLatencyMs,
            presentation: partialRunStore.presentation,
            followups: partialRunStore.followups,
          });
        }

        // Issue #151 follow-up: if the Agent loop gave up with no_data while
        // chunks actually exist in the vector store, fall back to /api/v1/rag
        // so the user gets a real answer instead of "未检索到相关依据".
        const postState = useRunStore.getState();
        const presentationIsNoData = postState.presentation?.type === 'no_data';
        const answerLooksEmpty = !postState.streamingAnswer?.trim();
        const noChunks = postState.retrievalChunks.length === 0;
        if (!signal.aborted && presentationIsNoData && answerLooksEmpty && noChunks) {
          try {
            const subQueries = postState.queryAnalysis?.sub_queries ?? [];
            const cleanSub = subQueries.find((s) => s && s.trim() && s.trim().length < 25)?.trim();
            const fallbackQuery = cleanSub || simplifyQueryForFallback(query);
            const ragResp = await fetch(`${API_BASE}/api/v1/rag`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                query: fallbackQuery,
                top_k: config?.topK ?? 8,
                session_id: currentSessionId,
              }),
              signal,
            });
            if (ragResp.ok) {
              const ragData = (await ragResp.json()) as {
                answer?: string;
                chunks?: AgentChunk[];
              };
              const fallbackAnswer = (ragData.answer || '').trim();
              const fallbackChunks = ragData.chunks ?? [];
              const refusalPatterns = [
                '无法回答', '无法直接回答', '无法提供', '无法分析',
                '抱歉', '未检索到', '未提供', '不足以回答',
              ];
              const isRefusal = refusalPatterns.some((p) => fallbackAnswer.startsWith(p) || fallbackAnswer.slice(0, 50).includes(p));
              if (fallbackAnswer && fallbackChunks.length > 0 && !isRefusal) {
                _replaceLastAssistant({
                  content: fallbackAnswer,
                  chunks: fallbackChunks,
                  presentation: null,
                });
                const rs = useRunStore.getState();
                rs.setPresentation(null);
                rs.finishRun({
                  answer: fallbackAnswer,
                  iterations: rs.finalIterations,
                  latency_ms: rs.finalLatencyMs,
                  presentation: null,
                  followups: rs.followups,
                });
              }
            }
          } catch (fbErr) {
            if ((fbErr as Error).name !== 'AbortError') {
              console.warn('RAG fallback failed:', fbErr);
            }
          }
        }
      } catch (error) {
        if ((error as Error).name === 'AbortError') return;
        const partialRunStore = useRunStore.getState();
        const partialAnswer =
          partialRunStore.streamingAnswer || buildPresentationFallbackText(partialRunStore.presentation);
        if (partialAnswer || partialRunStore.presentation || partialRunStore.retrievalChunks.length > 0) {
          _addMessage({
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content: partialAnswer,
            timestamp: Date.now(),
            sessionId: currentSessionId,
            runId,
            chunks: partialRunStore.retrievalChunks as AgentChunk[],
            evalScores: partialRunStore.evalScores,
            provider: partialRunStore.runtimeInfo?.provider,
            model: partialRunStore.runtimeInfo?.model,
            engine: partialRunStore.runtimeInfo?.engine,
            routeMode: partialRunStore.runtimeInfo?.routeMode,
            presentation: partialRunStore.presentation,
            followups: partialRunStore.followups,
          });
        } else {
          _addMessage({
            id: `error-${Date.now()}`,
            role: 'assistant',
            content: '',
            timestamp: Date.now(),
            error: error instanceof Error ? error.message : '请求失败',
          });
        }
        useRunStore.getState().finishRun({
          answer: partialAnswer,
          iterations: partialRunStore.finalIterations,
          latency_ms: partialRunStore.finalLatencyMs,
          presentation: partialRunStore.presentation,
          followups: partialRunStore.followups,
        });
      } finally {
        _setLoading(false);
      }
    },
    [isLoading, sessionId, _addMessage, _replaceLastAssistant, _setLoading, _setSessionId]
  );

  const cancelStream = useCallback(() => {
    abortControllerRef.current?.abort();
    _setLoading(false);
    const rs = useRunStore.getState();
    rs.finishRun({ answer: rs.streamingAnswer, iterations: 0, latency_ms: 0 });
  }, [_setLoading]);

  const clearMessages = useCallback(() => {
    abortControllerRef.current?.abort();
    _setMessages([]);
    _setLoading(false);
    _setSessionId(null);
    useRunStore.getState().clearRun();
  }, [_setMessages, _setLoading, _setSessionId]);

  return { messages, isLoading, sendMessage, clearMessages, cancelStream, sessionId };
}

type RunStoreState = ReturnType<typeof useRunStore.getState>;

function handleSSEEvent(type: string, data: Record<string, unknown>) {
  const rs = useRunStore.getState() as RunStoreState;
  switch (type) {
    case 'progress':
      rs.setStatusMessage((data.message as string) ?? '');
      break;
    case 'query_analysis':
      rs.setQueryAnalysis(data as unknown as QueryAnalysis);
      break;
    case 'plan':
      rs.setPlanSteps((data.steps as string[]) ?? []);
      rs.setStatusMessage('检索计划已生成');
      break;
    case 'executing':
      rs.setStatusMessage((data.message as string) ?? '正在执行检索步骤...');
      break;
    case 'retrieval_result':
      rs.addRetrievalChunk(data as unknown as RetrievalChunk);
      break;
    case 'tool_call_start':
      rs.startToolCall(data as unknown as Omit<ToolCall, 'status'>);
      rs.setStatusMessage(`调用工具 ${(data.tool as string) ?? ''}...`);
      break;
    case 'tool_call_end':
      rs.endToolCall(
        data.call_id as string,
        data.result_summary ?? data.result,
        (data.duration_ms as number) ?? 0
      );
      rs.setStatusMessage(`工具 ${(data.tool as string) ?? ''} 已返回结果`);
      break;
    case 'step_done':
      rs.setStatusMessage((data.message as string) ?? '当前步骤完成');
      break;
    case 'sandbox_exec':
      rs.addSandboxExec(data as unknown as SandboxExec);
      break;
    case 'loop_state':
      rs.addLoopState(data as unknown as LoopState);
      break;
    case 'eval_scores':
      rs.setEvalScores(data as unknown as EvalScores);
      break;
    case 'presentation':
      rs.setPresentation(data as unknown as PresentationPayload);
      break;
    case 'followup_suggestions':
      rs.setFollowups((data.suggestions as FollowupSuggestion[]) ?? []);
      break;
    case 'synthesizing':
      rs.setRuntimeInfo({
        provider: data.provider as string | undefined,
        model: data.model as string | undefined,
        engine: data.engine as string | undefined,
        routeMode: data.route_mode as string | undefined,
      } as RuntimeInfo);
      rs.setStatusMessage(
        `综合分析中 · ${(data.engine as string) || (data.provider as string) || '模型'}`
      );
      break;
    case 'token':
      rs.appendToken((data.delta as string) ?? '');
      break;
    case 'error':
      rs.setStatusMessage((data.message as string) ?? '请求失败');
      console.error('Agent SSE error:', data);
      break;
  }
}

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
import { useRunStore, QueryAnalysis, RetrievalChunk, EvalScores, ToolCall, SandboxExec, LoopState } from '../stores/useRunStore';
import { AgentChunk, AgentEvaluation } from '../services/agentApi';

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
  error?: string;
}

export interface AgentConfig {
  maxIterations?: number;
  scoreThreshold?: number;
  topK?: number;
  searchMode?: string;
  docTypes?: string[];
}

interface ChatStore {
  messages: ChatMessage[];
  isLoading: boolean;
  sessionId: string | null;
  _addMessage: (msg: ChatMessage) => void;
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

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export function useAgent() {
  const messages = useChatStore((s) => s.messages);
  const sessionId = useChatStore((s) => s.sessionId);
  const isLoading = useChatStore((s) => s.isLoading);
  const _addMessage = useChatStore((s) => s._addMessage);
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
      const currentSessionId = sessionId || crypto.randomUUID();
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

          let eventType = '';
          let dataStr = '';

          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              dataStr = line.slice(6).trim();
            } else if (line === '' && eventType && dataStr) {
              try {
                const data = JSON.parse(dataStr);
                handleSSEEvent(eventType, data);

                if (eventType === 'done') {
                  const finalRunStore = useRunStore.getState();
                  _addMessage({
                    id: `assistant-${Date.now()}`,
                    role: 'assistant',
                    content: data.answer,
                    timestamp: Date.now(),
                    sessionId: currentSessionId,
                    runId,
                    iterations: data.iterations,
                    latencyMs: data.latency_ms,
                    chunks: finalRunStore.retrievalChunks as AgentChunk[],
                    evalScores: finalRunStore.evalScores,
                  });
                  finalRunStore.finishRun(data);
                }
              } catch (e) {
                console.error('SSE parse error', e, dataStr);
              }
              eventType = '';
              dataStr = '';
            }
          }
        }
      } catch (error) {
        if ((error as Error).name === 'AbortError') return;

        _addMessage({
          id: `error-${Date.now()}`,
          role: 'assistant',
          content: '',
          timestamp: Date.now(),
          error: error instanceof Error ? error.message : '请求失败',
        });
        useRunStore.getState().finishRun({ answer: '', iterations: 0, latency_ms: 0 });
      } finally {
        _setLoading(false);
      }
    },
    [isLoading, sessionId, _addMessage, _setLoading, _setSessionId]
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
    case 'query_analysis':
      rs.setQueryAnalysis(data as unknown as QueryAnalysis);
      break;
    case 'plan':
      rs.setPlanSteps((data.steps as string[]) ?? []);
      break;
    case 'retrieval_result':
      rs.addRetrievalChunk(data as unknown as RetrievalChunk);
      break;
    case 'tool_call_start':
      rs.startToolCall(data as unknown as Omit<ToolCall, 'status'>);
      break;
    case 'tool_call_end':
      rs.endToolCall(
        data.call_id as string,
        data.result,
        (data.duration_ms as number) ?? 0
      );
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
    case 'token':
      rs.appendToken((data.delta as string) ?? '');
      break;
    case 'error':
      console.error('Agent SSE error:', data);
      break;
  }
}


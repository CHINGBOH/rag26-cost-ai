/**
 * XState v5 状态机定义
 * 驱动递归流程的状态流转
 */

import { setup, fromPromise, assign } from 'xstate';
import {
  RecursionState,
  RecursionSession,
  RecursionRound,
  ExpertDecision,
  RetrievedChunk,
  RoundEvaluation,
  SubQuery
} from '@rag/shared';
import { EventEmitter } from 'events';

// 将 unknown 错误转换为 Error 对象
function toError(error: unknown): Error {
  if (error instanceof Error) {
    return error;
  }
  if (typeof error === 'string') {
    return new Error(error);
  }
  return new Error(String(error));
}

// 状态机上下文
export interface RecursionContext {
  session: RecursionSession;
  currentRound?: RecursionRound;
  expertDecision?: ExpertDecision;
  error?: Error;
}

// 状态机事件
type RecursionEvent =
  | { type: 'START'; query: string }
  | { type: 'DECOMPOSE_COMPLETE'; subQueries: any[] }
  | { type: 'RETRIEVE_COMPLETE'; chunks: any[] }
  | { type: 'GENERATE_COMPLETE'; answer: string }
  | { type: 'EVALUATION_COMPLETE'; evaluation: any }
  | { type: 'EXPERT_DECISION'; decision: ExpertDecision; reasoning: string }
  | { type: 'EXTERNAL_QUERY_COMPLETE'; result: any }
  | { type: 'HUMAN_REVIEW_COMPLETE'; approved: boolean }
  | { type: 'ERROR'; error: Error }
  | { type: 'CANCEL' };

// 创建状态机 (XState v5 使用 setup)
export function createRecursionMachine(
  session: RecursionSession,
  eventEmitter: EventEmitter
) {
  // 定义状态机设置，包含默认的模拟 actor
  const recursionMachineSetup = setup({
    types: {
      context: {} as RecursionContext,
      events: {} as RecursionEvent,
      input: {} as {}
    },
    actors: {
      // 默认模拟 actor，返回适当的默认值以确保类型兼容
      // 实际使用时由外部提供具体实现
      decomposeQuery: fromPromise(async ({ input }: { input: RecursionContext }): Promise<RecursionRound> => {
        return {
          roundId: input.session.currentDepth + 1,
          timestamp: Date.now(),
          subQueries: [] as SubQuery[],
          retrievedChunks: [] as RetrievedChunk[],
          contradictions: []
        };
      }),
      dispatchQueries: fromPromise(async ({ input }: { input: RecursionContext }): Promise<void> => {
        // 空实现
        return;
      }),
      retrieveChunks: fromPromise(async ({ input }: { input: RecursionContext }): Promise<RetrievedChunk[]> => {
        return [];
      }),
      rankChunks: fromPromise(async ({ input }: { input: RecursionContext }): Promise<void> => {
        // 空实现
        return;
      }),
      generateAnswer: fromPromise(async ({ input }: { input: RecursionContext }): Promise<{ answer: string }> => {
        return { answer: '' };
      }),
      evaluateRound: fromPromise(async ({ input }: { input: RecursionContext }): Promise<any> => {
        return {
          completeness: 0,
          consistency: 0,
          confidence: 0,
          informationGain: 0,
          sourceDiversity: 0,
          factConsistency: 0,
          coverageEstimate: 0
        };
      }),
      expertJudgment: fromPromise(async ({ input }: { input: RecursionContext }): Promise<any> => {
        return {
          decision: 'satisfy' as const,
          reasoning: '默认实现'
        };
      }),
      queryExternal: fromPromise(async ({ input }: { input: RecursionContext }): Promise<void> => {
        // 空实现
        return;
      })
    }
  });

  // 创建状态机
  const machine = recursionMachineSetup.createMachine({
    id: 'recursion-controller',
    initial: 'idle',
    context: () => ({
      session,
      currentRound: undefined,
      expertDecision: undefined,
      error: undefined
    }),
    states: {
      idle: {
        on: {
          START: {
            target: 'decomposing',
            actions: assign({
              session: ({ context, event }) => ({
                ...context.session,
                currentState: 'decomposing' as RecursionState,
                updatedAt: Date.now()
              })
            })
          }
        }
      },

      decomposing: {
        entry: ({ context }) => {
          emitEvent(eventEmitter, context.session.id, 'state_change', { to: 'decomposing' });
        },
        invoke: {
          src: 'decomposeQuery',
          input: ({ context }) => context,
          onDone: {
            target: 'dispatching',
            actions: assign({
              currentRound: ({ event }) => event.output,
              session: ({ context }) => ({
                ...context.session,
                currentState: 'dispatching' as RecursionState,
                updatedAt: Date.now()
              })
            })
          },
          onError: {
            target: 'failed',
            actions: assign({
              error: ({ event }) => toError(event.error)
            })
          }
        },
        on: { CANCEL: 'completed' }
      },

      dispatching: {
        entry: ({ context }) => {
          emitEvent(eventEmitter, context.session.id, 'state_change', { to: 'dispatching' });
        },
        invoke: {
          src: 'dispatchQueries',
          input: ({ context }) => context,
          onDone: {
            target: 'retrieving',
            actions: assign({
              session: ({ context }) => ({
                ...context.session,
                currentState: 'retrieving' as RecursionState,
                updatedAt: Date.now()
              })
            })
          },
          onError: {
            target: 'failed',
            actions: assign({
              error: ({ event }) => toError(event.error)
            })
          }
        }
      },

      retrieving: {
        entry: ({ context }) => {
          emitEvent(eventEmitter, context.session.id, 'state_change', { to: 'retrieving' });
        },
        invoke: {
          src: 'retrieveChunks',
          input: ({ context }) => context,
          onDone: {
            target: 'ranking',
            actions: assign({
              currentRound: ({ context, event }) => ({
                ...context.currentRound!,
                retrievedChunks: event.output
              }),
              session: ({ context }) => ({
                ...context.session,
                currentState: 'ranking' as RecursionState,
                updatedAt: Date.now()
              })
            })
          },
          onError: {
            target: 'failed',
            actions: assign({
              error: ({ event }) => toError(event.error)
            })
          }
        }
      },

      ranking: {
        entry: ({ context }) => {
          emitEvent(eventEmitter, context.session.id, 'state_change', { to: 'ranking' });
        },
        invoke: {
          src: 'rankChunks',
          input: ({ context }) => context,
          onDone: {
            target: 'generating',
            actions: assign({
              session: ({ context }) => ({
                ...context.session,
                currentState: 'generating' as RecursionState,
                updatedAt: Date.now()
              })
            })
          },
          onError: {
            target: 'failed',
            actions: assign({
              error: ({ event }) => toError(event.error)
            })
          }
        }
      },

      generating: {
        entry: ({ context }) => {
          emitEvent(eventEmitter, context.session.id, 'state_change', { to: 'generating' });
        },
        invoke: {
          src: 'generateAnswer',
          input: ({ context }) => context,
          onDone: {
            target: 'evaluating',
            actions: assign({
              currentRound: ({ context, event }) => ({
                ...context.currentRound!,
                generatedAnswer: event.output.answer
              }),
              session: ({ context }) => ({
                ...context.session,
                currentState: 'evaluating' as RecursionState,
                updatedAt: Date.now()
              })
            })
          },
          onError: {
            target: 'failed',
            actions: assign({
              error: ({ event }) => toError(event.error)
            })
          }
        }
      },

      evaluating: {
        entry: ({ context }) => {
          emitEvent(eventEmitter, context.session.id, 'state_change', { to: 'evaluating' });
        },
        invoke: {
          src: 'evaluateRound',
          input: ({ context }) => context,
          onDone: {
            target: 'deciding',
            actions: assign({
              currentRound: ({ context, event }) => ({
                ...context.currentRound!,
                evaluation: event.output
              }),
              session: ({ context }) => ({
                ...context.session,
                currentState: 'deciding' as RecursionState,
                updatedAt: Date.now()
              })
            })
          },
          onError: {
            target: 'failed',
            actions: assign({
              error: ({ event }) => toError(event.error)
            })
          }
        }
      },

      deciding: {
        entry: ({ context }) => {
          emitEvent(eventEmitter, context.session.id, 'state_change', { to: 'deciding' });
        },
        invoke: {
          src: 'expertJudgment',
          input: ({ context }) => context,
          onDone: [
            {
              target: 'completed',
              guard: ({ event }) => event.output.decision === 'satisfy',
              actions: assign({
                expertDecision: ({ event }) => event.output.decision,
                currentRound: ({ context, event }) => ({
                  ...context.currentRound!,
                  decision: event.output.decision,
                  expertReasoning: event.output.reasoning
                }),
                session: ({ context }) => ({
                  ...context.session,
                  currentState: 'completed' as RecursionState,
                  finalAnswer: context.currentRound?.generatedAnswer,
                  updatedAt: Date.now()
                })
              })
            },
            {
              target: 'querying_external',
              guard: ({ event }) => event.output.decision === 'query_external',
              actions: assign({
                expertDecision: ({ event }) => event.output.decision,
                currentRound: ({ context, event }) => ({
                  ...context.currentRound!,
                  decision: event.output.decision,
                  expertReasoning: event.output.reasoning
                }),
                session: ({ context }) => ({
                  ...context.session,
                  currentState: 'querying_external' as RecursionState,
                  updatedAt: Date.now()
                })
              })
            },
            {
              target: 'human_review',
              guard: ({ event }) => event.output.decision === 'human_review',
              actions: assign({
                expertDecision: ({ event }) => event.output.decision,
                session: ({ context }) => ({
                  ...context.session,
                  currentState: 'human_review' as RecursionState,
                  updatedAt: Date.now()
                })
              })
            },
            {
              target: 'decomposing',
              guard: ({ event }) => event.output.decision === 'continue',
              actions: assign({
                expertDecision: ({ event }) => event.output.decision,
                currentRound: ({ context, event }) => ({
                  ...context.currentRound!,
                  decision: event.output.decision,
                  expertReasoning: event.output.reasoning
                }),
                session: ({ context }) => {
                  const newDepth = context.session.currentDepth + 1;
                  return {
                    ...context.session,
                    currentDepth: newDepth,
                    metrics: {
                      ...context.session.metrics,
                      maxDepthReached: Math.max(context.session.metrics.maxDepthReached, newDepth)
                    },
                    rounds: [...context.session.rounds, context.currentRound!],
                    currentState: 'decomposing' as RecursionState,
                    updatedAt: Date.now()
                  };
                }
              })
            }
          ],
          onError: {
            target: 'failed',
            actions: assign({
              error: ({ event }) => toError(event.error)
            })
          }
        }
      },

      querying_external: {
        entry: ({ context }) => {
          emitEvent(eventEmitter, context.session.id, 'state_change', { to: 'querying_external' });
        },
        invoke: {
          src: 'queryExternal',
          input: ({ context }) => context,
          onDone: {
            target: 'decomposing',
            actions: assign({
              session: ({ context }) => {
                const newDepth = context.session.currentDepth + 1;
                return {
                  ...context.session,
                  currentDepth: newDepth,
                  metrics: {
                    ...context.session.metrics,
                    maxDepthReached: Math.max(context.session.metrics.maxDepthReached, newDepth)
                  },
                  rounds: [...context.session.rounds, context.currentRound!],
                  currentState: 'decomposing' as RecursionState,
                  updatedAt: Date.now()
                };
              }
            })
          },
          onError: {
            target: 'failed',
            actions: assign({
              error: ({ event }) => toError(event.error)
            })
          }
        }
      },

      human_review: {
        entry: ({ context }) => {
          emitEvent(eventEmitter, context.session.id, 'human_review_required', {
            sessionId: context.session.id,
            context: context.session
          });
        },
        on: {
          HUMAN_REVIEW_COMPLETE: [
            { target: 'completed', guard: ({ event }) => event.approved },
            { target: 'decomposing', guard: ({ event }) => !event.approved }
          ]
        }
      },

      completed: {
        entry: ({ context }) => {
          emitEvent(eventEmitter, context.session.id, 'recursion_complete', {
            sessionId: context.session.id,
            finalAnswer: context.session.finalAnswer,
            totalRounds: context.session.rounds.length
          });
        },
        type: 'final'
      },

      failed: {
        entry: assign({
          session: ({ context }) => ({
            ...context.session,
            currentState: 'failed' as RecursionState,
            updatedAt: Date.now()
          })
        }),
        type: 'final'
      }
    }
  });

  // 返回未提供的机器，调用者需要提供具体的 actors
  return machine;
}

function emitEvent(
  emitter: EventEmitter,
  sessionId: string,
  type: string,
  payload: any
) {
  emitter.emit('dashboard', {
    type,
    sessionId,
    timestamp: Date.now(),
    payload
  });
}

// 注意：XState v5 不再导出 interpret，使用 createActor 代替
export { EventEmitter };

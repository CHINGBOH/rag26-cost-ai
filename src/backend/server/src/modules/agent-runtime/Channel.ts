/**
 * Channel - Agent 内建状态容器
 * 
 * 设计原则：
 * 1. Agent 自带 Channel，不是外部传入
 * 2. 每次 update 产生新版本，支持回溯
 * 3. 每个字段可配置 Reducer（覆盖/追加/合并/累加）
 * 4. 可序列化，支持持久化恢复
 */

import { AgentState, AgentStatus, ChannelConfig, StateReducer, MergeStrategy } from './types';

// 默认 Reducer：覆盖
const lastWriteWins: StateReducer = (_, update) => update;

// 默认 Reducer：追加（用于数组）
const appendReducer: StateReducer<any[]> = (current, update) => {
  if (!Array.isArray(update)) return update;
  return [...(current || []), ...update];
};

// 默认 Reducer：合并 Map
const mergeMapReducer: StateReducer<Map<string, any>> = (current, update) => {
  if (!(update instanceof Map)) return update;
  const merged = new Map(current || []);
  update.forEach((v, k) => merged.set(k, v));
  return merged;
};

// 字段级 Reducer 配置
const DEFAULT_REDUCERS: Record<string, StateReducer> = {
  // 覆盖型字段
  query: lastWriteWins,
  normalizedQuery: lastWriteWins,
  intent: lastWriteWins,
  retrievalStrategy: lastWriteWins,
  answer: lastWriteWins,
  evaluation: lastWriteWins,
  status: lastWriteWins,
  error: lastWriteWins,

  // 追加型字段
  retrievedChunks: appendReducer,
  citations: appendReducer,
  calculations: appendReducer,
  subQueries: appendReducer,

  // 合并型字段
  toolResults: mergeMapReducer,

  // 累加型字段
  iteration: (current: number, update: number) => (current || 0) + (update || 0),

  // 元数据覆盖
  sessionId: lastWriteWins,
  createdAt: lastWriteWins,
  updatedAt: lastWriteWins,
};

export class Channel {
  private state: AgentState;
  private history: AgentState[] = [];
  private version = 0;
  private reducers: Record<string, StateReducer>;
  private maxHistorySize: number;

  constructor(config?: ChannelConfig) {
    this.reducers = { ...DEFAULT_REDUCERS, ...config?.reducers };
    this.maxHistorySize = config?.maxHistorySize || 50;

    // 初始化空状态
    this.state = this.createEmptyState();
  }

  private createEmptyState(): AgentState {
    const now = Date.now();
    return {
      query: '',
      retrievedChunks: [],
      toolResults: new Map(),
      iteration: 0,
      maxIterations: 5,
      status: 'idle' as AgentStatus,
      sessionId: `session_${now}_${Math.random().toString(36).slice(2, 8)}`,
      createdAt: now,
      updatedAt: now,
    };
  }

  /**
   * 初始化 Channel（接收用户查询）
   */
  init(query: string, options?: { maxIterations?: number }): void {
    const now = Date.now();
    this.state = {
      ...this.createEmptyState(),
      query,
      maxIterations: options?.maxIterations || 5,
      status: 'idle',
      sessionId: `session_${now}_${Math.random().toString(36).slice(2, 8)}`,
      createdAt: now,
      updatedAt: now,
    };
    this.history = [];
    this.version = 0;
  }

  /**
   * 更新状态（核心方法）
   * 根据字段的 Reducer 策略合并更新
   */
  update(updates: Partial<AgentState>): void {
    // 保存历史
    this.history.push({ ...this.state });
    if (this.history.length > this.maxHistorySize) {
      this.history.shift();
    }

    // 逐字段应用 Reducer
    const newState = { ...this.state };
    for (const [key, value] of Object.entries(updates)) {
      if (value === undefined) continue;
      const reducer = this.reducers[key] || lastWriteWins;
      (newState as any)[key] = reducer((this.state as any)[key], value);
    }

    newState.updatedAt = Date.now();
    this.state = newState as AgentState;
    this.version++;
  }

  /**
   * 获取当前状态
   */
  getState(): AgentState {
    return { ...this.state };
  }

  /**
   * 获取当前版本号
   */
  getVersion(): number {
    return this.version;
  }

  /**
   * 获取历史版本
   */
  getHistory(): AgentState[] {
    return [...this.history];
  }

  /**
   * 回滚到指定版本
   */
  rollback(targetVersion: number): boolean {
    if (targetVersion < 0 || targetVersion >= this.version) return false;
    const offset = this.version - targetVersion - 1;
    if (offset >= this.history.length) return false;

    this.state = { ...this.history[this.history.length - 1 - offset] };
    this.version = targetVersion + 1;
    return true;
  }

  /**
   * 序列化（用于持久化）
   */
  serialize(): string {
    // Map 需要特殊处理
    const state = this.state;
    const serializable = {
      ...state,
      toolResults: Array.from(state.toolResults.entries()),
    };
    return JSON.stringify({
      state: serializable,
      version: this.version,
      history: this.history.map(h => ({
        ...h,
        toolResults: Array.from(h.toolResults.entries()),
      })),
    });
  }

  /**
   * 反序列化（用于恢复）
   */
  deserialize(data: string): void {
    const parsed = JSON.parse(data);
    this.state = {
      ...parsed.state,
      toolResults: new Map(parsed.state.toolResults || []),
    };
    this.version = parsed.version || 0;
    this.history = (parsed.history || []).map((h: any) => ({
      ...h,
      toolResults: new Map(h.toolResults || []),
    }));
  }

  /**
   * 获取结果（循环结束时调用）
   */
  getResult() {
    const state = this.state;
    return {
      success: state.status === 'completed' && !state.error,
      answer: state.answer,
      citations: state.citations,
      calculations: state.calculations,
      evaluation: state.evaluation,
      iterations: state.iteration,
      error: state.error,
      state: this.getState(),
    };
  }
}

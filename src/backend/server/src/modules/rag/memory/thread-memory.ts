/**
 * Thread Memory - 短期对话记忆
 * 管理单个对话线程内的消息历史和推理步骤
 */

import { v4 as uuidv4 } from 'uuid'
import { ReasoningStep } from '../types'

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  metadata?: Record<string, unknown>
  timestamp: number
}

export interface ToolExecution {
  id: string
  toolName: string
  args: Record<string, unknown>
  result?: unknown
  success: boolean
  error?: string
  latencyMs: number
  timestamp: number
}

export interface ThreadMemory {
  threadId: string
  messages: Message[]
  toolExecutions: ToolExecution[]
  reasoningSteps: ReasoningStep[]
  metadata: Record<string, unknown>
  createdAt: number
  updatedAt: number
}

export interface ThreadMemoryConfig {
  maxMessages?: number
  maxToolExecutions?: number
  maxReasoningSteps?: number
  messageRetentionDays?: number
}

const DEFAULT_CONFIG: Required<ThreadMemoryConfig> = {
  maxMessages: 100,
  maxToolExecutions: 50,
  maxReasoningSteps: 200,
  messageRetentionDays: 7
}

export class ThreadMemoryService {
  private store: Map<string, ThreadMemory>
  private config: Required<ThreadMemoryConfig>

  constructor(config: ThreadMemoryConfig = {}) {
    this.store = new Map()
    this.config = { ...DEFAULT_CONFIG, ...config }
  }

  private createEmptyMemory(threadId: string): ThreadMemory {
    const now = Date.now()
    return {
      threadId,
      messages: [],
      toolExecutions: [],
      reasoningSteps: [],
      metadata: {},
      createdAt: now,
      updatedAt: now
    }
  }

  getOrCreate(threadId: string): ThreadMemory {
    let memory = this.store.get(threadId)
    if (!memory) {
      memory = this.createEmptyMemory(threadId)
      this.store.set(threadId, memory)
    }
    return memory
  }

  has(threadId: string): boolean {
    return this.store.has(threadId)
  }

  addMessage(
    threadId: string,
    role: Message['role'],
    content: string,
    metadata?: Record<string, unknown>
  ): Message {
    const memory = this.getOrCreate(threadId)

    const message: Message = {
      id: uuidv4(),
      role,
      content,
      metadata,
      timestamp: Date.now()
    }

    memory.messages.push(message)

    if (memory.messages.length > this.config.maxMessages) {
      memory.messages = memory.messages.slice(-this.config.maxMessages)
    }

    memory.updatedAt = Date.now()
    this.store.set(threadId, memory)

    return message
  }

  addToolExecution(
    threadId: string,
    toolName: string,
    args: Record<string, unknown>,
    result?: unknown,
    success: boolean = true,
    error?: string,
    latencyMs: number = 0
  ): ToolExecution {
    const memory = this.getOrCreate(threadId)

    const execution: ToolExecution = {
      id: uuidv4(),
      toolName,
      args,
      result,
      success,
      error,
      latencyMs,
      timestamp: Date.now()
    }

    memory.toolExecutions.push(execution)

    if (memory.toolExecutions.length > this.config.maxToolExecutions) {
      memory.toolExecutions = memory.toolExecutions.slice(-this.config.maxToolExecutions)
    }

    memory.updatedAt = Date.now()
    this.store.set(threadId, memory)

    return execution
  }

  addReasoningStep(
    threadId: string,
    type: ReasoningStep['type'],
    content: string,
    toolUsed?: string,
    resultSummary?: string
  ): ReasoningStep {
    const memory = this.getOrCreate(threadId)

    const stepNumber = memory.reasoningSteps.length + 1

    const step: ReasoningStep = {
      id: uuidv4(),
      stepNumber,
      type,
      content,
      toolUsed,
      resultSummary,
      timestamp: Date.now()
    }

    memory.reasoningSteps.push(step)

    if (memory.reasoningSteps.length > this.config.maxReasoningSteps) {
      memory.reasoningSteps = memory.reasoningSteps.slice(-this.config.maxReasoningSteps)
    }

    memory.updatedAt = Date.now()
    this.store.set(threadId, memory)

    return step
  }

  getMessages(threadId: string, limit?: number): Message[] {
    const memory = this.store.get(threadId)
    if (!memory) return []

    if (limit) {
      return memory.messages.slice(-limit)
    }
    return [...memory.messages]
  }

  getToolExecutions(threadId: string, limit?: number): ToolExecution[] {
    const memory = this.store.get(threadId)
    if (!memory) return []

    if (limit) {
      return memory.toolExecutions.slice(-limit)
    }
    return [...memory.toolExecutions]
  }

  getReasoningSteps(threadId: string): ReasoningStep[] {
    const memory = this.store.get(threadId)
    if (!memory) return []

    return [...memory.reasoningSteps]
  }

  getContextForLLM(
    threadId: string,
    options: {
      includeMessages?: boolean
      includeToolExecutions?: boolean
      includeReasoning?: boolean
      maxTokens?: number
    } = {}
  ): string {
    const memory = this.store.get(threadId)
    if (!memory) return ''

    const {
      includeMessages = true,
      includeToolExecutions = true,
      includeReasoning = true,
      maxTokens = 4000
    } = options

    const parts: string[] = []

    if (includeReasoning && memory.reasoningSteps.length > 0) {
      parts.push('## 推理过程\n')
      for (const step of memory.reasoningSteps) {
        parts.push(`[${step.type}] ${step.content}`)
        if (step.toolUsed) {
          parts.push(`  工具: ${step.toolUsed}`)
        }
        if (step.resultSummary) {
          parts.push(`  结果: ${step.resultSummary}`)
        }
      }
      parts.push('')
    }

    if (includeToolExecutions && memory.toolExecutions.length > 0) {
      parts.push('## 工具执行\n')
      for (const exec of memory.toolExecutions.slice(-10)) {
        parts.push(`[${exec.toolName}] ${exec.success ? '成功' : '失败'}: ${JSON.stringify(exec.args)}`)
        if (exec.result) {
          parts.push(`  结果: ${JSON.stringify(exec.result).slice(0, 200)}`)
        }
      }
      parts.push('')
    }

    if (includeMessages) {
      parts.push('## 对话历史\n')
      for (const msg of memory.messages.slice(-20)) {
        parts.push(`[${msg.role}] ${msg.content}`)
      }
    }

    let context = parts.join('\n')

    if (maxTokens && context.length > maxTokens * 4) {
      context = context.slice(-maxTokens * 4)
    }

    return context
  }

  setMetadata(threadId: string, key: string, value: unknown): void {
    const memory = this.getOrCreate(threadId)
    memory.metadata[key] = value
    memory.updatedAt = Date.now()
    this.store.set(threadId, memory)
  }

  getMetadata(threadId: string, key: string): unknown {
    const memory = this.store.get(threadId)
    return memory?.metadata[key]
  }

  clear(threadId: string): void {
    this.store.delete(threadId)
  }

  clearAll(): void {
    this.store.clear()
  }

  getAllThreadIds(): string[] {
    return Array.from(this.store.keys())
  }

  getMemoryStats(): {
    totalThreads: number
    totalMessages: number
    totalToolExecutions: number
    totalReasoningSteps: number
  } {
    let totalMessages = 0
    let totalToolExecutions = 0
    let totalReasoningSteps = 0

    for (const memory of this.store.values()) {
      totalMessages += memory.messages.length
      totalToolExecutions += memory.toolExecutions.length
      totalReasoningSteps += memory.reasoningSteps.length
    }

    return {
      totalThreads: this.store.size,
      totalMessages,
      totalToolExecutions,
      totalReasoningSteps
    }
  }

  cleanupOldMemories(maxAgeMs: number = 7 * 24 * 60 * 60 * 1000): number {
    const now = Date.now()
    let cleaned = 0

    for (const [threadId, memory] of this.store.entries()) {
      if (now - memory.updatedAt > maxAgeMs) {
        this.store.delete(threadId)
        cleaned++
      }
    }

    return cleaned
  }
}

export function createThreadMemoryService(config?: ThreadMemoryConfig): ThreadMemoryService {
  return new ThreadMemoryService(config)
}

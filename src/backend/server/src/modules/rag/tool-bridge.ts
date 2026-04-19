/**
 * Tool Bridge - LangChain Tool 到 XState Event的桥接层
 * 负责Tool执行、事件发射和结果处理
 */

import { EventEmitter } from 'events'
import { DynamicStructuredTool } from '@langchain/core/tools'
import { z } from 'zod'
import { ToolResult, ToolArgs, RAGEvent } from './types'

export interface ToolBridgeConfig {
  eventEmitter?: EventEmitter
  timeout?: number
  retryAttempts?: number
  retryDelay?: number
}

export interface ToolExecutionContext {
  sessionId: string
  threadId: string
  iteration: number
  timestamp: number
}

export class ToolBridge {
  private tools: Map<string, DynamicStructuredTool>
  private eventEmitter: EventEmitter
  private timeout: number
  private retryAttempts: number
  private retryDelay: number

  constructor(config: ToolBridgeConfig = {}) {
    this.tools = new Map()
    this.eventEmitter = config.eventEmitter || new EventEmitter()
    this.timeout = config.timeout || 30000
    this.retryAttempts = config.retryAttempts || 3
    this.retryDelay = config.retryDelay || 1000
  }

  registerTool(tool: DynamicStructuredTool): void {
    this.tools.set(tool.name, tool)
    console.log(`[ToolBridge] Registered tool: ${tool.name}`)
  }

  registerTools(tools: DynamicStructuredTool[]): void {
    tools.forEach(tool => this.registerTool(tool))
  }

  getTool(name: string): DynamicStructuredTool | undefined {
    return this.tools.get(name)
  }

  getAvailableTools(): string[] {
    return Array.from(this.tools.keys())
  }

  async executeTool(
    toolName: string,
    args: ToolArgs,
    context: ToolExecutionContext
  ): Promise<ToolResult> {
    const tool = this.tools.get(toolName)

    if (!tool) {
      const errorResult: ToolResult = {
        success: false,
        error: `Tool not found: ${toolName}`,
        latencyMs: 0
      }
      this.emitToolEvent('tool_error', toolName, args, errorResult, context)
      return errorResult
    }

    const startTime = Date.now()

    try {
      this.emitToolEvent('tool_start', toolName, args, null, context)

      const result = await this.executeWithRetry(tool, args)

      const latencyMs = Date.now() - startTime

      const successResult: ToolResult = {
        success: true,
        data: result,
        latencyMs
      }

      this.emitToolEvent('tool_complete', toolName, args, successResult, context)

      return successResult
    } catch (error) {
      const latencyMs = Date.now() - startTime

      const errorResult: ToolResult = {
        success: false,
        error: error instanceof Error ? error.message : String(error),
        latencyMs
      }

      this.emitToolEvent('tool_error', toolName, args, errorResult, context)

      return errorResult
    }
  }

  private async executeWithRetry(
    tool: DynamicStructuredTool,
    args: ToolArgs,
    attempt: number = 1
  ): Promise<unknown> {
    try {
      const result = await this.executeWithTimeout(tool, args)
      return result
    } catch (error) {
      if (attempt < this.retryAttempts) {
        console.log(`[ToolBridge] Retry ${attempt}/${this.retryAttempts} for ${tool.name}`)
        await this.delay(this.retryDelay)
        return this.executeWithRetry(tool, args, attempt + 1)
      }
      throw error
    }
  }

  private async executeWithTimeout(
    tool: DynamicStructuredTool,
    args: ToolArgs
  ): Promise<unknown> {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error(`Tool ${tool.name} execution timeout after ${this.timeout}ms`))
      }, this.timeout)

      tool.invoke(args)
        .then(result => {
          clearTimeout(timer)
          resolve(result)
        })
        .catch(error => {
          clearTimeout(timer)
          reject(error)
        })
    })
  }

  private delay(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms))
  }

  private emitToolEvent(
    eventType: string,
    toolName: string,
    args: ToolArgs,
    result: ToolResult | null,
    context: ToolExecutionContext
  ): void {
    const event = {
      type: eventType,
      tool: toolName,
      args,
      result,
      context,
      timestamp: Date.now()
    }

    this.eventEmitter.emit('tool-event', event)
    this.eventEmitter.emit(`tool:${toolName}:${eventType}`, event)
  }

  onToolEvent(callback: (event: ToolBridgeEvent) => void): () => void {
    this.eventEmitter.on('tool-event', callback)
    return () => this.eventEmitter.off('tool-event', callback)
  }

  onToolSpecificEvent(
    toolName: string,
    eventType: string,
    callback: (event: ToolBridgeEvent) => void
  ): () => void {
    const fullEventName = `tool:${toolName}:${eventType}`
    this.eventEmitter.on(fullEventName, callback)
    return () => this.eventEmitter.off(fullEventName, callback)
  }

  /**
   * 执行工具并返回 XState 兼容的 RAGEvent
   * 用于直接将工具结果注入状态机
   */
  async executeToolAsRAGEvent(
    toolName: string,
    args: ToolArgs,
    context: ToolExecutionContext
  ): Promise<RAGEvent> {
    const result = await this.executeTool(toolName, args, context)

    if (result.success) {
      return {
        type: 'TOOL_COMPLETE',
        toolName,
        result: result.data,
      } as RAGEvent
    }

    return {
      type: 'TOOL_ERROR',
      toolName,
      error: result.error || 'Unknown tool error',
    } as RAGEvent
  }

  /**
   * 批量执行工具并返回 RAGEvent 数组
   */
  async executeAllToolsAsRAGEvents(
    toolCalls: Array<{ name: string; args: ToolArgs }>,
    context: ToolExecutionContext
  ): Promise<RAGEvent[]> {
    const events: RAGEvent[] = []
    for (const { name, args } of toolCalls) {
      const event = await this.executeToolAsRAGEvent(name, args, context)
      events.push(event)
    }
    return events
  }

  async executeAllTools(
    toolCalls: Array<{ name: string; args: ToolArgs }>,
    context: ToolExecutionContext
  ): Promise<Map<string, ToolResult>> {
    const results = new Map<string, ToolResult>()

    for (const { name, args } of toolCalls) {
      const result = await this.executeTool(name, args, context)
      results.set(name, result)
    }

    return results
  }

  async executeToolsParallel(
    toolCalls: Array<{ name: string; args: ToolArgs }>,
    context: ToolExecutionContext
  ): Promise<Map<string, ToolResult>> {
    const promises = toolCalls.map(async ({ name, args }) => {
      const result = await this.executeTool(name, args, context)
      return { name, result }
    })

    const settled = await Promise.all(promises)

    const results = new Map<string, ToolResult>()
    for (const { name, result } of settled) {
      results.set(name, result)
    }

    return results
  }

  validateArgs(toolName: string, args: unknown): { valid: boolean; errors?: string[] } {
    const tool = this.tools.get(toolName)

    if (!tool) {
      return { valid: false, errors: [`Tool not found: ${toolName}`] }
    }

    try {
      const schema = tool.schema as z.ZodObject<any>
      schema.parse(args)
      return { valid: true }
    } catch (error) {
      if (error instanceof z.ZodError) {
        return {
          valid: false,
          errors: error.errors.map(e => `${e.path.join('.')}: ${e.message}`)
        }
      }
      return { valid: false, errors: [String(error)] }
    }
  }

  getToolSchema(toolName: string): z.ZodObject<any> | null {
    const tool = this.tools.get(toolName)
    return tool?.schema as z.ZodObject<any> || null
  }
}

export interface ToolBridgeEvent {
  type: string
  tool: string
  args: ToolArgs
  result: ToolResult | null
  context: ToolExecutionContext
  timestamp: number
}

export function createToolBridge(config?: ToolBridgeConfig): ToolBridge {
  return new ToolBridge(config)
}

export function createToolsFromDefinitions(
  definitions: Array<{
    name: string
    description: string
    schema: z.ZodObject<any>
    func: (args: Record<string, unknown>) => Promise<unknown>
  }>
): DynamicStructuredTool[] {
  return definitions.map(def =>
    new DynamicStructuredTool({
      name: def.name,
      description: def.description,
      schema: def.schema,
      func: def.func
    })
  )
}

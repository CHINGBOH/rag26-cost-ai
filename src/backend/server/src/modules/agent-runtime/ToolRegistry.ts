/**
 * ToolRegistry - Agent 内建工具注册表
 * 
 * 设计原则：
 * 1. Agent 自带 ToolRegistry，工具是 Agent 的手脚
 * 2. 所有工具调用真实 API，绝不模拟数据
 * 3. 支持动态注册/卸载，留下扩展接口
 * 4. 自动记录调用结果到 Channel
 */

import { ToolDefinition, ToolArgs, ToolResult, RetrievedChunk } from './types';

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8000';
const RETRIEVAL_API_URL = process.env.RETRIEVAL_API_URL || 'http://localhost:8002';

export class ToolRegistry {
  private tools: Map<string, ToolDefinition> = new Map();

  constructor() {
    // 注册默认四库工具
    this.registerVectorSearch();
    this.registerKeywordSearch();
    this.registerGraphSearch();
    this.registerCalculator();
  }

  register(tool: ToolDefinition): void {
    this.tools.set(tool.name, tool);
  }

  unregister(name: string): void {
    this.tools.delete(name);
  }

  get(name: string): ToolDefinition | undefined {
    return this.tools.get(name);
  }

  list(): ToolDefinition[] {
    return Array.from(this.tools.values());
  }

  /**
   * 执行工具调用（真实 API）
   */
  async execute(name: string, args: ToolArgs): Promise<ToolResult> {
    const tool = this.tools.get(name);
    if (!tool) {
      return {
        success: false,
        error: `Tool "${name}" not found`,
        latencyMs: 0,
      };
    }

    const start = Date.now();
    try {
      const result = await tool.execute(args);
      return {
        ...result,
        latencyMs: Date.now() - start,
      };
    } catch (err) {
      return {
        success: false,
        error: err instanceof Error ? err.message : String(err),
        latencyMs: Date.now() - start,
      };
    }
  }

  // ==================== 默认工具实现（真实 API） ====================

  private registerVectorSearch(): void {
    this.register({
      name: 'vectorSearch',
      description: '语义向量检索，适用于概念理解、模糊查询、知识发现',
      execute: async (args: ToolArgs) => {
        const result = await this.callSearchAPI(args.query || '', args.topK || 10, 'vector');
        return result;
      },
    });
  }

  private registerKeywordSearch(): void {
    this.register({
      name: 'keywordSearch',
      description: '关键词精确匹配检索，适用于事实查询、定额子目、费率系数',
      execute: async (args: ToolArgs) => {
        const result = await this.callSearchAPI(args.query || '', args.topK || 10, 'keyword');
        return result;
      },
    });
  }

  private registerGraphSearch(): void {
    this.register({
      name: 'graphSearch',
      description: '知识图谱关系检索，适用于实体关联、跨版本对比、条文关联',
      execute: async (args: ToolArgs) => {
        const result = await this.callSearchAPI(args.query || '', args.topK || 10, 'graph');
        return result;
      },
    });
  }

  private registerCalculator(): void {
    this.register({
      name: 'calculator',
      description: '数学计算工具，支持基本运算、费率反推、价格差异计算',
      execute: async (args: ToolArgs) => {
        try {
          const expression = args.expression || '';
          // 安全过滤：只允许数字和运算符
          const sanitized = expression.replace(/[^0-9+\-*/().%\s]/g, '');
          if (!sanitized) {
            return { success: false, error: 'Empty or invalid expression', latencyMs: 0 };
          }
          const result = Function('"use strict"; return (' + sanitized + ')')();
          return {
            success: true,
            data: { result, expression: sanitized },
            latencyMs: 0,
          };
        } catch (e) {
          return {
            success: false,
            error: `Calculation failed: ${e instanceof Error ? e.message : String(e)}`,
            latencyMs: 0,
          };
        }
      },
    });
  }

  /**
   * 调用 Python 后端真实检索 API
   */
  private async callSearchAPI(
    query: string,
    topK: number,
    mode: 'vector' | 'keyword' | 'graph'
  ): Promise<ToolResult> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);

    try {
      const response = await fetch(`${PYTHON_API_URL}/api/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, top_k: topK, mode }),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        const text = await response.text();
        return {
          success: false,
          error: `Search API error: ${response.status} - ${text}`,
          latencyMs: 0,
        };
      }

      const data = (await response.json()) as any;
      const results = data.data?.results || [];

      // 转换为 RetrievedChunk 格式
      const chunks: RetrievedChunk[] = results.map((r: any) => ({
        id: r.chunk_id || r.id || `chunk_${Math.random().toString(36).slice(2)}`,
        content: r.content || '',
        source: r.doc_id || r.source || 'unknown',
        database: mode as any,
        score: r.score || 0,
        metadata: r.metadata || {},
      }));

      return {
        success: true,
        data: { chunks, total: chunks.length, query },
        latencyMs: 0,
      };
    } catch (err) {
      clearTimeout(timeoutId);
      return {
        success: false,
        error: err instanceof Error ? err.message : String(err),
        latencyMs: 0,
      };
    }
  }
}

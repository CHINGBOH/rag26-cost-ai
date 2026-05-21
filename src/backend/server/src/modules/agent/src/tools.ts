import { z } from 'zod'
import { DynamicStructuredTool } from '@langchain/core/tools'
import { IndexReference } from './types'
import { runtimeConfig } from '../../../config/runtime'
import { evaluateArithmetic } from './code_pipeline_client'

function getPythonApiUrl(): string {
  return runtimeConfig.services.retrievalApiUrl
}

async function callSearchAPI(
  query: string,
  topK: number,
  sourceDb: string
): Promise<string> {
  try {
    const retrievalApiUrl = getPythonApiUrl()

    // 搜索 canonical 入口在 retrieval-service；优先 /api/search，失败再降级到 /api/v1/search。
    let response = await fetch(`${retrievalApiUrl}/api/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        top_k: topK,
        mode: sourceDb === 'vector' ? 'hybrid' : sourceDb,
        filters: {},
      }),
    })

    let data: any
    if (!response.ok && response.status === 404) {
      // 降级到兼容接口
      response = await fetch(`${retrievalApiUrl}/api/v1/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          top_k: topK,
          use_rerank: true,
          use_llm: false,
        }),
      })
    }

    if (!response.ok) {
      const errorText = await response.text()
      console.warn(`[${sourceDb}Search] Retrieval backend error: ${response.status} - ${errorText}`)
      return `[${sourceDb}Search] 检索失败: ${response.status}`
    }

    const wrapped = await response.json() as any
    data = wrapped.data || wrapped

    const results = (data.results || []) as any[]

    if (results.length === 0) {
      return `[${sourceDb}Search] 未找到与 "${query}" 相关的内容。`
    }

    // 返回对 LLM 友好的文本格式（而非原始 JSON）
    const lines: string[] = [
      `[${sourceDb}Search] 找到 ${results.length} 条相关结果：`,
      '',
    ]
    results.forEach((r, idx) => {
      lines.push(`[${idx + 1}] 来源: ${r.source || 'unknown'}`)
      lines.push(`    内容: ${(r.content || '').replace(/\n+/g, ' ').slice(0, 300)}`)
      lines.push(`    相关度: ${(r.score || 0).toFixed(2)}`)
      lines.push('')
    })

    return lines.join('\n')
  } catch (error) {
    console.warn(`[${sourceDb}Search] Failed to call retrieval backend:`, error)
    return `[${sourceDb}Search] 调用失败: ${String(error)}`
  }
}

export function createVectorSearchTool() {
  return new DynamicStructuredTool({
    name: 'vectorSearch',
    description: '使用向量相似度搜索，适用于语义查询、模糊匹配和知识发现',
    schema: z.object({
      query: z.string().describe('搜索查询语句'),
      topK: z.number().default(10).describe('返回结果数量')
    }),
    func: async ({ query, topK }) => {
      return await callSearchAPI(query, topK, 'vector')
    }
  })
}

export function createKeywordSearchTool() {
  return new DynamicStructuredTool({
    name: 'keywordSearch',
    description: '使用关键词精确匹配搜索，适用于事实查询、精确匹配和数据检索',
    schema: z.object({
      query: z.string().describe('关键词查询'),
      topK: z.number().default(10).describe('返回结果数量')
    }),
    func: async ({ query, topK }) => {
      return await callSearchAPI(query, topK, 'keyword')
    }
  })
}

export function createGraphSearchTool() {
  return new DynamicStructuredTool({
    name: 'graphSearch',
    description: '使用知识图谱查询，适用于关系发现、实体关联和推理任务',
    schema: z.object({
      query: z.string().describe('图谱查询语句'),
      topK: z.number().default(10).describe('返回结果数量')
    }),
    func: async ({ query, topK }) => {
      return await callSearchAPI(query, topK, 'graph')
    }
  })
}

export function createCalculatorTool() {
  return new DynamicStructuredTool({
    name: 'calculator',
    description: '数学计算工具，支持基本运算、统计计算',
    schema: z.object({
      expression: z.string().describe('数学表达式，如: 2 + 3 * 4')
    }),
    func: async ({ expression }) => {
      const result = evaluateArithmetic(expression)
      if (result.ok) {
        return `计算结果: ${result.value}\n表达式: ${expression}`
      }
      return `计算失败: ${result.error}`
    }
  })
}

export function createFourDatabaseTools() {
  return [
    createVectorSearchTool(),
    createKeywordSearchTool(),
    createGraphSearchTool(),
    createCalculatorTool()
  ]
}

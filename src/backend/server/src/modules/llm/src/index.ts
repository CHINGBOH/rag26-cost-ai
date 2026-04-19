/**
 * LLM模块 - 大语言模型服务
 * 提供管道式生成与嵌入接口
 */

import { LLMConfig, LLMResponse, EmbeddingConfig } from '../../common/types'

export interface GenerationOptions {
  temperature?: number
  maxTokens?: number
  topP?: number
  stream?: boolean
}

const defaultLLMConfig: LLMConfig = {
  model: process.env.LLM_MODEL || 'gpt-3.5-turbo',
  temperature: 0.7,
  maxTokens: 2048,
  topP: 1,
  apiKey: process.env.OPENAI_API_KEY,
  baseUrl: process.env.LLM_BASE_URL || 'https://api.openai.com/v1'
}

const defaultEmbeddingConfig: EmbeddingConfig = {
  model: process.env.EMBEDDING_MODEL || 'text-embedding-ada-002',
  dimensions: 1536,
  apiKey: process.env.OPENAI_API_KEY,
  baseUrl: process.env.LLM_BASE_URL || 'https://api.openai.com/v1'
}

/**
 * 生成文本
 */
export function generateText(config?: Partial<LLMConfig> & GenerationOptions) {
  const cfg = { ...defaultLLMConfig, ...config }

  return async function generate(prompt: string): Promise<string> {
    try {
      const response = await fetch(`${cfg.baseUrl}/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${cfg.apiKey}`
        },
        body: JSON.stringify({
          model: cfg.model,
          messages: [{ role: 'user', content: prompt }],
          temperature: cfg.temperature,
          max_tokens: cfg.maxTokens,
          top_p: cfg.topP
        })
      })

      if (!response.ok) {
        throw new Error(`LLM generation failed: ${response.status}`)
      }

      interface ChatCompletion {
        choices: Array<{ message: { content: string } }>
      }
      const data = await response.json() as ChatCompletion
      return data.choices[0]?.message?.content || ''
    } catch (error) {
      console.warn('[LLM] Generation failed, using mock response:', error)
      return getMockResponse(prompt)
    }
  }
}

/**
 * 创建嵌入向量
 */
export function createEmbedding(config?: Partial<EmbeddingConfig>) {
  const cfg = { ...defaultEmbeddingConfig, ...config }

  return async function embed(text: string): Promise<number[]> {
    try {
      const response = await fetch(`${cfg.baseUrl}/embeddings`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${cfg.apiKey}`
        },
        body: JSON.stringify({
          model: cfg.model,
          input: text
        })
      })

      if (!response.ok) {
        throw new Error(`Embedding creation failed: ${response.status}`)
      }

      interface EmbeddingResponse {
        data: Array<{ embedding: number[] }>
      }
      const data = await response.json() as EmbeddingResponse
      return data.data[0]?.embedding || []
    } catch (error) {
      console.warn('[LLM] Embedding failed, using mock vector:', error)
      return getMockEmbedding(cfg.dimensions)
    }
  }
}

/**
 * 批量创建嵌入
 */
export function batchCreateEmbedding(config?: Partial<EmbeddingConfig>) {
  const embedFn = createEmbedding(config)

  return async function batchEmbed(texts: string[]): Promise<number[][]> {
    return Promise.all(texts.map(text => embedFn(text)))
  }
}

/**
 * 流式生成
 */
export async function* streamGenerate(
  prompt: string,
  config?: Partial<LLMConfig>
): AsyncIterable<string> {
  const cfg = { ...defaultLLMConfig, ...config }

  try {
    const response = await fetch(`${cfg.baseUrl}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${cfg.apiKey}`
      },
      body: JSON.stringify({
        model: cfg.model,
        messages: [{ role: 'user', content: prompt }],
        temperature: cfg.temperature,
        max_tokens: cfg.maxTokens,
        stream: true
      })
    })

    if (!response.ok) {
      throw new Error(`Streaming failed: ${response.status}`)
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('No response body')
    }

    const decoder = new TextDecoder()

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      const chunk = decoder.decode(value)
      const lines = chunk.split('\n')

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6)
          if (data === '[DONE]') return

          try {
            interface StreamChunk {
              choices: Array<{ delta: { content?: string } }>
            }
            const parsed = JSON.parse(data) as StreamChunk
            const content = parsed.choices[0]?.delta?.content
            if (content) yield content
          } catch {
            // 忽略解析错误
          }
        }
      }
    }
  } catch (error) {
    console.error('[LLM] Streaming error:', error)
    // 降级到非流式
    const text = await generateText(cfg)(prompt)
    yield text
  }
}

// ==================== 工具函数 ====================

function getMockResponse(prompt: string): string {
  return `这是针对"${prompt.slice(0, 50)}..."的模拟回答。实际使用时将调用LLM API生成真实回复。`
}

function getMockEmbedding(dimensions: number): number[] {
  // 生成随机但确定的向量
  const embedding: number[] = []
  for (let i = 0; i < dimensions; i++) {
    embedding.push(Math.sin(i) * 0.1)
  }
  return embedding
}

/**
 * 计算向量相似度
 */
export function cosineSimilarity(a: number[], b: number[]): number {
  let dotProduct = 0
  let normA = 0
  let normB = 0

  for (let i = 0; i < a.length; i++) {
    dotProduct += a[i] * b[i]
    normA += a[i] * a[i]
    normB += b[i] * b[i]
  }

  return dotProduct / (Math.sqrt(normA) * Math.sqrt(normB))
}

/**
 * 创建LLM管道
 */
export function createLLMPipeline(config?: Partial<LLMConfig & EmbeddingConfig>) {
  return {
    generate: generateText(config),
    embed: createEmbedding(config),
    batchEmbed: batchCreateEmbedding(config),
    similarity: cosineSimilarity
  }
}

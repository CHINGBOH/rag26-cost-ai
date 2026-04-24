/**
 * 检索模块 - 基于 LangChain 的多路召回 + 精排 + 分数融合
 * 提供管道式检索接口
 */

import { Document } from '@langchain/core/documents'
import { BaseRetriever } from '@langchain/core/retrievers'
import { Embeddings } from '@langchain/core/embeddings'
import { OpenAIEmbeddings } from '@langchain/openai'
import { QdrantVectorStore } from '@langchain/qdrant'
import { z } from 'zod'
import { pipe } from '../../common/pipe'
import { 
  RetrievedChunk, 
  SubQuery, 
  RoundEvaluation,
} from '../../common/types'

// ==================== Schema 定义 ====================

export const RetrievalConfigSchema = z.object({
  qdrantUrl: z.string().default('http://localhost:6333'),
  openaiApiKey: z.string().optional(),
  embeddingModel: z.string().default('text-embedding-3-small'),
  timeout: z.number().default(30000)
})

export type RetrievalConfig = z.infer<typeof RetrievalConfigSchema>

export const SearchOptionsSchema = z.object({
  topK: z.number().default(10),
  enableRerank: z.boolean().default(true),
  enableFusion: z.boolean().default(true),
  vectorWeight: z.number().default(0.6),
  textWeight: z.number().default(0.4)
})

export type SearchOptions = z.infer<typeof SearchOptionsSchema>

// ==================== 向量存储管理 ====================

class VectorStoreManager {
  private qdrantStore?: QdrantVectorStore
  private embeddings: Embeddings
  private config: RetrievalConfig

  constructor(config: Partial<RetrievalConfig> = {}) {
    this.config = RetrievalConfigSchema.parse({
      qdrantUrl: process.env.QDRANT_URL || 'http://localhost:6333',
      openaiApiKey: process.env.OPENAI_API_KEY,
      ...config
    })

    this.embeddings = new OpenAIEmbeddings({
      modelName: this.config.embeddingModel,
      openAIApiKey: this.config.openaiApiKey
    })
  }

  async initialize(): Promise<void> {
    // 初始化 Qdrant（仅用于 session_context，文档检索已迁移至 PG）
    try {
      this.qdrantStore = await QdrantVectorStore.fromExistingCollection(
        this.embeddings,
        {
          url: this.config.qdrantUrl,
          collectionName: 'session_context'
        }
      )
    } catch (error) {
      console.warn('[Retrieval] Qdrant initialization failed:', error)
    }
  }

  getQdrantStore(): QdrantVectorStore {
    if (!this.qdrantStore) throw new Error('Qdrant not initialized')
    return this.qdrantStore
  }
}

// ==================== 检索器工厂 ====================

class RetrieverFactory {
  constructor(private storeManager: VectorStoreManager) {}

  createVectorRetriever(topK: number = 10): BaseRetriever {
    return this.storeManager.getQdrantStore().asRetriever({ k: topK }) as unknown as BaseRetriever
  }

  createTextRetriever(topK: number = 5): BaseRetriever {
    // PG 全文检索替代 Neo4j（由 Python 后端实际执行）
    // 此处返回空检索器，实际检索通过 Python API 完成
    const retriever: BaseRetriever = {
      lc_namespace: ['custom', 'retrievers'],
      lc_secrets: {},
      lc_attributes: {},
      lc_aliases: {},
      invoke: async (_query: string) => {
        return []
      }
    } as unknown as BaseRetriever
    return retriever
  }
}

// ==================== 文档处理 ====================

export function createTextSplitter(chunkSize: number = 512, chunkOverlap: number = 50) {
  // 简化版文本分割器
  return {
    splitDocuments: async (docs: Document[]): Promise<Document[]> => {
      const chunks: Document[] = []
      for (const doc of docs) {
        const text = doc.pageContent
        const separator = '\n\n'
        const parts = text.split(separator)
        
        for (let i = 0; i < parts.length; i++) {
          const part = parts[i]
          if (part.length > chunkSize) {
            // 进一步分割
            const subParts = part.match(new RegExp(`.{1,${chunkSize}}`, 'g')) || []
            for (const subPart of subParts) {
              chunks.push(new Document({
                pageContent: subPart,
                metadata: { ...doc.metadata, chunk: true }
              }))
            }
          } else if (part.trim()) {
            chunks.push(new Document({
              pageContent: part,
              metadata: { ...doc.metadata, chunk: true }
            }))
  }
}


      }
      return chunks
    }
  }
}

// ==================== 管道操作符 ====================

export function decompose(config?: { model?: string; apiKey?: string }) {
  return async function decomposeQuery(query: string): Promise<SubQuery[]> {
    const subQueries: SubQuery[] = []

    subQueries.push({
      id: `sq_${Date.now()}_1`,
      query: `${query} 基础概念定义`,
      targetDB: 'vector',
      status: 'pending'
    })

    subQueries.push({
      id: `sq_${Date.now()}_2`,
      query: `${query} 实现方法 技术细节`,
      targetDB: 'vector',
      status: 'pending'
    })

    if (/如何|怎么|怎样|案例|示例/.test(query)) {
      subQueries.push({
        id: `sq_${Date.now()}_3`,
        query: `${query} 实际案例 应用示例`,
        targetDB: 'vector',
        status: 'pending'
      })
    }

    return subQueries
  }
}

export function vectorSearch(config?: Partial<RetrievalConfig> & { topK?: number }) {
  return async function searchVector(query: string): Promise<RetrievedChunk[]> {
    const manager = new VectorStoreManager(config)
    await manager.initialize()

    const factory = new RetrieverFactory(manager)
    const retriever = factory.createVectorRetriever(config?.topK || 10)
    
    const documents = await retriever.invoke(query)
    
    return documents.map((doc, idx) => ({
      id: `vec_${idx}_${Date.now()}`,
      content: doc.pageContent,
      source: String(doc.metadata.source || 'unknown'),
      database: 'vector' as const,
      score: Number(doc.metadata.score || 0),
      metadata: doc.metadata
    }))
  }
}

export function keywordSearch(config?: Partial<RetrievalConfig> & { topK?: number }) {
  return async function searchKeyword(query: string): Promise<RetrievedChunk[]> {
    // TODO: implement keyword search using Elasticsearch or similar
    console.warn('[Retrieval] keywordSearch not implemented, returning empty results')
    return []
  }
}

export function graphSearch(_config?: Partial<RetrievalConfig> & { topK?: number }) {
  return async function searchGraph(_query: string): Promise<RetrievedChunk[]> {
    // Neo4j has been removed; graph search is no longer available
    return []
  }
}

export function textSearch(config?: Partial<RetrievalConfig> & { topK?: number }) {
  return async function searchText(_query: string): Promise<RetrievedChunk[]> {
    // PG 全文检索由 Python 后端执行，Node 层直接代理
    return []
  }
}

export function retrieve(config?: Partial<RetrievalConfig> & Partial<SearchOptions>) {
  const options = SearchOptionsSchema.parse({
    topK: config?.topK || 10,
    enableRerank: config?.enableRerank ?? true,
    enableFusion: config?.enableFusion ?? true,
    vectorWeight: config?.vectorWeight ?? 0.6,
    textWeight: config?.textWeight ?? 0.4,
    ...config
  })

  return async function unifiedRetrieve(query: string): Promise<RetrievedChunk[]> {
    console.log(`[Retrieval] 开始召回: "${query.slice(0, 50)}..."`)

    // Node 层检索已简化，实际混合检索由 Python 后端 (UnifiedPipeline) 执行
    const vectorResults = await vectorSearch({ ...config, topK: options.topK })(query)

    console.log(`[Retrieval] 召回完成: ${vectorResults.length} 条结果`)
    return vectorResults.slice(0, options.topK)
  }
}

export function rerank(config?: { apiKey?: string; topK?: number; model?: string }) {
  const topK = config?.topK || 10

  return async function doRerank(
    query: string, 
    chunks: RetrievedChunk[]
  ): Promise<RetrievedChunk[]> {
    if (chunks.length === 0) return chunks

    console.log(`[Rerank] 对 ${chunks.length} 条结果重排序`)

    return chunks
      .sort((a, b) => b.score - a.score)
      .slice(0, topK)
  }
}

export const FusionWeightsSchema = z.object({
  rerank: z.number().default(0.5),
  vector: z.number().default(0.6),
  text: z.number().default(0.4),
  graph: z.number().default(0.0)
})

export type FusionWeights = z.infer<typeof FusionWeightsSchema>

export function fuseScores(weights?: Partial<FusionWeights>) {
  const w = FusionWeightsSchema.parse({
    rerank: 0.5,
    vector: 0.6,
    text: 0.4,
    ...weights
  })

  return function mergeResults(results: RetrievedChunk[][]): RetrievedChunk[] {
    const k = 60
    const scoreMap = new Map<string, { chunk: RetrievedChunk; score: number }>()

    results.forEach((chunks, listIdx) => {
      const weight = listIdx === 0 ? w.vector : w.text

      chunks.forEach((chunk, rank) => {
        const rrfScore = weight * (1 / (k + rank + 1))
        
        if (scoreMap.has(chunk.id)) {
          const existing = scoreMap.get(chunk.id)!
          existing.score += rrfScore
        } else {
          scoreMap.set(chunk.id, { chunk, score: rrfScore })
        }
      })
    })

    return Array.from(scoreMap.values())
      .sort((a, b) => b.score - a.score)
      .map(({ chunk, score }) => ({
        ...chunk,
        score,
        metadata: {
          ...chunk.metadata,
          fusedScore: score
        }
      }))
  }
}

export function evaluate() {
  return function evaluateChunks(
    query: string,
    chunks: RetrievedChunk[],
    answer?: string
  ): RoundEvaluation {
    const avgScore = chunks.length > 0
      ? chunks.reduce((sum, c) => sum + c.score, 0) / chunks.length
      : 0

    const sources = new Set(chunks.map(c => c.source))
    const sourceDiversity = Math.min(sources.size / 3, 1.0)

    const databases = new Set(chunks.map(c => c.database))
    const dbDiversity = databases.size / 2
    const diversity = sourceDiversity

    const totalContentLength = chunks.reduce((sum, c) => sum + c.content.length, 0)
    const completeness = Math.min(totalContentLength / 2000, 0.95)

    const variance = chunks.length > 0
      ? chunks.reduce((sum, c) => sum + Math.pow(c.score - avgScore, 2), 0) / chunks.length
      : 0
    const consistency = Math.max(0.5, 1 - variance)

    const citationCount = answer ? (answer.match(/\[\d+\]/g) || []).length : 0
    const factConsistency = Math.min(0.5 + citationCount * 0.1, 0.95)

    return {
      completeness,
      consistency,
      confidence: avgScore,
      informationGain: diversity * avgScore,
      sourceDiversity: diversity,
      factConsistency,
      coverageEstimate: Math.min(avgScore * diversity * 1.5, 0.95)
    }
  }
}

export function indexDocuments(config?: Partial<RetrievalConfig>) {
  return async function index(docs: Document[]): Promise<void> {
    const manager = new VectorStoreManager(config)
    await manager.initialize()

    const splitter = createTextSplitter()
    const chunks = await splitter.splitDocuments(docs)

    await manager.getQdrantStore().addDocuments(chunks)

    console.log(`[Retrieval] 索引完成: ${chunks.length} 个 chunks`)
  }
}

export async function healthCheck(config?: Partial<RetrievalConfig>): Promise<{
  healthy: boolean
  services: Record<string, boolean>
}> {
  const cfg = RetrievalConfigSchema.parse({
    qdrantUrl: process.env.QDRANT_URL || 'http://localhost:6333',
    ...config
  })

  const services: Record<string, boolean> = {}

  try {
    const qdrantRes = await fetch(`${cfg.qdrantUrl}/healthz`)
    services.qdrant = qdrantRes.ok
  } catch {
    services.qdrant = false
  }

  return {
    healthy: services.qdrant,
    services
  }
}

export function createRetrievalPipeline(config?: Partial<RetrievalConfig> & Partial<SearchOptions>) {
  return {
    decompose: decompose(),
    vectorSearch: vectorSearch(config),
    keywordSearch: keywordSearch(config),
    graphSearch: graphSearch(config),
    textSearch: textSearch(config),
    retrieve: retrieve(config),
    rerank: rerank(config),
    fuseScores: (w?: Partial<FusionWeights>) => fuseScores(w),
    evaluate: evaluate(),
    indexDocuments: indexDocuments(config),
    healthCheck: () => healthCheck(config)
  }
}

export { CascadeRetrievalService, createCascadeRetrieval } from './cascade-retrieval';
export type { CascadeSearchOptions, CascadeSearchResult, ChunkResult, GraphEntity, KeywordContext, StructuredData } from './cascade-retrieval';

export { QueryFusionRetriever, createQueryFusionRetriever } from './query-fusion';
export type { RetrievalResult, FusionNode, FusionConfig } from './query-fusion';

/**
 * Session Memory - 长期知识存储
 * 跨会话的记忆管理，支持向量检索
 */

import { Embeddings } from '@langchain/core/embeddings'
import { VectorStore } from '@langchain/core/vectorstores'

export interface MemoryEntry {
  id: string
  content: string
  embedding?: number[]
  metadata: {
    source: string
    sourceType: 'document' | 'conversation' | 'extracted' | 'manual'
    tags: string[]
    accessCount: number
    lastAccessedAt: number
    createdAt: number
    expiresAt?: number
    [key: string]: unknown
  }
}

export interface MemorySearchResult {
  entry: MemoryEntry
  score: number
  highlights: string[]
}

export interface SessionMemoryConfig {
  embeddings?: Embeddings
  vectorStore?: VectorStore
  maxEntries?: number
  defaultTtl?: number
  similarityThreshold?: number
}

const DEFAULT_CONFIG = {
  maxEntries: 10000,
  defaultTtl: 30 * 24 * 60 * 60 * 1000,
  similarityThreshold: 0.7
}

export class SessionMemoryService {
  private memoryStore: Map<string, MemoryEntry>
  private config: typeof DEFAULT_CONFIG
  private embeddings?: Embeddings
  private vectorStore?: VectorStore

  constructor(config: SessionMemoryConfig = {}) {
    this.memoryStore = new Map()
    this.config = {
      maxEntries: config.maxEntries ?? DEFAULT_CONFIG.maxEntries,
      defaultTtl: config.defaultTtl ?? DEFAULT_CONFIG.defaultTtl,
      similarityThreshold: config.similarityThreshold ?? DEFAULT_CONFIG.similarityThreshold
    }
    this.embeddings = config.embeddings
    this.vectorStore = config.vectorStore
  }

  async storeEntry(
    content: string,
    metadata: Partial<MemoryEntry['metadata']> & { source: string }
  ): Promise<string> {
    const id = `mem_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`

    let embedding: number[] | undefined
    if (this.embeddings && this.vectorStore) {
      try {
        embedding = await this.embeddings.embedQuery(content)
      } catch (error) {
        console.warn('[SessionMemory] Failed to generate embedding:', error)
      }
    }

    const entry: MemoryEntry = {
      id,
      content,
      embedding,
      metadata: {
        source: metadata.source,
        sourceType: metadata.sourceType || 'manual',
        tags: metadata.tags || [],
        accessCount: 0,
        lastAccessedAt: Date.now(),
        createdAt: Date.now(),
        expiresAt: metadata.expiresAt || (Date.now() + this.config.defaultTtl)
      }
    }

    this.memoryStore.set(id, entry)

    if (this.vectorStore && embedding) {
      try {
        await this.vectorStore.addVectors([embedding], [{
          pageContent: content,
          metadata: { memoryId: id, ...metadata }
        }])
      } catch (error) {
        console.warn('[SessionMemory] Failed to add to vector store:', error)
      }
    }

    if (this.memoryStore.size > this.config.maxEntries) {
      this.evictOldest()
    }

    return id
  }

  async recall(
    query: string,
    topK: number = 5,
    filter?: Record<string, unknown>
  ): Promise<MemorySearchResult[]> {
    let results: MemorySearchResult[] = []

    if (this.vectorStore && this.embeddings) {
      try {
        const queryEmbedding = await this.embeddings.embedQuery(query)

        const vectorResults = await this.vectorStore.similaritySearchVectorWithScore(
          queryEmbedding,
          topK * 2
        )

        for (const [doc, score] of vectorResults) {
          const memoryId = doc.metadata?.memoryId as string
          const entry = this.memoryStore.get(memoryId)

          if (entry && score <= (1 - this.config.similarityThreshold)) {
            this.updateAccessStats(memoryId)

            results.push({
              entry,
              score: 1 - score,
              highlights: this.generateHighlights(entry.content, query)
            })
          }
        }
      } catch (error) {
        console.warn('[SessionMemory] Vector search failed, falling back to text search:', error)
      }
    }

    if (results.length < topK) {
      const textResults = this.textSearch(query, topK, filter)
      for (const result of textResults) {
        if (!results.find(r => r.entry.id === result.entry.id)) {
          results.push(result)
        }
        if (results.length >= topK) break
      }
    }

    results = results.slice(0, topK)

    return results
  }

  private textSearch(
    query: string,
    topK: number = 5,
    filter?: Record<string, unknown>
  ): MemorySearchResult[] {
    const queryLower = query.toLowerCase()
    const queryTerms = queryLower.split(/\s+/).filter(t => t.length > 2)

    const scored: Array<{ entry: MemoryEntry; score: number }> = []

    for (const entry of this.memoryStore.values()) {
      if (filter) {
        let matchesFilter = true
        for (const [key, value] of Object.entries(filter)) {
          if (entry.metadata[key] !== value) {
            matchesFilter = false
            break
          }
        }
        if (!matchesFilter) continue
      }

      if (entry.metadata.expiresAt && Date.now() > entry.metadata.expiresAt) {
        continue
      }

      let score = 0
      const contentLower = entry.content.toLowerCase()

      for (const term of queryTerms) {
        if (contentLower.includes(term)) {
          score += 1
          if (contentLower.startsWith(term)) {
            score += 2
          }
        }
      }

      for (const tag of entry.metadata.tags) {
        if (queryTerms.some(term => tag.toLowerCase().includes(term))) {
          score += 0.5
        }
      }

      if (score > 0) {
        score = score / (queryTerms.length + 1)

        scored.push({ entry, score })
      }
    }

    scored.sort((a, b) => b.score - a.score)

    return scored.slice(0, topK).map(({ entry, score }) => ({
      entry,
      score,
      highlights: this.generateHighlights(entry.content, query)
    }))
  }

  private generateHighlights(content: string, query: string): string[] {
    const highlights: string[] = []
    const queryTerms = query.toLowerCase().split(/\s+/).filter(t => t.length > 2)
    const contentLower = content.toLowerCase()

    for (const term of queryTerms) {
      const index = contentLower.indexOf(term)
      if (index !== -1) {
        const start = Math.max(0, index - 30)
        const end = Math.min(content.length, index + term.length + 30)
        highlights.push('...' + content.slice(start, end) + '...')
      }
    }

    return highlights.slice(0, 3)
  }

  async updateEntry(id: string, updates: Partial<Pick<MemoryEntry, 'content' | 'metadata'>>): Promise<boolean> {
    const entry = this.memoryStore.get(id)
    if (!entry) return false

    if (updates.content !== undefined) {
      entry.content = updates.content

      if (this.embeddings) {
        try {
          entry.embedding = await this.embeddings.embedQuery(updates.content)
        } catch (error) {
          console.warn('[SessionMemory] Failed to regenerate embedding:', error)
        }
      }
    }

    if (updates.metadata) {
      entry.metadata = { ...entry.metadata, ...updates.metadata }
    }

    entry.metadata.lastAccessedAt = Date.now()
    this.memoryStore.set(id, entry)

    return true
  }

  private updateAccessStats(id: string): void {
    const entry = this.memoryStore.get(id)
    if (entry) {
      entry.metadata.accessCount++
      entry.metadata.lastAccessedAt = Date.now()
      this.memoryStore.set(id, entry)
    }
  }

  async getRelevantMemories(
    context: string,
    threshold: number = 0.6,
    limit: number = 5
  ): Promise<MemoryEntry[]> {
    const results = await this.recall(context, limit)
    return results
      .filter(r => r.score >= threshold)
      .map(r => r.entry)
  }

  get(id: string): MemoryEntry | undefined {
    const entry = this.memoryStore.get(id)

    if (entry) {
      if (entry.metadata.expiresAt && Date.now() > entry.metadata.expiresAt) {
        this.memoryStore.delete(id)
        return undefined
      }

      this.updateAccessStats(id)
    }

    return entry
  }

  delete(id: string): boolean {
    return this.memoryStore.delete(id)
  }

  deleteByTag(tag: string): number {
    let deleted = 0

    for (const [id, entry] of this.memoryStore.entries()) {
      if (entry.metadata.tags.includes(tag)) {
        this.memoryStore.delete(id)
        deleted++
      }
    }

    return deleted
  }

  addTag(id: string, tag: string): boolean {
    const entry = this.memoryStore.get(id)
    if (!entry) return false

    if (!entry.metadata.tags.includes(tag)) {
      entry.metadata.tags.push(tag)
      this.memoryStore.set(id, entry)
    }

    return true
  }

  getByTag(tag: string): MemoryEntry[] {
    return Array.from(this.memoryStore.values()).filter(
      entry => entry.metadata.tags.includes(tag)
    )
  }

  getAllTags(): string[] {
    const tagSet = new Set<string>()

    for (const entry of this.memoryStore.values()) {
      for (const tag of entry.metadata.tags) {
        tagSet.add(tag)
      }
    }

    return Array.from(tagSet)
  }

  private evictOldest(): void {
    let oldest: { id: string; timestamp: number } | null = null

    for (const [id, entry] of this.memoryStore.entries()) {
      if (!oldest || entry.metadata.lastAccessedAt < oldest.timestamp) {
        oldest = { id, timestamp: entry.metadata.lastAccessedAt }
      }
    }

    if (oldest) {
      this.memoryStore.delete(oldest.id)
    }
  }

  clear(): void {
    this.memoryStore.clear()
  }

  getStats(): {
    totalEntries: number
    entriesBySourceType: Record<string, number>
    totalAccessCount: number
    averageAccessCount: number
    tags: string[]
    oldestEntry: number
    newestEntry: number
  } {
    const entries = Array.from(this.memoryStore.values())

    const entriesBySourceType: Record<string, number> = {}
    let totalAccessCount = 0
    let oldestTimestamp = Date.now()
    let newestTimestamp = 0

    for (const entry of entries) {
      const sourceType = entry.metadata.sourceType
      entriesBySourceType[sourceType] = (entriesBySourceType[sourceType] || 0) + 1

      totalAccessCount += entry.metadata.accessCount

      if (entry.metadata.createdAt < oldestTimestamp) {
        oldestTimestamp = entry.metadata.createdAt
      }
      if (entry.metadata.createdAt > newestTimestamp) {
        newestTimestamp = entry.metadata.createdAt
      }
    }

    return {
      totalEntries: entries.length,
      entriesBySourceType,
      totalAccessCount,
      averageAccessCount: entries.length > 0 ? totalAccessCount / entries.length : 0,
      tags: this.getAllTags(),
      oldestEntry: oldestTimestamp,
      newestEntry: newestTimestamp
    }
  }

  cleanupExpired(): number {
    const now = Date.now()
    let cleaned = 0

    for (const [id, entry] of this.memoryStore.entries()) {
      if (entry.metadata.expiresAt && now > entry.metadata.expiresAt) {
        this.memoryStore.delete(id)
        cleaned++
      }
    }

    return cleaned
  }
}

export function createSessionMemoryService(config?: SessionMemoryConfig): SessionMemoryService {
  return new SessionMemoryService(config)
}

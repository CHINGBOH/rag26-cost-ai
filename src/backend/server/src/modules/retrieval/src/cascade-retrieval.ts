/**
 * 级联检索服务 - Cascaded Retrieval
 *
 * 检索流程:
 * 1. Qdrant (向量库) - 语义匹配, 返回 chunk_ids + 语义得分
 * 2. Neo4j (图谱库) - 基于 chunk_ids 查关联实体关系
 * 3. ES (关键词库) - 基于 chunk_ids 查关键词上下文
 * 4. PostgreSQL (结构化库) - 基于 chunk_ids 查关联结构化数据
 * 5. 融合 - 综合评分返回最终结果
 */

import { QdrantClient } from '@qdrant/qdrant-js';
import { Neo4jGraph } from '@langchain/community/graphs/neo4j_graph';
import { Client as ElasticsearchClient } from '@elastic/elasticsearch';
import { Pool as PgPool } from 'pg';

// ==================== 类型定义 ====================

export interface ChunkResult {
  chunkId: string;
  docId: string;
  content: string;
  pageNumber: number;
  score: number;
  metadata?: Record<string, any>;
}

export interface GraphEntity {
  entityId: string;
  entityName: string;
  entityType: string;
  relationships: Array<{
    target: string;
    type: string;
  }>;
}

export interface KeywordContext {
  chunkId: string;
  matchedTerms: string[];
  highlights: string[];
}

export interface StructuredData {
  chunkId: string;
  tableName?: string;
  tableData?: any;
 指标?: Record<string, number>;
}

export interface CascadeSearchOptions {
  qdrantUrl?: string;
  neo4jUrl?: string;
  elasticsearchUrl?: string;
  postgresUrl?: string;

  neo4jUsername?: string;
  neo4jPassword?: string;
  elasticUsername?: string;
  elasticPassword?: string;

  topK?: number;
  vectorWeight?: number;
  graphWeight?: number;
  keywordWeight?: number;
}

export interface CascadeSearchResult {
  results: ChunkResult[];
  graphEntities: GraphEntity[];
  keywordContexts: KeywordContext[];
  structuredData: StructuredData[];
  latencyMs: {
    total: number;
    vector: number;
    graph: number;
    keyword: number;
    structured: number;
  };
}

// ==================== 级联检索服务 ====================

export class CascadeRetrievalService {
  private qdrantClient: QdrantClient;
  private neo4jGraph?: Neo4jGraph;
  private elasticClient?: ElasticsearchClient;
  private pgPool?: PgPool;

  private collectionName: string = 'documents';
  private indexName: string = 'documents';

  constructor(private options: CascadeSearchOptions = {}) {
    this.qdrantClient = new QdrantClient({
      url: options.qdrantUrl || process.env.QDRANT_URL || 'http://localhost:6333',
    });
  }

  async initialize(): Promise<void> {
    // 初始化 Neo4j
    if (this.options.neo4jUrl) {
      try {
        this.neo4jGraph = await Neo4jGraph.initialize({
          url: this.options.neo4jUrl,
          username: this.options.neo4jUsername || 'neo4j',
          password: this.options.neo4jPassword || process.env.NEO4J_PASSWORD || 'password',
        });
        console.log('[CascadeRetrieval] Neo4j connected');
      } catch (e) {
        console.warn('[CascadeRetrieval] Neo4j connection failed:', e);
      }
    }

    // 初始化 Elasticsearch
    if (this.options.elasticsearchUrl) {
      try {
        this.elasticClient = new ElasticsearchClient({
          node: this.options.elasticsearchUrl,
          auth: this.options.elasticUsername && this.options.elasticPassword
            ? { username: this.options.elasticUsername, password: this.options.elasticPassword }
            : undefined,
        });
        console.log('[CascadeRetrieval] Elasticsearch connected');
      } catch (e) {
        console.warn('[CascadeRetrieval] Elasticsearch connection failed:', e);
      }
    }

    // 初始化 PostgreSQL
    if (this.options.postgresUrl) {
      try {
        this.pgPool = new PgPool({
          connectionString: this.options.postgresUrl,
        });
        await this.pgPool.query('SELECT 1');
        console.log('[CascadeRetrieval] PostgreSQL connected');
      } catch (e) {
        console.warn('[CascadeRetrieval] PostgreSQL connection failed:', e);
      }
    }
  }

  // ==================== 1. 向量库检索 (语义入口) ====================

  private async searchVector(queryEmbedding: number[], topK: number): Promise<ChunkResult[]> {
    const startTime = Date.now();

    try {
      const results = await this.qdrantClient.search(this.collectionName, {
        vector: queryEmbedding,
        limit: topK,
        with_payload: true,
      });

      const latency = Date.now() - startTime;
      console.log(`[CascadeRetrieval] Vector search: ${results.length} results in ${latency}ms`);

      return results.map((hit) => ({
        chunkId: String(hit.id),
        docId: (hit.payload as Record<string, any>)?.doc_id || '',
        content: (hit.payload as Record<string, any>)?.content || '',
        pageNumber: (hit.payload as Record<string, any>)?.page_number || 1,
        score: hit.score,
        metadata: (hit.payload as Record<string, any>) || undefined,
      }));
    } catch (e) {
      console.error('[CascadeRetrieval] Vector search failed:', e);
      return [];
    }
  }

  // ==================== 2. 图谱库级联 (基于 chunk_ids) ====================

  private async cascadeGraph(chunkIds: string[], topK: number = 10): Promise<{
    entities: GraphEntity[];
    graphScores: Map<string, number>;
  }> {
    const startTime = Date.now();

    if (!this.neo4jGraph || chunkIds.length === 0) {
      return { entities: [], graphScores: new Map() };
    }

    try {
      // 通过 chunk_ids 查找关联的实体
      const placeholders = chunkIds.map((_, i) => `$id${i}`).join(', ');
      const params: Record<string, any> = {};
      chunkIds.forEach((id, i) => { params[`id${i}`] = id; });

      const records = await this.neo4jGraph.query(`
        MATCH (c:Chunk)-[r]-(e:Entity)
        WHERE c.chunk_id IN [${placeholders}]
        RETURN e.entity_id as entityId,
               e.name as entityName,
               e.type as entityType,
               type(r) as relType,
               c.chunk_id as chunkId
        LIMIT $limit
      `, { ...params, limit: topK });

      const latency = Date.now() - startTime;
      console.log(`[CascadeRetrieval] Graph cascade: ${records.length} relations in ${latency}ms`);

      // 构建实体和关系图
      const entityMap = new Map<string, GraphEntity>();
      const graphScores = new Map<string, number>();

      for (const record of records) {
        const entityId = record.entityId;
        if (!entityMap.has(entityId)) {
          entityMap.set(entityId, {
            entityId,
            entityName: record.entityName || '',
            entityType: record.entityType || '',
            relationships: [],
          });
        }

        if (record.relType && record.chunkId) {
          entityMap.get(entityId)!.relationships.push({
            target: record.chunkId,
            type: record.relType,
          });

          // 图谱得分
          const currentScore = graphScores.get(record.chunkId) || 0;
          graphScores.set(record.chunkId, currentScore + 1);
        }
      }

      // 归一化图谱得分
      const maxGraphScore = Math.max(...Array.from(graphScores.values()), 1);
      Array.from(graphScores.entries()).forEach(([key, score]) => {
        graphScores.set(key, score / maxGraphScore);
      });

      return {
        entities: Array.from(entityMap.values()),
        graphScores,
      };
    } catch (e) {
      console.error('[CascadeRetrieval] Graph cascade failed:', e);
      return { entities: [], graphScores: new Map() };
    }
  }

  // ==================== 3. 关键词库级联 (基于 chunk_ids) ====================

  private async cascadeKeyword(chunkIds: string[], query: string): Promise<{
    contexts: KeywordContext[];
    keywordScores: Map<string, number>;
  }> {
    const startTime = Date.now();

    if (!this.elasticClient || chunkIds.length === 0) {
      return { contexts: [], keywordScores: new Map() };
    }

    try {
      // 通过 chunk_ids 查找文档,计算关键词匹配
      const placeholders = chunkIds.map((_, i) => `$id${i}`).join(', ');
      const params: Record<string, any> = {};
      chunkIds.forEach((id, i) => { params[`id${i}`] = id; });

      const response = await this.elasticClient.search({
        index: this.indexName,
        body: {
          query: {
            terms: { chunk_id: chunkIds },
          },
          highlight: {
            fields: {
              content: {
                pre_tags: ['**'],
                post_tags: ['**'],
                fragment_size: 150,
                number_of_fragments: 3,
              },
            },
          },
          size: chunkIds.length,
        },
      });

      const latency = Date.now() - startTime;
      console.log(`[CascadeRetrieval] Keyword cascade: ${response.hits.hits.length} hits in ${latency}ms`);

      const contexts: KeywordContext[] = [];
      const keywordScores = new Map<string, number>();

      for (const hit of response.hits.hits) {
        const chunkId = (hit._source as any)?.chunk_id || String(hit._id);
        const highlight = hit.highlight?.content || [];
        const content = (hit._source as any)?.content || '';

        // 计算关键词匹配得分
        const matchedTerms = query.split(/\s+/).filter(term =>
          content.toLowerCase().includes(term.toLowerCase())
        );
        const score = matchedTerms.length / query.split(/\s+/).length;

        contexts.push({
          chunkId,
          matchedTerms,
          highlights: highlight,
        });

        keywordScores.set(chunkId, score);
      }

      return { contexts, keywordScores };
    } catch (e) {
      console.error('[CascadeRetrieval] Keyword cascade failed:', e);
      return { contexts: [], keywordScores: new Map() };
    }
  }

  // ==================== 4. 结构化库级联 (基于 chunk_ids) ====================

  private async cascadePostgres(chunkIds: string[]): Promise<StructuredData[]> {
    const startTime = Date.now();

    if (!this.pgPool || chunkIds.length === 0) {
      return [];
    }

    try {
      // 查找关联的表格数据
      const placeholders = chunkIds.map((_, i) => `$${i + 1}`).join(', ');

      const result = await this.pgPool.query(`
        SELECT
          dc.chunk_id as "chunkId",
          td.table_name as "tableName",
          td.markdown_content as "tableData",
          td.metadata
        FROM document_chunks dc
        LEFT JOIN tables_data td ON td.document_id = dc.document_id
          AND td.page_number = dc.page_number
        WHERE dc.chunk_id IN (${placeholders})
      `, chunkIds);

      const latency = Date.now() - startTime;
      console.log(`[CascadeRetrieval] PostgreSQL cascade: ${result.rows.length} records in ${latency}ms`);

      return result.rows.map(row => ({
        chunkId: row.chunkId,
        tableName: row.tableName,
        tableData: row.tableData,
        metadata: row.metadata,
      }));
    } catch (e) {
      console.error('[CascadeRetrieval] PostgreSQL cascade failed:', e);
      return [];
    }
  }

  // ==================== 5. 分数融合 ====================

  private fuseResults(
    vectorResults: ChunkResult[],
    graphScores: Map<string, number>,
    keywordScores: Map<string, number>,
    weights: { vector: number; graph: number; keyword: number }
  ): ChunkResult[] {
    const scoreMap = new Map<string, {
      chunk: ChunkResult;
      fusedScore: number;
    }>();

    // 添加向量得分
    for (const chunk of vectorResults) {
      scoreMap.set(chunk.chunkId, {
        chunk,
        fusedScore: chunk.score * weights.vector,
      });
    }

    // 融合图谱得分
    Array.from(graphScores.entries()).forEach(([chunkId, graphScore]) => {
      if (scoreMap.has(chunkId)) {
        scoreMap.get(chunkId)!.fusedScore += graphScore * weights.graph;
      }
    });

    // 融合关键词得分
    Array.from(keywordScores.entries()).forEach(([chunkId, keywordScore]) => {
      if (scoreMap.has(chunkId)) {
        scoreMap.get(chunkId)!.fusedScore += keywordScore * weights.keyword;
      }
    });

    return Array.from(scoreMap.values())
      .sort((a, b) => b.fusedScore - a.fusedScore)
      .map(({ chunk, fusedScore }) => ({
        ...chunk,
        score: fusedScore,
      }));
  }

  // ==================== 主入口: 级联检索 ====================

  async search(
    queryEmbedding: number[],
    query: string,
    topK: number = 10
  ): Promise<CascadeSearchResult> {
    const totalStart = Date.now();
    const weights = {
      vector: this.options.vectorWeight ?? 0.5,
      graph: this.options.graphWeight ?? 0.3,
      keyword: this.options.keywordWeight ?? 0.2,
    };

    console.log(`[CascadeRetrieval] Starting cascade search for: "${query.slice(0, 50)}..."`);

    // Step 1: Qdrant 向量检索
    const vectorStart = Date.now();
    const vectorResults = await this.searchVector(queryEmbedding, topK * 2);
    const vectorLatency = Date.now() - vectorStart;

    if (vectorResults.length === 0) {
      return {
        results: [],
        graphEntities: [],
        keywordContexts: [],
        structuredData: [],
        latencyMs: {
          total: Date.now() - totalStart,
          vector: vectorLatency,
          graph: 0,
          keyword: 0,
          structured: 0,
        },
      };
    }

    const chunkIds = vectorResults.map(r => r.chunkId);

    // Step 2: Neo4j 图谱级联
    const graphStart = Date.now();
    const { entities, graphScores } = await this.cascadeGraph(chunkIds, topK);
    const graphLatency = Date.now() - graphStart;

    // Step 3: ES 关键词级联
    const keywordStart = Date.now();
    const { contexts, keywordScores } = await this.cascadeKeyword(chunkIds, query);
    const keywordLatency = Date.now() - keywordStart;

    // Step 4: PostgreSQL 结构化数据 (可选,异步)
    const structuredStart = Date.now();
    const structuredData = await this.cascadePostgres(chunkIds);
    const structuredLatency = Date.now() - structuredStart;

    // Step 5: 融合
    const fusedResults = this.fuseResults(
      vectorResults,
      graphScores,
      keywordScores,
      weights
    ).slice(0, topK);

    const totalLatency = Date.now() - totalStart;

    console.log(`[CascadeRetrieval] Cascade complete: ${fusedResults.length} results in ${totalLatency}ms`);

    return {
      results: fusedResults,
      graphEntities: entities,
      keywordContexts: contexts,
      structuredData,
      latencyMs: {
        total: totalLatency,
        vector: vectorLatency,
        graph: graphLatency,
        keyword: keywordLatency,
        structured: structuredLatency,
      },
    };
  }

  async close(): Promise<void> {
    if (this.neo4jGraph) {
      await this.neo4jGraph.close();
    }
    if (this.elasticClient) {
      await this.elasticClient.close();
    }
    if (this.pgPool) {
      await this.pgPool.end();
    }
  }
}

// ==================== 导出工厂函数 ====================

export function createCascadeRetrieval(options?: CascadeSearchOptions): CascadeRetrievalService {
  return new CascadeRetrievalService(options);
}

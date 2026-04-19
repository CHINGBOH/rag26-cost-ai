import { Neo4jGraph } from '@langchain/community/graphs/neo4j_graph';
import { QdrantClient } from '@qdrant/qdrant-js';
import { Client as ElasticsearchClient } from '@elastic/elasticsearch';
import { Pool } from 'pg';

export interface RetrievalResult {
  id: string;
  score: number;
  content: string;
  metadata: Record<string, any>;
}

export interface FusionNode {
  id: string;
  content: string;
  metadata: Record<string, any>;
  scores: {
    vector?: number;
    graph?: number;
    keyword?: number;
    rrf?: number;
    count?: number;
    weighted?: number;
    rerank?: number;
  };
}

export interface FusionConfig {
  vectorWeight: number;
  graphWeight: number;
  keywordWeight: number;
  rrfK: number;
  topK: number;
  numQueries: number;
  similarityTopK: number;
}

export interface AdaptiveWeights {
  vector: number;
  graph: number;
  keyword: number;
}

const DEFAULT_CONFIG: FusionConfig = {
  vectorWeight: 0.4,
  graphWeight: 0.3,
  keywordWeight: 0.3,
  rrfK: 60,
  topK: 10,
  numQueries: 4,
  similarityTopK: 20,
};

export class QueryFusionRetriever {
  private qdrant: QdrantClient;
  private neo4j?: Neo4jGraph;
  private es?: ElasticsearchClient;
  private pg?: Pool;
  private config: FusionConfig;
  private collectionName = 'document_chunks';

  constructor(
    qdrant: QdrantClient,
    config: Partial<FusionConfig> = {}
  ) {
    this.qdrant = qdrant;
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  setNeo4j(neo4j: Neo4jGraph): void {
    this.neo4j = neo4j;
  }

  setElasticsearch(es: ElasticsearchClient): void {
    this.es = es;
  }

  setPostgres(pg: Pool): void {
    this.pg = pg;
  }

  calculateAdaptiveWeights(query: string): AdaptiveWeights {
    const hasExactKeywords = /\d{4,}|^\d+$/.test(query);
    const hasChineseEntity = /[工程|费率|标准|系数|费用]/.test(query);
    const queryLength = query.length;

    if (hasExactKeywords) {
      return { vector: 0.3, graph: 0.2, keyword: 0.5 };
    } else if (hasChineseEntity) {
      return { vector: 0.4, graph: 0.4, keyword: 0.2 };
    } else if (queryLength > 20) {
      return { vector: 0.5, graph: 0.3, keyword: 0.2 };
    }
    return { vector: 0.4, graph: 0.3, keyword: 0.3 };
  }

  async generateQueries(
    originalQuery: string,
    numQueries: number,
    llmCallback?: (prompt: string) => Promise<string[]>
  ): Promise<string[]> {
    if (!llmCallback) {
      return [originalQuery];
    }

    const prompt = `You are a helpful assistant that generates multiple search queries based on a
single input query. Generate ${numQueries} search queries, one on each line, related to the following input query:

Query: ${originalQuery}

Queries:`;

    const response = await llmCallback(prompt);
    const queries: string[] = (Array.isArray(response) ? response : [response])
      .map((q: string) => q.trim())
      .filter((q: string) => q.length > 0 && !q.startsWith('#'))
      .slice(0, numQueries);

    return [originalQuery, ...queries];
  }

  async vectorSearch(
    queryEmbedding: number[],
    topK: number
  ): Promise<RetrievalResult[]> {
    try {
      const results = await this.qdrant.search(this.collectionName, {
        vector: queryEmbedding,
        limit: topK,
        with_payload: true,
      });

      return results.map(hit => ({
        id: (hit.payload as any)?.chunk_id || String(hit.id),
        score: hit.score || 0,
        content: (hit.payload as any)?.content || '',
        metadata: (hit.payload as any) || {},
      }));
    } catch (error) {
      console.error('Vector search error:', error);
      return [];
    }
  }

  async graphSearch(
    chunkIds: string[],
    topK: number
  ): Promise<RetrievalResult[]> {
    if (!this.neo4j) return [];

    try {
      if (!chunkIds.length) return [];

      const placeholders = chunkIds.map((_, i) => `$id${i}`).join(', ');
      const params: Record<string, any> = {};
      chunkIds.forEach((id, i) => {
        params[`id${i}`] = id;
      });

      const query = `
        MATCH (c:Chunk)-[:CONTAINS]->(e:Entity)
        WHERE c.chunk_id IN [${placeholders}]
        WITH c, e, count(e) as entityCount
        RETURN c.chunk_id as id,
               c.content as content,
               entityCount as score,
               collect(e.name) as entities
        ORDER BY entityCount DESC
        LIMIT ${topK}
      `;

      const result = await this.neo4j.query(query, params);
      return result.map((row: any) => ({
        id: row.id,
        score: row.score || 0,
        content: row.content || '',
        metadata: { entities: row.entities || [] },
      }));
    } catch (error) {
      console.error('Graph search error:', error);
      return [];
    }
  }

  async keywordSearch(
    query: string,
    topK: number
  ): Promise<RetrievalResult[]> {
    if (!this.es) return [];

    try {
      const result = await this.es.search({
        index: 'documents',
        body: {
          size: topK,
          query: {
            match: {
              content: {
                query: query,
                fuzziness: 'AUTO',
              },
            },
          },
          _source: ['chunk_id', 'content', 'page_number', 'doc_id'],
        },
      });

      return (result.hits.hits as any[]).map((hit: any, index: number) => ({
        id: hit._source.chunk_id || hit._id,
        score: 1 / (index + 1),
        content: hit._source.content || '',
        metadata: hit._source,
      }));
    } catch (error) {
      console.error('Keyword search error:', error);
      return [];
    }
  }

  reciprocalRankFusion(
    resultLists: Map<string, { result: RetrievalResult; rank: number }[]>
  ): Map<string, { node: RetrievalResult; rrfScore: number; count: number }> {
    const k = this.config.rrfK;
    const scores = new Map<string, { node: RetrievalResult; rrfScore: number; count: number }>();

    for (const [, results] of resultLists.entries()) {
      for (const { result, rank } of results) {
        const rrfScore = 1 / (k + rank + 1);

        if (scores.has(result.id)) {
          const existing = scores.get(result.id)!;
          existing.rrfScore += rrfScore;
          existing.count += 1;
        } else {
          scores.set(result.id, {
            node: result,
            rrfScore,
            count: 1,
          });
        }
      }
    }

    return scores;
  }

  weightedFusion(
    fusedResults: Map<string, { node: RetrievalResult; rrfScore: number; count: number }>,
    weights: AdaptiveWeights
  ): FusionNode[] {
    const nodes: FusionNode[] = [];

    for (const [id, data] of fusedResults.entries()) {
      const finalScore = data.rrfScore * (
        weights.vector * (data.node.metadata?.vectorScore || 0.5) +
        weights.graph * (data.node.metadata?.graphScore || 0.5) +
        weights.keyword * (data.node.metadata?.keywordScore || 0.5)
      );

      nodes.push({
        id,
        content: data.node.content,
        metadata: data.node.metadata,
        scores: {
          rrf: data.rrfScore,
          count: data.count,
          weighted: finalScore,
          vector: data.node.metadata?.vectorScore || 0,
          graph: data.node.metadata?.graphScore || 0,
          keyword: data.node.metadata?.keywordScore || 0,
        },
      });
    }

    return nodes
      .sort((a, b) => (b.scores.weighted || 0) - (a.scores.weighted || 0))
      .slice(0, this.config.topK);
  }

  async structSearch(
    chunkIds: string[]
  ): Promise<RetrievalResult[]> {
    if (!this.pg || !chunkIds.length) return [];

    try {
      const placeholders = chunkIds.map((_, i) => `$${i + 1}`).join(', ');
      const query = `
        SELECT chunk_id, doc_id, content, metadata
        FROM document_chunks
        WHERE chunk_id IN (${placeholders})
      `;
      const result = await this.pg.query(query, chunkIds);

      return result.rows.map((row: any) => ({
        id: row.chunk_id,
        score: 1,
        content: row.content || '',
        metadata: {
          doc_id: row.doc_id,
          ...row.metadata,
          from_struct: true,
        },
      }));
    } catch (error) {
      console.error('Struct search error:', error);
      return [];
    }
  }

  async structSearchByKeywords(
    keywords: string[]
  ): Promise<RetrievalResult[]> {
    if (!this.pg || !keywords.length) return [];

    try {
      const pattern = keywords.join('|');
      const query = `
        SELECT chunk_id, doc_id, content, metadata
        FROM document_chunks
        WHERE content ~* $1
      `;
      const result = await this.pg.query(query, [pattern]);

      return result.rows.map((row: any) => ({
        id: row.chunk_id,
        score: 1,
        content: row.content || '',
        metadata: {
          doc_id: row.doc_id,
          ...row.metadata,
          from_struct: true,
        },
      }));
    } catch (error) {
      console.error('Struct keyword search error:', error);
      return [];
    }
  }

  async retrieve(
    queryEmbedding: number[],
    query: string,
    options?: {
      generateQueries?: boolean;
      llmCallback?: (prompt: string) => Promise<string[]>;
      mode?: 'rrf' | 'weighted' | 'hybrid';
    }
  ): Promise<{ semanticResults: FusionNode[]; structResults: RetrievalResult[] }> {
    const {
      generateQueries = false,
      llmCallback,
      mode = 'hybrid',
    } = options || {};

    const weights = this.calculateAdaptiveWeights(query);
    const queries = generateQueries && llmCallback
      ? await this.generateQueries(query, this.config.numQueries, llmCallback)
      : [query];

    const vectorResults = new Map<string, { result: RetrievalResult; rank: number }[]>();
    const graphResults = new Map<string, { result: RetrievalResult; rank: number }[]>();
    const keywordResults = new Map<string, { result: RetrievalResult; rank: number }[]>();

    const keywords = query.split(/\s+/).filter(k => k.length > 2);

    for (const q of queries) {
      const [vectorRes, graphRes, keywordRes] = await Promise.all([
        this.vectorSearch(queryEmbedding, this.config.similarityTopK),
        this.graphSearch([], this.config.similarityTopK),
        this.keywordSearch(q, this.config.similarityTopK),
      ]);

      vectorRes.forEach((r, rank) => {
        const arr = vectorResults.get(r.id) || [];
        arr.push({ result: { ...r, metadata: { ...r.metadata, vectorScore: r.score } }, rank });
        vectorResults.set(r.id, arr);
      });

      graphRes.forEach((r, rank) => {
        const arr = graphResults.get(r.id) || [];
        arr.push({ result: { ...r, metadata: { ...r.metadata, graphScore: r.score } }, rank });
        graphResults.set(r.id, arr);
      });

      keywordRes.forEach((r, rank) => {
        const arr = keywordResults.get(r.id) || [];
        arr.push({ result: { ...r, metadata: { ...r.metadata, keywordScore: r.score } }, rank });
        keywordResults.set(r.id, arr);
      });
    }

    const fused = this.reciprocalRankFusion(
      new Map([
        ['vector', Array.from(vectorResults.values()).flat()],
        ['graph', Array.from(graphResults.values()).flat()],
        ['keyword', Array.from(keywordResults.values()).flat()],
      ])
    );

    let semanticNodes: FusionNode[];
    if (mode === 'rrf') {
      semanticNodes = Array.from(fused.values())
        .map(data => ({
          id: data.node.id,
          content: data.node.content,
          metadata: data.node.metadata,
          scores: {
            rrf: data.rrfScore,
            count: data.count,
          },
        }))
        .sort((a, b) => (b.scores.rrf || 0) - (a.scores.rrf || 0))
        .slice(0, this.config.topK);
    } else {
      semanticNodes = this.weightedFusion(fused, weights);
    }

    const chunkIds = semanticNodes.map(n => n.id);
    const structResults = await this.structSearch(chunkIds);

    return {
      semanticResults: semanticNodes,
      structResults,
    };
  }

  async rerank(
    nodes: FusionNode[],
    query: string,
    rerankCallback?: (query: string, nodes: string[]) => Promise<{ index: number; score: number }[]>
  ): Promise<FusionNode[]> {
    if (!rerankCallback) return nodes;

    const contents = nodes.map(n => n.content);
    const rerankResults = await rerankCallback(query, contents);

    const rerankMap = new Map(rerankResults.map(r => [r.index, r.score]));

    return nodes
      .map((node, index) => ({
        ...node,
        scores: {
          ...node.scores,
          rerank: rerankMap.get(index) || 0,
        },
      }))
      .sort((a, b) => (b.scores.rerank || 0) - (a.scores.rerank || 0));
  }
}

export function createQueryFusionRetriever(
  qdrant: QdrantClient,
  config?: Partial<FusionConfig>
): QueryFusionRetriever {
  return new QueryFusionRetriever(qdrant, config);
}

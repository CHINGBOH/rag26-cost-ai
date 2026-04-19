/**
 * 检索服务 - 调用Python后端的多路召回能力
 * 实现向量检索、关键词检索、图数据库检索
 */

import {
  RetrievedChunk,
  SubQuery,
  RoundEvaluation,
  DatabaseTarget
} from '@rag/shared';

interface RetrievalConfig {
  pythonApiUrl: string;
  retrievalApiUrl?: string;
  apiKey?: string;
  timeout: number;
}

interface SearchRequest {
  query: string;
  top_k?: number;
  enable_rerank?: boolean;
  enable_fusion?: boolean;
}

interface SearchResult {
  id: string;
  content: string;
  source: string;
  database: DatabaseTarget;
  score: number;
  metadata?: Record<string, any>;
}

interface SearchResponse {
  results: SearchResult[];
  total: number;
  query_time_ms: number;
  fusion_scores?: Record<string, number>;
}

export class RetrievalService {
  private config: RetrievalConfig;

  constructor(config?: Partial<RetrievalConfig>) {
    this.config = {
      pythonApiUrl: config?.pythonApiUrl || process.env.PYTHON_API_URL || 'http://localhost:8000',
      retrievalApiUrl: config?.retrievalApiUrl || process.env.RETRIEVAL_API_URL || 'http://localhost:8002',
      apiKey: config?.apiKey || process.env.API_KEY,
      timeout: config?.timeout || 30000
    };
  }

  private async fetchWithTimeout(
    url: string,
    options: RequestInit,
    timeoutMs: number = this.config.timeout
  ): Promise<Response> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, {
        ...options,
        signal: controller.signal
      });
      return response;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  /**
   * 执行多路召回检索
   * 调用Python后端的统一检索API
   */
  async retrieve(query: string, topK: number = 10): Promise<RetrievedChunk[]> {
    try {
      console.log(`[RetrievalService] 开始检索: "${query.slice(0, 50)}..."`);
      
      const request: SearchRequest = {
        query,
        top_k: topK * 3, // 请求更多结果用于精排
        enable_rerank: true,
        enable_fusion: true
      };

      const response = await this.fetchWithTimeout(`${this.config.retrievalApiUrl}/api/v1/search`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(this.config.apiKey && { 'Authorization': `Bearer ${this.config.apiKey}` })
        },
        body: JSON.stringify(request)
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`检索API错误: ${response.status} - ${errorText}`);
      }

      const data = await response.json() as SearchResponse;
      
      console.log(`[RetrievalService] 检索完成: ${data.results.length} 条结果, 耗时 ${data.query_time_ms}ms`);

      // 转换为RetrievedChunk格式
      return data.results.map(result => this.toRetrievedChunk(result));
    } catch (error) {
      console.error('[RetrievalService] 检索失败:', error);
      console.warn('Retrieval service unreachable, falling back to local mock');
      return this.getMockRetrievedChunks(query);
    }
  }

  /**
   * 分解查询为子查询
   * 调用Python后端的查询分解服务
   */
  async decomposeQuery(query: string): Promise<SubQuery[]> {
    try {
      console.log(`[RetrievalService] 分解查询: "${query.slice(0, 50)}..."`);

      // 首先尝试调用Python后端的分解API
      const response = await this.fetchWithTimeout(`${this.config.retrievalApiUrl}/api/v1/decompose`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(this.config.apiKey && { 'Authorization': `Bearer ${this.config.apiKey}` })
        },
        body: JSON.stringify({ query })
      });

      if (response.ok) {
        const data = await response.json() as { subQueries: SubQuery[] };
        return data.subQueries;
      }

      // 如果API不存在，使用本地简单分解
      throw new Error('分解API不可用');
    } catch (error) {
      console.error('[RetrievalService] 查询分解失败:', error);
      console.warn('Retrieval service unreachable, falling back to local mock');
      return this.localDecomposeQuery(query);
    }
  }

  /**
   * 生成本地子查询分解
   */
  private localDecomposeQuery(query: string): SubQuery[] {
    const subQueries: SubQuery[] = [];
    
    // 基础概念查询 - 总是添加
    subQueries.push({
      id: `sq_${Date.now()}_1`,
      query: `${query} 基础概念定义`,
      targetDB: 'vector',
      status: 'pending'
    });

    // 实现细节查询
    subQueries.push({
      id: `sq_${Date.now()}_2`,
      query: `${query} 实现方法 技术细节`,
      targetDB: 'knowledge',
      status: 'pending'
    });

    // 如果查询包含"如何/怎么"，添加案例查询
    if (/如何|怎么|怎样|案例|示例/.test(query)) {
      subQueries.push({
        id: `sq_${Date.now()}_3`,
        query: `${query} 实际案例 应用示例`,
        targetDB: 'graph',
        status: 'pending'
      });
    }

    // 如果查询包含"区别/对比/比较"，添加对比查询
    if (/区别|对比|比较|vs|versus/.test(query)) {
      subQueries.push({
        id: `sq_${Date.now()}_4`,
        query: `${query} 对比分析 优缺点`,
        targetDB: 'vector',
        status: 'pending'
      });
    }

    return subQueries;
  }

  /**
   * 精排文档块
   * 调用Python后端的重排序服务
   */
  async rerank(query: string, chunks: RetrievedChunk[]): Promise<RetrievedChunk[]> {
    try {
      if (chunks.length === 0) return chunks;

      const response = await this.fetchWithTimeout(`${this.config.retrievalApiUrl}/api/v1/rerank`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(this.config.apiKey && { 'Authorization': `Bearer ${this.config.apiKey}` })
        },
        body: JSON.stringify({
          query,
          documents: chunks.map(c => ({ id: c.id, content: c.content })),
          top_k: chunks.length
        })
      });

      if (response.ok) {
        const data = await response.json() as { results: Array<{ id: string; score: number }> };
        // 根据重排结果重新排序
        const rerankedIds = new Map(data.results.map((r, idx) => [r.id, idx]));
        return chunks
          .map(c => ({ ...c, score: data.results.find(r => r.id === c.id)?.score || c.score }))
          .sort((a, b) => (rerankedIds.get(b.id) ?? 0) - (rerankedIds.get(a.id) ?? 0));
      }

      throw new Error('重排序API不可用');
    } catch (error) {
      console.error('[RetrievalService] 重排序失败:', error);
      console.warn('Retrieval service unreachable, falling back to local mock');
      return chunks.sort((a, b) => b.score - a.score);
    }
  }

  /**
   * 评估检索轮次质量
   */
  async evaluateRound(
    query: string,
    chunks: RetrievedChunk[],
    answer: string,
    historyRounds: number
  ): Promise<RoundEvaluation> {
    try {
      const response = await this.fetchWithTimeout(`${this.config.retrievalApiUrl}/api/v1/evaluate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(this.config.apiKey && { 'Authorization': `Bearer ${this.config.apiKey}` })
        },
        body: JSON.stringify({
          query,
          retrieved_chunks: chunks,
          generated_answer: answer,
          history_rounds: historyRounds
        })
      });

      if (response.ok) {
        return await response.json() as RoundEvaluation;
      }

      throw new Error('评估API不可用');
    } catch (error) {
      console.error('[RetrievalService] 评估失败:', error);
      console.warn('Retrieval service unreachable, falling back to local mock');
      return this.localEvaluateRound(chunks, answer, historyRounds);
    }
  }

  /**
   * 本地评估算法
   */
  private localEvaluateRound(
    chunks: RetrievedChunk[],
    answer: string,
    historyRounds: number
  ): RoundEvaluation {
    // 计算基础指标
    const avgScore = chunks.length > 0 
      ? chunks.reduce((sum, c) => sum + c.score, 0) / chunks.length 
      : 0;
    
    // 来源多样性
    const sources = new Set(chunks.map(c => c.source));
    const sourceDiversity = Math.min(sources.size / 3, 1.0);

    // 数据库多样性
    const databases = new Set(chunks.map(c => c.database));
    const dbDiversity = databases.size / 4;

    // 综合多样性
    const diversity = (sourceDiversity + dbDiversity) / 2;

    // 信息增益（模拟：轮次越多增益递减）
    const informationGain = Math.max(0.1, 0.5 - historyRounds * 0.1);

    // 完整性估计（基于检索到的内容长度）
    const totalContentLength = chunks.reduce((sum, c) => sum + c.content.length, 0);
    const completeness = Math.min(totalContentLength / 2000, 0.95);

    // 一致性（基于分数方差）
    const variance = chunks.length > 0
      ? chunks.reduce((sum, c) => sum + Math.pow(c.score - avgScore, 2), 0) / chunks.length
      : 0;
    const consistency = Math.max(0.5, 1 - variance);

    // 事实一致性（简化：假设引用越多越一致）
    const citationCount = (answer.match(/\[\d+\]/g) || []).length;
    const factConsistency = Math.min(0.5 + citationCount * 0.1, 0.95);

    // 覆盖率估计
    const coverageEstimate = Math.min(avgScore * diversity * 1.5, 0.95);

    // 置信度
    const confidence = (completeness + consistency + factConsistency + diversity) / 4;

    return {
      completeness,
      consistency,
      confidence,
      informationGain,
      sourceDiversity: diversity,
      factConsistency,
      coverageEstimate
    };
  }

  /**
   * 将SearchResult转换为RetrievedChunk
   */
  private toRetrievedChunk(result: SearchResult): RetrievedChunk {
    return {
      id: result.id,
      content: result.content,
      source: result.source,
      database: result.database,
      score: result.score,
      metadata: result.metadata || {}
    };
  }

  /**
   * 获取模拟检索结果（降级方案）
   */
  private getMockRetrievedChunks(query: string): RetrievedChunk[] {
    return [
      {
        id: `mock_${Date.now()}_1`,
        content: `关于"${query}"的基础概念：这是一个重要的主题，涉及多个方面的知识体系。根据相关文档，核心定义包括...`,
        source: '知识库/kb-001',
        database: 'knowledge',
        score: 0.92,
        metadata: { section: '基础概念' }
      },
      {
        id: `mock_${Date.now()}_2`,
        content: `在实现层面，"${query}"通常采用分层架构设计。具体实现步骤包括：1) 需求分析 2) 架构设计 3) 模块实现...`,
        source: '技术文档/tech-102',
        database: 'vector',
        score: 0.88,
        metadata: { page: 5, section: 'Implementation' }
      },
      {
        id: `mock_${Date.now()}_3`,
        content: `相关案例分析：某公司在实施"${query}"方案时，采用了敏捷开发方法，最终取得了显著成效...`,
        source: '案例库/case-045',
        database: 'graph',
        score: 0.85,
        metadata: { timestamp: Date.now() }
      }
    ];
  }

  /**
   * 健康检查
   */
  async healthCheck(): Promise<{ healthy: boolean; services: Record<string, boolean> }> {
    try {
      const response = await this.fetchWithTimeout(`${this.config.retrievalApiUrl}/api/v1/health`, {
        method: 'GET',
        headers: {
          ...(this.config.apiKey && { 'Authorization': `Bearer ${this.config.apiKey}` })
        }
      });

      if (response.ok) {
        const data = await response.json() as { status: string; services?: Record<string, boolean> };
        return {
          healthy: data.status === 'healthy',
          services: data.services || {}
        };
      }

      return { healthy: false, services: {} };
    } catch (error) {
      console.error('[RetrievalService] 健康检查失败:', error);
      console.warn('Retrieval service unreachable, falling back to local mock');
      return { healthy: false, services: {} };
    }
  }
}

/**
 * 检索服务测试
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { RetrievalService } from '../services/RetrievalService';

describe('RetrievalService', () => {
  let service: RetrievalService;

  beforeEach(() => {
    service = new RetrievalService({
      pythonApiUrl: 'http://localhost:8000',
      timeout: 5000
    });
  });

  it('应该成功检索文档', async () => {
    const results = await service.retrieve('测试查询', 5);
    
    expect(results).toBeInstanceOf(Array);
    expect(results.length).toBeGreaterThan(0);
    
    if (results.length > 0) {
      expect(results[0]).toHaveProperty('id');
      expect(results[0]).toHaveProperty('content');
      expect(results[0]).toHaveProperty('source');
      expect(results[0]).toHaveProperty('score');
    }
  });

  it('应该分解查询为子查询', async () => {
    const subQueries = await service.decomposeQuery('如何实现RAG系统');
    
    expect(subQueries).toBeInstanceOf(Array);
    expect(subQueries.length).toBeGreaterThan(0);
    
    subQueries.forEach(sq => {
      expect(sq).toHaveProperty('id');
      expect(sq).toHaveProperty('query');
      expect(sq).toHaveProperty('targetDB');
    });
  });

  it('应该正确评估轮次', async () => {
    const chunks = [
      { id: '1', content: '测试内容1', source: 'doc1', database: 'vector' as const, score: 0.9, metadata: {} },
      { id: '2', content: '测试内容2', source: 'doc2', database: 'knowledge' as const, score: 0.8, metadata: {} }
    ];
    
    const evaluation = await service.evaluateRound('测试查询', chunks, '测试答案', 1);
    
    expect(evaluation).toHaveProperty('completeness');
    expect(evaluation).toHaveProperty('consistency');
    expect(evaluation).toHaveProperty('confidence');
    expect(evaluation).toHaveProperty('informationGain');
    
    expect(evaluation.confidence).toBeGreaterThan(0);
    expect(evaluation.confidence).toBeLessThanOrEqual(1);
  });
});

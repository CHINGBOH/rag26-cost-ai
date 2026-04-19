/**
 * LLM服务测试
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { LLMService } from '../services/LLMService';

describe('LLMService', () => {
  let service: LLMService;

  beforeEach(() => {
    service = new LLMService({
      provider: 'kimi',
      model: 'kimi-for-coding'
    });
  });

  it('应该生成回答', async () => {
    const chunks = [
      { content: 'RAG是一种检索增强生成技术', source: 'doc1', score: 0.95 },
      { content: '它结合了检索和生成的能力', source: 'doc2', score: 0.88 }
    ];

    const result = await service.generateAnswer('什么是RAG', chunks);
    
    expect(result).toHaveProperty('answer');
    expect(result).toHaveProperty('citations');
    expect(typeof result.answer).toBe('string');
    expect(result.answer.length).toBeGreaterThan(0);
  });

  it('应该快速回答简单问题', async () => {
    const answer = await service.quickAsk('你好');
    
    expect(typeof answer).toBe('string');
  });

  it('应该测试连接', async () => {
    const result = await service.testConnection();
    
    expect(result).toHaveProperty('success');
    expect(result).toHaveProperty('message');
  });
});

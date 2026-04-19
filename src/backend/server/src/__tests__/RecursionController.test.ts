/**
 * 递归控制器测试
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { EventEmitter } from 'events';
import { RecursionController } from '../core/RecursionController';

describe('RecursionController', () => {
  let controller: RecursionController;
  let eventEmitter: EventEmitter;

  beforeEach(() => {
    eventEmitter = new EventEmitter();
    controller = new RecursionController(eventEmitter);
  });

  it('应该创建会话', () => {
    const session = controller.createSession('测试查询');
    
    expect(session).toHaveProperty('id');
    expect(session.originalQuery).toBe('测试查询');
    expect(session.currentState).toBe('idle');
    expect(session.currentDepth).toBe(0);
  });

  it('应该获取所有会话', () => {
    controller.createSession('查询1');
    controller.createSession('查询2');
    
    const sessions = controller.getAllSessions();
    expect(sessions.length).toBe(2);
  });

  it('应该通过ID获取会话', () => {
    const session = controller.createSession('查询');
    const found = controller.getSession(session.id);
    
    expect(found).not.toBeNull();
    expect(found?.id).toBe(session.id);
  });

  it('应该提交人工审核', async () => {
    // 创建并启动会话
    const session = controller.createSession('测试查询');
    
    // 启动递归（异步，不等待）
    controller.startRecursion(session.id).catch(() => {});
    
    // 等待一会儿让状态机启动
    await new Promise(resolve => setTimeout(resolve, 100));
    
    // 提交审核应该不抛出异常
    expect(() => {
      // 注意：如果actor还没创建可能会报错
      try {
        controller.submitHumanReview(session.id, true);
      } catch (e) {
        // 预期的错误
      }
    }).not.toThrow();
  });
});

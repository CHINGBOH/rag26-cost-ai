/**
 * LangChain Agent 集成测试
 */

import { describe, it, expect } from 'vitest'
import { AgentFactory } from '../modules/agent/src'

describe('Agent Integration', () => {
  it('应该能创建 LangChain Agent', async () => {
    const agent = AgentFactory.create('langchain', {
      model: 'deepseek-chat',
      apiKey: 'test-key',
      baseUrl: 'https://api.deepseek.com'
    })

    expect(agent).toBeDefined()
    expect(typeof agent.run).toBe('function')
  })

  it('应该能创建空工具列表', async () => {
    // 测试工具函数
    const { createFourDatabaseTools } = await import('../modules/agent/src')
    const tools = createFourDatabaseTools()

    expect(tools).toBeDefined()
    expect(Array.isArray(tools)).toBe(true)
    expect(tools.length).toBe(4)
    expect(tools[0].name).toBe('vectorSearch')
    expect(tools[1].name).toBe('keywordSearch')
    expect(tools[2].name).toBe('graphSearch')
    expect(tools[3].name).toBe('calculator')
  })
})

#!/usr/bin/env tsx
/**
 * LangChain Agent 实际运行测试
 */

import { LLMService } from './src/services/LLMService'
import { AgentFactory } from './src/modules/agent/src'

console.log('🚀 开始 LangChain Agent 测试...\n')

async function testLLMService() {
  console.log('📡 测试 LLM 连接...')

  try {
    const llmService = new LLMService()
    const result = await llmService.quickAsk('你好，请用一句话介绍自己')
    console.log('✅ LLM 测试成功:', result)
    return true
  } catch (error) {
    console.error('❌ LLM 测试失败:', error)
    return false
  }
}

async function testAgent() {
  console.log('\n🤖 测试 Agent 运行...')

  try {
    const llmService = new LLMService()

    const agent = AgentFactory.create('langchain', {
      model: (llmService as any).config.model,
      apiKey: (llmService as any).config.apiKey,
      baseUrl: (llmService as any).config.baseUrl
    }, {
      maxIterations: 3
    })

    console.log('✅ Agent 创建成功')
    console.log('🧪 执行查询...\n')

    const result = await agent.run('什么是 RAG (Retrieval-Augmented Generation)？')

    console.log('\n🎯 测试完成！')
    console.log('=' .repeat(80))
    console.log('📝 Answer:')
    console.log(result.answer)
    console.log('\n📚 Indices:', result.indices.length)
    console.log('🔢 Calculations:', result.calculations.length)
    console.log('⭐ Confidence:', result.confidence)
    console.log('=' .repeat(80))

    return true
  } catch (error) {
    console.error('❌ Agent 测试失败:', error)
    return false
  }
}

async function main() {
  const llmOk = await testLLMService()

  if (llmOk) {
    await testAgent()
  }

  console.log('\n✅ 测试结束')
}

main().catch(console.error)

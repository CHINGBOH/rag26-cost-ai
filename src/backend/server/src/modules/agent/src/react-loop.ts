import { ChatOpenAI } from '@langchain/openai'
import { SystemMessage, HumanMessage, AIMessage, ToolMessage } from '@langchain/core/messages'
import { BaseMessage } from '@langchain/core/messages'
import { createFourDatabaseTools } from './tools'
import { StructuredOutput, AgentOptions, AgentOptionsSchema, IndexReference, Calculation } from './types'

export interface AgentIterationEvent {
  iteration: number
  type: 'reasoning' | 'acting' | 'reflection' | 'answer'
  content: string
  timestamp: number
  toolCalls?: Array<{
    id: string
    name: string
    args: any
    result?: string
  }>
}

const SYSTEM_PROMPT = `你是一个智能研究助手，基于检索到的知识回答用户问题。

【绝对规则 - 必须遵守】
1. 你必须先调用工具获取信息，然后基于检索结果回答问题
2. 禁止在没有调用任何工具的情况下直接回答用户问题
3. 即使你认为知道答案，也必须先通过工具验证
4. 涉及数学计算的问题（如"费率是多少""价格差异""变化幅度""比例"），必须调用calculator工具验证结果
5. 问题询问具体数值、系数、比例时，优先使用keywordSearch精确查找

核心原则:
1. Reasoning (推理): 先思考需要什么信息，再决定调用什么工具
2. Acting (行动): 调用工具获取信息（这是强制步骤，不可跳过）
3. Reflection (反思): 评估信息是否足够回答问题

工具选择指南:
- vectorSearch: 语义搜索，用于理解性查询、概念解释
- keywordSearch: 精确匹配，用于事实查询、数据查找、费率系数查询、定额子目查询
- graphSearch: 关系发现，用于实体关联、推理链条、跨版本对比
- calculator: 数学计算，用于数值运算、费率反推、价格差异计算、变化幅度计算

【回答格式要求 - 必须遵守】
1. 最终回答必须是自然语言，用中文清晰表达
2. 不要直接输出工具返回的原始 JSON 数据
3. 基于检索到的内容，整合信息后给出简洁、准确的回答
4. 如果涉及多个要点，使用编号列表
5. 在回答末尾标注引用来源（如：参考 doc_0.md、chunk_1）
6. 如果信息不足，明确说明"根据现有资料无法完全回答"

示例（正确回答）:
"RAG（检索增强生成）是一种结合信息检索与文本生成的AI技术。其核心工作流程是：
1. 接收用户查询
2. 从知识库检索相关文档片段
3. 将检索结果作为上下文输入LLM
4. 生成准确、可追溯的回答

参考来源：doc_0.md"

示例（错误回答 - 禁止）:
直接复制粘贴工具返回的JSON字符串`

export class ReactAgent {
  private llm: ChatOpenAI
  private tools: any[]
  private options: AgentOptions
  private eventCallback?: (event: AgentIterationEvent) => void

  constructor(
    llm: ChatOpenAI,
    options?: Partial<AgentOptions>,
    eventCallback?: (event: AgentIterationEvent) => void
  ) {
    this.llm = llm
    this.options = AgentOptionsSchema.parse(options || {})
    this.tools = createFourDatabaseTools()
    this.eventCallback = eventCallback
  }

  private emitEvent(event: AgentIterationEvent) {
    if (this.eventCallback) {
      this.eventCallback(event)
    }
  }

  async run(query: string): Promise<StructuredOutput> {
    const messages: BaseMessage[] = [
      new SystemMessage(SYSTEM_PROMPT),
      new HumanMessage(query)
    ]
    
    const allIndices: IndexReference[] = []
    const allCalculations: Calculation[] = []
    
    for (let i = 0; i < this.options.maxIterations; i++) {
      const iteration = i + 1
      
      this.emitEvent({
        iteration,
        type: 'reasoning',
        content: '思考需要什么信息来回答这个问题...',
        timestamp: Date.now()
      })
      
      const boundLlm = this.llm.bindTools(this.tools)
      const aiMsg = await boundLlm.invoke(messages)
      messages.push(aiMsg)
      
      if ('tool_calls' in aiMsg && aiMsg.tool_calls && aiMsg.tool_calls.length > 0) {
        const toolCallEvents = aiMsg.tool_calls.map((tc: any) => ({
          id: tc.id || 'unknown',
          name: tc.name,
          args: tc.args
        }))
        
        this.emitEvent({
          iteration,
          type: 'acting',
          content: `调用 ${aiMsg.tool_calls.length} 个工具获取相关信息`,
          timestamp: Date.now(),
          toolCalls: toolCallEvents
        })
        
        for (const toolCall of aiMsg.tool_calls) {
          const tool = this.tools.find((t: any) => t.name === toolCall.name)
          if (tool) {
            const result = await tool.invoke(toolCall.args)
            messages.push(new ToolMessage({
              content: result,
              tool_call_id: toolCall.id || 'unknown'
            }))
            
            this.emitEvent({
              iteration,
              type: 'acting',
              content: `${toolCall.name} 执行完成`,
              timestamp: Date.now(),
              toolCalls: [{
                id: toolCall.id || 'unknown',
                name: toolCall.name,
                args: toolCall.args,
                result
              }]
            })
            
            // 从工具返回文本中提取索引和计算记录
            if (typeof result === 'string') {
              if (toolCall.name === 'calculator') {
                const calcMatch = result.match(/计算结果[:：]\s*([\d.]+)/)
                const exprMatch = result.match(/表达式[:：]\s*(.+)/)
                if (calcMatch && exprMatch) {
                  allCalculations.push({
                    formula: exprMatch[1].trim(),
                    steps: [exprMatch[1].trim(), `= ${calcMatch[1]}`],
                    result: parseFloat(calcMatch[1])
                  })
                }
              } else if (toolCall.name.includes('Search')) {
                // 解析检索结果文本中的来源信息
                const sourceMatches = result.matchAll(/来源:\s*(\S+)/g)
                const contentMatches = result.matchAll(/内容:\s*(.+)/g)
                const sources = Array.from(sourceMatches).map(m => m[1])
                const contents = Array.from(contentMatches).map(m => m[1].trim().slice(0, 200))
                
                sources.forEach((src, idx) => {
                  const sourceDb = toolCall.name === 'vectorSearch' ? 'vector' :
                                   toolCall.name === 'keywordSearch' ? 'keyword' :
                                   toolCall.name === 'graphSearch' ? 'graph' : 'knowledge'
                  allIndices.push({
                    chunk_id: `chunk_${src}_${idx}`,
                    doc_id: src,
                    source_db: sourceDb as any
                  })
                })
              }
            }
          }
        }
        
        this.emitEvent({
          iteration,
          type: 'reflection',
          content: '评估信息是否足够回答问题...',
          timestamp: Date.now()
        })
        
      } else {
        break
      }
    }
    
    // 最终总结：提取所有 ToolMessage 中的检索内容，单独调用 LLM 生成自然语言回答
    const toolContents = messages
      .filter((m: any) => m._getType && m._getType() === 'tool')
      .map((m: any) => typeof m.content === 'string' ? m.content : '')
      .filter(Boolean)
    
    const summaryMessages: BaseMessage[] = [
      new SystemMessage(
        '你是一个信息整合助手。基于下面提供的检索结果，生成一段简洁、准确的中文自然语言回答。' +
        '要求：不要返回JSON；不要直接复制原文；用自己的话整合表达；标注参考来源。'
      ),
      new HumanMessage(`检索结果：\n${toolContents.join('\n---\n')}\n\n用户问题：${query}\n\n请生成回答：`)
    ]
    
    const finalMsg = await this.llm.invoke(summaryMessages)
    let content = typeof finalMsg.content === 'string' ? finalMsg.content : ''
    
    // 后处理：如果 LLM 返回 JSON，提取关键内容并格式化为自然语言
    try {
      const parsed = JSON.parse(content)
      const items = parsed.results || []
      if (Array.isArray(items) && items.length > 0) {
        const texts = items
          .map((item: any) => {
            const txt = item.content || ''
            // 去掉 "关于 'xxx' 的检索结果：" 前缀
            return txt.replace(/^关于\s*.+?\s*的检索结果[：:]\s*/, '')
          })
          .filter(Boolean)
        // 去重
        const unique = Array.from(new Set(texts))
        if (unique.length > 0) {
          content = unique.join('\n\n')
        }
      }
    } catch {
      // 不是 JSON，保留原始内容
    }
    
    this.emitEvent({
      iteration: Math.max(1, Math.floor(messages.length / 2)),
      type: 'answer',
      content,
      timestamp: Date.now()
    })
    
    // 动态计算置信度：基于检索结果数量、来源多样性和是否有计算验证
    const hasResults = allIndices.length > 0
    const hasCalculations = allCalculations.length > 0
    const uniqueSources = new Set(allIndices.map(idx => idx.doc_id))
    const sourceDiversity = Math.min(uniqueSources.size / 3, 1)
    const confidence = Math.min(1, (hasResults ? 0.6 : 0.2) + sourceDiversity * 0.2 + (hasCalculations ? 0.1 : 0) + (content.includes('参考') || content.includes('来源') ? 0.1 : 0))
    
    // 确保回答末尾有引用来源（如果没有，自动追加）
    if (hasResults && !content.includes('参考') && !content.includes('来源')) {
      const sourceList = Array.from(uniqueSources).slice(0, 5).join('、')
      content += `\n\n参考来源：${sourceList}`
    }
    
    return {
      answer: content,
      indices: allIndices,
      calculations: allCalculations,
      confidence
    }
  }
}

export function createAgent(
  llm: ChatOpenAI,
  options?: Partial<AgentOptions>,
  eventCallback?: (event: AgentIterationEvent) => void
): ReactAgent {
  return new ReactAgent(llm, options, eventCallback)
}

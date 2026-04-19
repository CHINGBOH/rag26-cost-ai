import { ChatOpenAI } from '@langchain/openai'
import { ReactAgent, createAgent as createLangChainAgent, AgentIterationEvent } from './react-loop'
import { AgentOptions, StructuredOutput } from './types'

export type AgentFramework = 'langchain' | 'llamaindex'

export interface Agent {
  run(query: string): Promise<StructuredOutput>
}

export class AgentFactory {
  static create(
    framework: AgentFramework,
    llmOptions: { model?: string; apiKey?: string; baseUrl?: string },
    options?: Partial<AgentOptions>,
    eventCallback?: (event: AgentIterationEvent) => void
  ): Agent {
    switch (framework) {
      case 'langchain':
        const llm = new ChatOpenAI({
          model: llmOptions.model || 'gpt-4o-mini',
          apiKey: llmOptions.apiKey,
          configuration: { baseURL: llmOptions.baseUrl }
        })
        return createLangChainAgent(llm, options, eventCallback)
      
      case 'llamaindex':
        throw new Error('LlamaIndex agent not implemented yet')
      
      default:
        throw new Error(`Unsupported framework: ${framework}`)
    }
  }
}

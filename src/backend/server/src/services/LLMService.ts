/**
 * LLM生成服务
 * 支持多种模型提供商：OpenAI, Claude, Kimi, 本地模型
 */

export interface LLMMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  tool_call_id?: string;
}

export interface ToolDefinition {
  type: 'function';
  function: {
    name: string;
    description: string;
    parameters: Record<string, any>;
  };
}

export interface ToolCall {
  id: string;
  type: 'function';
  function: {
    name: string;
    arguments: string;
  };
}

export interface LLMResponse {
  content: string;
  toolCalls?: ToolCall[];
  usage: {
    promptTokens: number;
    completionTokens: number;
    totalTokens: number;
  };
  model: string;
}

export interface LLMConfig {
  provider: 'openai' | 'claude' | 'kimi' | 'ollama' | 'custom' | 'deepseek';
  baseUrl: string;
  apiKey: string;
  model: string;
  temperature: number;
  maxTokens: number;
}

export class LLMService {
  private config: LLMConfig;

  constructor(config?: Partial<LLMConfig>) {
    this.config = {
      provider: config?.provider || (process.env.LLM_PROVIDER as any) || 'kimi',
      baseUrl: config?.baseUrl || process.env.LLM_BASE_URL || 'https://api.kimi.com/coding/v1',
      apiKey: config?.apiKey || process.env.LLM_API_KEY || '',
      model: config?.model || process.env.LLM_MODEL || 'kimi-for-coding',
      temperature: config?.temperature ?? 0.7,
      maxTokens: config?.maxTokens || 2000
    };
  }

  /**
   * 带工具调用的 LLM 调用
   */
  async callWithTools(
    messages: LLMMessage[],
    tools: ToolDefinition[],
    options?: {
      responseFormat?: { type: 'json_object'; schema?: any };
      toolChoice?: 'auto' | 'none' | 'required' | { type: 'function'; function: { name: string } };
    }
  ): Promise<LLMResponse> {
    const response = await fetch(`${this.config.baseUrl}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.config.apiKey}`
      },
      body: JSON.stringify({
        model: this.config.model,
        messages,
        tools: tools.length > 0 ? tools : undefined,
        tool_choice: options?.toolChoice,
        response_format: options?.responseFormat,
        temperature: this.config.temperature,
        max_tokens: this.config.maxTokens
      })
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`LLM API错误: ${response.status} - ${errorText}`);
    }

    const data: any = await response.json();
    const choice = data.choices[0];
    
    return {
      content: choice?.message?.content || '',
      toolCalls: choice?.message?.tool_calls?.map((tc: any) => ({
        id: tc.id,
        type: tc.type,
        function: {
          name: tc.function.name,
          arguments: tc.function.arguments
        }
      })),
      usage: {
        promptTokens: data.usage?.prompt_tokens || 0,
        completionTokens: data.usage?.completion_tokens || 0,
        totalTokens: data.usage?.total_tokens || 0
      },
      model: data.model || this.config.model
    };
  }

  /**
   * 生成RAG回答
   * 基于检索到的文档块生成完整答案
   */
  async generateAnswer(
    query: string,
    retrievedChunks: Array<{ content: string; source: string; score: number }>,
    context?: {
      previousAnswers?: string[];
      contradictions?: Array<{ description: string; severity: string }>;
    }
  ): Promise<{ answer: string; citations: string[] }> {
    const prompt = this.buildRAGPrompt(query, retrievedChunks, context);
    
    try {
      console.log(`[LLMService] 生成回答, 使用模型: ${this.config.model}`);
      
      const response = await this.callLLM(prompt);
      
      // 提取引用标记
      const citations = this.extractCitations(response.content);
      
      console.log(`[LLMService] 生成完成, 引用 ${citations.length} 个来源`);
      
      return {
        answer: response.content,
        citations
      };
    } catch (error) {
      console.error('[LLMService] 生成失败:', error);
      // 降级到模板回答
      return this.generateTemplateAnswer(query, retrievedChunks);
    }
  }

  /**
   * 构建RAG提示词
   */
  private buildRAGPrompt(
    query: string,
    chunks: Array<{ content: string; source: string; score: number }>,
    context?: {
      previousAnswers?: string[];
      contradictions?: Array<{ description: string; severity: string }>;
    }
  ): LLMMessage[] {
    const contextParts = chunks.map((chunk, idx) => {
      const relevance = chunk.score > 0.9 ? '高' : chunk.score > 0.7 ? '中' : '低';
      return `[${idx + 1}] 来源: ${chunk.source} (相关度: ${relevance})
内容: ${chunk.content}`;
    }).join('\n\n');

    let systemPrompt = `你是一个专业的知识助手。请基于提供的参考资料回答问题。

回答要求：
1. 优先使用参考资料中的信息
2. 回答需要准确、完整、有条理
3. 使用 [数字] 格式标注信息来源，如 [1], [2]
4. 如果参考资料不足以回答问题，明确说明
5. 保持客观，不要编造信息`;

    // 如果有矛盾，添加特殊说明
    if (context?.contradictions && context.contradictions.length > 0) {
      const contradictionDesc = context.contradictions
        .map(c => `- ${c.description} (严重程度: ${c.severity})`)
        .join('\n');
      
      systemPrompt += `\n\n注意：参考资料中存在以下矛盾信息，请谨慎处理：
${contradictionDesc}`;
    }

    const userPrompt = `问题：${query}

参考资料：
${contextParts}

请基于以上资料回答问题，并标注信息来源。`;

    return [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: userPrompt }
    ];
  }

  /**
   * 调用LLM API
   */
  private async callLLM(messages: LLMMessage[]): Promise<LLMResponse> {
    const response = await fetch(`${this.config.baseUrl}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.config.apiKey}`
      },
      body: JSON.stringify({
        model: this.config.model,
        messages,
        temperature: this.config.temperature,
        max_tokens: this.config.maxTokens
      })
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`LLM API错误: ${response.status} - ${errorText}`);
    }

    const data: any = await response.json();
    
    return {
      content: data.choices[0]?.message?.content || '',
      usage: {
        promptTokens: data.usage?.prompt_tokens || 0,
        completionTokens: data.usage?.completion_tokens || 0,
        totalTokens: data.usage?.total_tokens || 0
      },
      model: data.model || this.config.model
    };
  }

  /**
   * 提取引用标记
   */
  private extractCitations(content: string): string[] {
    const matches = content.match(/\[(\d+)\]/g);
    if (!matches) return [];
    
    // 去重并提取数字
    const uniqueCitations = [...new Set(matches)];
    return uniqueCitations.map(c => c.replace(/\[|\]/g, ''));
  }

  /**
   * 生成模板回答（降级方案）
   */
  private generateTemplateAnswer(
    query: string,
    chunks: Array<{ content: string; source: string }>
  ): { answer: string; citations: string[] } {
    console.warn('[LLMService] 使用模板回答降级');
    
    const topChunks = chunks.slice(0, 3);
    
    const answer = `基于检索到的${chunks.length}条相关资料，关于"${query}"的回答如下：

${topChunks.map((chunk, idx) => `${idx + 1}. ${chunk.content.slice(0, 200)}... [${idx + 1}]`).join('\n\n')}

以上内容仅供参考。由于模型服务暂时不可用，这是基于检索结果的摘要。`;

    return {
      answer,
      citations: topChunks.map((_, idx) => String(idx + 1))
    };
  }

  /**
   * 快速回答（用于非RAG场景）
   */
  async quickAsk(prompt: string): Promise<string> {
    const messages: LLMMessage[] = [
      {
        role: 'system',
        content: '你是一个有帮助的助手。请简洁准确地回答用户的问题。'
      },
      { role: 'user', content: prompt }
    ];

    try {
      const response = await this.callLLM(messages);
      return response.content;
    } catch (error) {
      console.error('[LLMService] 快速问答失败:', error);
      return '抱歉，模型服务暂时不可用。';
    }
  }

  /**
   * 测试连接
   */
  async testConnection(): Promise<{ success: boolean; message: string }> {
    try {
      const response = await this.quickAsk('Hello, are you working?');
      return {
        success: true,
        message: `连接成功，模型: ${this.config.model}`
      };
    } catch (error) {
      return {
        success: false,
        message: `连接失败: ${error instanceof Error ? error.message : String(error)}`
      };
    }
  }
}

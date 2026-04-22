/**
 * LLM API 服务
 * 通过 Node.js 后端代理访问 LLM API，保护 API Key 不暴露在前端
 */

import { authFetch } from '../utils/auth';

export interface LLMMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface LLMRequest {
  model: string;
  messages: LLMMessage[];
  temperature?: number;
  max_tokens?: number;
  top_p?: number;
  stream?: boolean;
}

export interface LLMResponse {
  id: string;
  choices: {
    index: number;
    message: LLMMessage;
    finish_reason: string;
  }[];
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

export interface LLMStreamChunk {
  id: string;
  choices: {
    index: number;
    delta: {
      content?: string;
      role?: string;
    };
    finish_reason: string | null;
  }[];
}

// 通过 Vite proxy 访问 Python 后端服务
export const API_BASE = import.meta.env.VITE_API_BASE_URL || ''; // 空字符串使用相对路径，由 Vite proxy 转发

/**
 * 发送非流式请求到 LLM
 * 通过 Node.js 后端 /api/llm/chat 代理，保护 API Key
 */
export async function sendLLMRequest(
  messages: LLMMessage[],
  options?: {
    temperature?: number;
    maxTokens?: number;
    topP?: number;
  }
): Promise<LLMResponse> {
  try {
    const response = await authFetch(`${API_BASE}/api/llm/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        model: 'deepseek-chat',
        messages,
        temperature: options?.temperature ?? 0.7,
        max_tokens: options?.maxTokens ?? 2000,
        top_p: options?.topP ?? 0.9,
        stream: false
      })
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`LLM API 错误: ${response.status} - ${errorText}`);
    }

    const result = await response.json();
    // 后端使用 successResponse 包装，实际数据在 result.data 中
    const data = result.data || result;
    return data as LLMResponse;
  } catch (error) {
    console.error('[LLM] 请求失败:', error);
    // 降级：返回友好提示
    return {
      id: `error-${Date.now()}`,
      choices: [{
        index: 0,
        message: {
          role: 'assistant',
          content: error instanceof Error
            ? `❌ LLM 请求失败: ${error.message}`
            : '❌ LLM 服务暂时不可用，请检查后端配置。'
        },
        finish_reason: 'stop'
      }],
      usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 }
    };
  }
}

/**
 * 发送流式请求到 LLM
 * 通过 Node.js 后端 /api/llm/chat 代理，解析 SSE 流
 */
export async function* sendLLMStream(
  messages: LLMMessage[],
  options?: {
    temperature?: number;
    maxTokens?: number;
    topP?: number;
  }
): AsyncGenerator<LLMStreamChunk, void, unknown> {
  try {
    const response = await authFetch(`${API_BASE}/api/llm/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        model: 'deepseek-chat',
        messages,
        temperature: options?.temperature ?? 0.7,
        max_tokens: options?.maxTokens ?? 2000,
        top_p: options?.topP ?? 0.9,
        stream: true
      })
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`LLM API 错误: ${response.status} - ${errorText}`);
    }

    const reader = response.body?.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    if (!reader) {
      throw new Error('无法读取流式响应');
    }

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data: ')) continue;

        const data = trimmed.slice(6);
        if (data === '[DONE]') return;

        try {
          const chunk: LLMStreamChunk = JSON.parse(data);
          yield chunk;
        } catch {
          // 忽略无法解析的行
        }
      }
    }
  } catch (error) {
    console.error('[LLM] 流式请求失败:', error);
    // 降级：返回单条错误消息
    yield {
      id: `error-${Date.now()}`,
      choices: [{
        index: 0,
        delta: {
          content: error instanceof Error
            ? `❌ LLM 请求失败: ${error.message}`
            : '❌ LLM 服务暂时不可用，请检查后端配置。'
        },
        finish_reason: 'stop'
      }]
    };
  }
}

/**
 * 构建 RAG 提示
 */
export function buildRAGPrompt(
  query: string,
  context: string[],
  systemPrompt?: string
): LLMMessage[] {
  const messages: LLMMessage[] = [];

  // 系统提示
  messages.push({
    role: 'system',
    content: systemPrompt || `你是一个基于检索增强生成(RAG)的智能助手。请根据提供的参考资料回答用户问题。

回答要求：
1. 基于提供的参考资料进行回答
2. 如果资料不足，明确告知用户
3. 保持回答简洁、准确
4. 适当引用参考资料中的信息`
  });

  // 构建上下文
  const contextText = context.length > 0
    ? `参考资料：\n\n${context.map((c, i) => `[${i + 1}] ${c}`).join('\n\n')}`
    : '（暂无参考资料）';

  messages.push({
    role: 'user',
    content: `${contextText}\n\n用户问题：${query}`
  });

  return messages;
}

/**
 * 测试 API 连接
 */
export async function testLLMConnection(): Promise<boolean> {
  try {
    const response = await authFetch(`${API_BASE}/api/system/status`);
    return response.ok;
  } catch {
    return false;
  }
}

// ==================== Agent API ====================

export interface AgentRunRequest {
  query: string;
  model?: string;
  apiKey?: string;
  baseUrl?: string;
  maxIterations?: number;
}

export interface AgentIndexReference {
  chunk_id: string;
  doc_id: string;
  page_number: number;
  source_db: string;
}

export interface AgentCalculation {
  formula: string;
  result: number;
  steps: string;
}

export interface AgentRunResponse {
  answer: string;
  indices: AgentIndexReference[];
  calculations: AgentCalculation[];
  confidence: number;
}

/**
 * 运行 Agent
 */
export async function runAgent(request: AgentRunRequest): Promise<AgentRunResponse> {
  const response = await authFetch(`${API_BASE}/api/agent/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request)
  });
  
  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Agent API 调用失败: ${response.status} - ${error}`);
  }
  
  const data = await response.json();
  return data.data;
}

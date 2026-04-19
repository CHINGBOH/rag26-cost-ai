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
 */
export async function sendLLMRequest(
  messages: LLMMessage[],
  _options?: {
    temperature?: number;
    maxTokens?: number;
    topP?: number;
  }
): Promise<LLMResponse> {
  // 由于后端没有LLM API，使用模拟响应
  // _options 参数保留用于未来真实 API 调用

  // 模拟延迟
  // 实际项目中，这里应该调用真实的LLM API

  // 模拟延迟
  await new Promise(resolve => setTimeout(resolve, 1000));

  // 模拟LLM响应
  const userMessage = messages.find(msg => msg.role === 'user');
  let responseContent = '';

  if (userMessage) {
    const query = userMessage.content;
    if (query.includes('你好') || query.includes('Hello')) {
      responseContent = '你好！我是RAG智能助手，很高兴为你服务。请问有什么我可以帮助你的吗？';
    } else if (query.includes('搜索') || query.includes('查找')) {
      responseContent = '我已经在知识库中搜索了相关信息，为你找到了以下内容...';
    } else if (query.includes('代码') || query.includes('编程')) {
      responseContent = '以下是你需要的代码实现：\n\n```python\ndef hello_world():\n    print("Hello, World!")\n```\n\n这段代码可以输出"Hello, World!"到控制台。';
    } else {
      responseContent = `我理解你的问题："${query}"。\n\n这是一个模拟的LLM响应。在实际系统中，我会基于检索到的相关文档来回答你的问题，提供更准确和详细的信息。`;
    }
  } else {
    responseContent = '我收到了你的消息，但是没有找到用户输入内容。请尝试重新输入你的问题。';
  }

  // 转换为前端期望的格式
  return {
    id: Date.now().toString(),
    choices: [{
      index: 0,
      message: {
        role: 'assistant',
        content: responseContent
      },
      finish_reason: 'stop'
    }],
    usage: {
      prompt_tokens: 0,
      completion_tokens: responseContent.length,
      total_tokens: responseContent.length
    }
  };
}

/**
 * 发送流式请求到 LLM
 */
export async function* sendLLMStream(
  messages: LLMMessage[],
  _options?: {
    temperature?: number;
    maxTokens?: number;
    topP?: number;
  }
): AsyncGenerator<LLMStreamChunk, void, unknown> {
  // 由于后端没有LLM API，使用模拟响应
  // _options 参数保留用于未来真实 API 调用

  // 模拟延迟
  await new Promise(resolve => setTimeout(resolve, 500));

  // 模拟LLM响应
  const userMessage = messages.find(msg => msg.role === 'user');
  let responseContent = '';
  
  if (userMessage) {
    const query = userMessage.content;
    if (query.includes('你好') || query.includes('Hello')) {
      responseContent = '你好！我是RAG智能助手，很高兴为你服务。请问有什么我可以帮助你的吗？';
    } else if (query.includes('搜索') || query.includes('查找')) {
      responseContent = '我已经在知识库中搜索了相关信息，为你找到了以下内容...';
    } else if (query.includes('代码') || query.includes('编程')) {
      responseContent = '以下是你需要的代码实现：\n\n```python\ndef hello_world():\n    print("Hello, World!")\n```\n\n这段代码可以输出"Hello, World!"到控制台。';
    } else {
      responseContent = `我理解你的问题："${query}"。\n\n这是一个模拟的LLM响应。在实际系统中，我会基于检索到的相关文档来回答你的问题，提供更准确和详细的信息。`;
    }
  } else {
    responseContent = '我收到了你的消息，但是没有找到用户输入内容。请尝试重新输入你的问题。';
  }
  
  // 模拟流式输出
  for (let i = 0; i < responseContent.length; i++) {
    await new Promise(resolve => setTimeout(resolve, 20));
    yield {
      id: Date.now().toString(),
      choices: [{
        index: 0,
        delta: {
          content: responseContent[i]
        },
        finish_reason: null
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

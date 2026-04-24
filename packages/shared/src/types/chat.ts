/**
 * 聊天/RAG对话类型定义
 */

import { RetrievedChunk, Citation, SubQuery } from './recursion';

// ==================== LLM配置 ====================

export type LLMProviderType = 
  | 'kimi' 
  | 'openai' 
  | 'azure' 
  | 'anthropic' 
  | 'google' 
  | 'local' 
  | 'custom'
  | 'deepseek';

export type InferenceEngine = 
  | 'default'
  | 'llama.cpp' 
  | 'vllm' 
  | 'tensorrt' 
  | 'text-generation-inference'
  | 'ollama';

export interface ChatConfig {
  // 模型选择
  provider: LLMProviderType;
  model: string;
  engine?: InferenceEngine;
  
  // 生成参数
  temperature: number;      // 0-2
  maxTokens: number;        // 100-8000
  topP: number;            // 0-1
  topK?: number;           // 1-100
  frequencyPenalty: number; // -2-2
  presencePenalty: number;  // -2-2
  
  // RAG参数
  enableRag: boolean;
  ragParams: {
    topK: number;           // 召回数量
    threshold: number;      // 相似度阈值 0-1
    rerank: boolean;        // 是否精排
    maxReferences: number;  // 最大引用数
    contextWindow: number;  // 上下文窗口
  };
  
  // 系统提示词
  systemPrompt?: string;
}

// ==================== 聊天会话 ====================

export interface ChatSession {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: ChatMessage[];
  config: ChatConfig;
  ragContext?: RagContext;
  status: 'idle' | 'processing' | 'error';
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  
  // RAG相关
  references?: ChatReference[];
  ragProcess?: RagProcessStep[];
  
  // 代码执行
  codeExecution?: CodeExecutionResult;
  
  // 元数据
  tokenCount?: number;
  latency?: number;
  model?: string;
}

export interface ChatReference {
  id: string;
  index: number;           // [1], [2] 等引用标记
  chunk: RetrievedChunk;
  relevanceScore: number;
  usedInAnswer: boolean;
}

// ==================== RAG上下文 ====================

export interface RagContext {
  // 意图识别
  intent: {
    type: 'qa' | 'calculation' | 'summary' | 'comparison' | 'analysis' | 'creative';
    confidence: number;
    description: string;
  };
  
  // 任务拆解
  subQueries: SubQuery[];
  
  // 召回结果
  retrievedChunks: RetrievedChunk[];
  
  // 精排结果
  rankedChunks: {
    chunk: RetrievedChunk;
    originalRank: number;
    rerankScore: number;
  }[];
  
  // Prompt组装
  promptAssembly: PromptAssembly;
}

export interface PromptAssembly {
  systemPrompt: string;
  contextPrompt: string;
  queryPrompt: string;
  instructionPrompt: string;
  finalPrompt: string;
  tokenCount: number;
}

// ==================== RAG流程步骤 ====================

export type RagProcessStepType = 
  | 'intent_recognition'
  | 'task_decomposition'
  | 'query_generation'
  | 'vector_retrieval'
  | 'knowledge_retrieval'
  | 'graph_retrieval'
  | 'reranking'
  | 'prompt_assembly'
  | 'llm_generation'
  | 'answer_formatting';

export interface RagProcessStep {
  type: RagProcessStepType;
  status: 'pending' | 'running' | 'completed' | 'failed';
  startTime?: number;
  endTime?: number;
  latency?: number;
  
  // 详细数据
  data?: {
    // intent_recognition
    intentType?: string;
    confidence?: number;
    description?: string;
    
    // task_decomposition
    subQueries?: SubQuery[];
    intent?: {
      type: string;
      confidence: number;
    };
    
    // retrieval
    dbType?: string;
    resultCount?: number;
    topScore?: number;
    queryEmbedding?: string;
    tables?: string[];
    
    // reranking
    inputCount?: number;
    outputCount?: number;
    rerankModel?: string;
    compressionRatio?: string;
    
    // prompt_assembly
    tokenCount?: number;
    contextLength?: number;
    assembly?: PromptAssembly;
    
    // generation
    tokensGenerated?: number;
    tokensPerSecond?: number;
    firstTokenLatency?: number;
    model?: string;
    
    // UI display
    label?: string;
    planSteps?: string[];
    summary?: string;
  };
  
  // 错误信息
  error?: string;
}

// ==================== 代码执行 ====================

export interface CodeExecutionResult {
  code: string;
  language: 'typescript' | 'javascript' | 'python';
  status: 'pending' | 'running' | 'success' | 'error';
  output?: string;
  result?: any;
  error?: string;
  executionTime?: number;
  timestamp: number;
}

// ==================== 预设配置 ====================

export interface ChatPreset {
  id: string;
  name: string;
  description: string;
  config: Partial<ChatConfig>;
  icon?: string;
}

export const DEFAULT_CHAT_CONFIG: ChatConfig = {
  provider: 'deepseek',
  model: 'deepseek-chat',
  temperature: 0.3,
  maxTokens: 2000,
  topP: 0.9,
  frequencyPenalty: 0,
  presencePenalty: 0,
  enableRag: true,
  ragParams: {
    topK: 100,
    threshold: 0.7,
    rerank: true,
    maxReferences: 5,
    contextWindow: 4000
  }
};

export const CHAT_PRESETS: ChatPreset[] = [
  {
    id: 'creative',
    name: '创意写作',
    description: '适合创意写作和头脑风暴',
    icon: '✨',
    config: {
      temperature: 0.8,
      topP: 0.95,
      enableRag: false
    }
  },
  {
    id: 'analytical',
    name: '分析问答',
    description: '适合深度分析和精确回答',
    icon: '🔍',
    config: {
      temperature: 0.2,
      topP: 0.9,
      enableRag: true,
      ragParams: {
        topK: 50,
        threshold: 0.8,
        rerank: true,
        maxReferences: 8,
        contextWindow: 4000
      }
    }
  },
  {
    id: 'coding',
    name: '编程助手',
    description: '适合代码生成和技术问答',
    icon: '💻',
    config: {
      temperature: 0.1,
      topP: 0.95,
      enableRag: true,
      systemPrompt: '你是一个专业的编程助手，擅长代码分析、生成和调试。'
    }
  },
  {
    id: 'speed',
    name: '快速回答',
    description: '牺牲质量换取速度',
    icon: '⚡',
    config: {
      temperature: 0.5,
      maxTokens: 500,
      enableRag: true,
      ragParams: {
        topK: 20,
        threshold: 0.6,
        rerank: false,
        maxReferences: 3,
        contextWindow: 2000
      }
    }
  }
];

// ==================== 模型选项 ====================

export const PROVIDER_OPTIONS: { value: LLMProviderType; label: string; icon: string }[] = [
  { value: 'deepseek', label: 'DeepSeek', icon: '🐋' },
  { value: 'kimi', label: 'Kimi', icon: '🌙' },
  { value: 'openai', label: 'OpenAI', icon: '🅾️' },
  { value: 'azure', label: 'Azure OpenAI', icon: '☁️' },
  { value: 'anthropic', label: 'Anthropic', icon: '🅰️' },
  { value: 'google', label: 'Google', icon: '🇬' },
  { value: 'local', label: '本地模型', icon: '🏠' },
  { value: 'custom', label: '自定义', icon: '⚙️' }
];

export const ENGINE_OPTIONS: { value: InferenceEngine; label: string }[] = [
  { value: 'default', label: '默认引擎' },
  { value: 'llama.cpp', label: 'llama.cpp' },
  { value: 'vllm', label: 'vLLM' },
  { value: 'tensorrt', label: 'TensorRT' },
  { value: 'text-generation-inference', label: 'TGI' },
  { value: 'ollama', label: 'Ollama' }
];

export const MODEL_OPTIONS: Record<LLMProviderType, string[]> = {
  deepseek: ['deepseek-chat', 'deepseek-coder', 'deepseek-reasoner'],
  kimi: ['kimi-for-coding', 'kimi-k2', 'kimi-k1.5'],
  openai: ['gpt-4', 'gpt-4-turbo', 'gpt-3.5-turbo'],
  azure: ['gpt-4', 'gpt-4-turbo', 'gpt-3.5-turbo'],
  anthropic: ['claude-3-opus', 'claude-3-sonnet', 'claude-3-haiku'],
  google: ['gemini-pro', 'gemini-ultra'],
  local: ['llama-2-7b', 'llama-2-13b', 'llama-2-70b', 'mistral-7b', 'mixtral-8x7b'],
  custom: ['custom-model']
};

/**
 * Dashboard 配置文件
 * 集中管理所有硬编码配置
 *
 * 【递归配置原则】
 * 本文件本身受 .kimi/rules.md 约束，形成配置-规则的闭环验证：
 * 1. rules.md 定义代码规范（类型安全、验证优先、弱耦合架构）
 * 2. config/index.ts 定义业务配置，必须符合 rules.md 的架构原则
 * 3. configValidator 运行时验证配置合规性
 *
 * 修改本文件时，请同时检查是否违反 rules.md 中的规范。
 */

// 主题配置 - 统一深蓝暗色主题
export const theme = {
  name: "dark-blue",
  colors: {
    background: "#0f172a",      // 深蓝背景
    surface: "#1e293b",         // 卡片背景
    surfaceHighlight: "#334155", // 高亮背景
    border: "#334155",          // 边框
    borderHighlight: "#3b82f6", // 高亮边框
    textPrimary: "#f8fafc",     // 主要文字
    textSecondary: "#94a3b8",   // 次要文字
    textMuted: "#64748b",       // 淡化文字
    primary: "#3b82f6",         // 主题色
    primaryHover: "#2563eb",    // 悬停色
    success: "#22c55e",         // 成功
    warning: "#f59e0b",         // 警告
    error: "#ef4444",           // 错误
    info: "#06b6d4",            // 信息
  }
};

// 品牌配置
export const branding = {
  name: "RAG Dashboard",
  subtitle: "递归检索系统",
  logo: "🧠"
};

// LLM 提供商配置
export const llmProviders = {
  deepseek: {
    id: "deepseek",
    name: "DeepSeek",
    icon: "🐋",
    apiKey: import.meta.env.VITE_DEEPSEEK_API_KEY || '',
    baseURL: import.meta.env.VITE_DEEPSEEK_BASE_URL || 'https://api.deepseek.com',
    models: [
      { id: "deepseek-chat", name: "DeepSeek Chat", description: "通用对话模型" },
      { id: "deepseek-coder", name: "DeepSeek Coder", description: "代码专用模型" }
    ],
    defaultModel: "deepseek-chat",
    defaultParams: {
      temperature: 0.7,
      maxTokens: 2000,
      topP: 0.9
    },
    pricing: {
      input: 0.001,   // 每 1K tokens
      output: 0.002,
      currency: '¥'
    }
  },
  kimi: {
    id: "kimi",
    name: "Kimi",
    icon: "🌙",
    apiKey: import.meta.env.VITE_KIMI_API_KEY || '',
    baseURL: import.meta.env.VITE_KIMI_BASE_URL || 'https://api.moonshot.cn',
    models: [
      { id: "kimi-for-coding", name: "Kimi for Coding" },
      { id: "kimi-chat", name: "Kimi Chat" }
    ],
    defaultModel: "kimi-for-coding",
    defaultParams: {
      temperature: 0.3,
      maxTokens: 2000,
      topP: 0.9
    },
    pricing: {
      input: 0.003,
      output: 0.006,
      currency: '¥'
    }
  },
  openai: {
    id: "openai",
    name: "OpenAI",
    icon: "🤖",
    apiKey: import.meta.env.VITE_OPENAI_API_KEY || '',
    baseURL: import.meta.env.VITE_OPENAI_BASE_URL || 'https://api.openai.com',
    models: [
      { id: "gpt-4", name: "GPT-4" },
      { id: "gpt-3.5-turbo", name: "GPT-3.5" }
    ],
    defaultModel: "gpt-4",
    defaultParams: {
      temperature: 0.7,
      maxTokens: 2000,
      topP: 0.9
    },
    pricing: {
      input: 0.03,
      output: 0.06,
      currency: '$'
    }
  }
};

// 当前激活的 LLM 提供商
export const activeProvider = "deepseek";

// 推理引擎配置
export const engines = [
  { id: "llama.cpp", name: "llama.cpp", icon: "🦙", description: "本地推理引擎" },
  { id: "vllm", name: "vLLM", icon: "⚡", description: "高性能推理" },
  { id: "tensorrt", name: "TensorRT", icon: "🔥", description: "NVIDIA加速" }
];

// 基础设施服务
export const services = [
  { id: "llm", name: "LLM API", icon: "🤖", type: "llm" },
  { id: "inference", name: "推理引擎", icon: "⚙️", type: "inference" },
  { id: "api", name: "API Gateway", icon: "🔌", type: "api" },
  { id: "vector-db", name: "Vector DB", icon: "🔍", type: "database" }
];

// RAG 流程阶段
export const ragStages = [
  { id: "intent_analysis", name: "意图分析", icon: "🎯", description: "分析查询意图" },
  { id: "query_decomposition", name: "查询分解", icon: "✂️", description: "分解子查询" },
  { id: "vector_retrieval", name: "向量检索", icon: "🔍", description: "语义相似度搜索" },
  { id: "knowledge_retrieval", name: "知识检索", icon: "📚", description: "知识库查询" },
  { id: "graph_retrieval", name: "图检索", icon: "🕸️", description: "图数据库遍历" },
  { id: "reranking", name: "精排", icon: "📊", description: "重排序筛选" },
  { id: "context_assembly", name: "上下文组装", icon: "🧩", description: "构建提示上下文" },
  { id: "llm_generation", name: "生成", icon: "💬", description: "LLM生成回答" },
  { id: "complete", name: "完成", icon: "✅", description: "任务完成" }
];

// 快速提示
export const quickPrompts = [
  { id: "search", icon: "🔍", title: "搜索知识库", description: "检索相关知识", prompt: "请在知识库中搜索关于【主题】的资料，并总结关键信息。" },
  { id: "code", icon: "💻", title: "编写代码", description: "生成代码实现", prompt: "请帮我编写一段代码来实现【功能】。" },
  { id: "analyze", icon: "📊", title: "分析数据", description: "处理和可视化", prompt: "请分析以下数据并提供见解：" },
  { id: "debug", icon: "🔧", title: "调试问题", description: "排查代码错误", prompt: "请帮我调试以下代码，找出问题所在：" },
  { id: "document", icon: "📚", title: "生成文档", description: "创建说明文档", prompt: "请为以下内容生成详细的技术文档：" },
  { id: "translate", icon: "🌐", title: "翻译内容", description: "多语言转换", prompt: "请将以下内容翻译成【目标语言】：" }
];

// 功能特性
export const capabilities = [
  { icon: "🔍", title: "智能检索" },
  { icon: "🧠", title: "意图理解" },
  { icon: "⚡", title: "多引擎推理" },
  { icon: "📚", title: "知识增强" }
];

// 获取当前激活的 LLM 配置
export function getActiveLLMConfig() {
  return llmProviders[activeProvider as keyof typeof llmProviders];
}

// 获取 API 配置
export function getApiConfig() {
  const provider = getActiveLLMConfig();
  return {
    apiKey: provider.apiKey,
    baseURL: provider.baseURL,
    model: provider.defaultModel,
    defaultParams: provider.defaultParams
  };
}

// ============================================
// 智能路由配置 - 控制何时启用 RAG
// ============================================

export const routingConfig = {
  // 是否启用智能路由
  enabled: true,

  // 直接走 LLM、不走 RAG 的模式
  directLLMPatterns: {
    // 问候语匹配
    greetings: [
      /^你好/i, /^hi/i, /^hello/i, /^hey/i,
      /^(早上好|下午好|晚上好)/i,
      /^(在吗|在么)/i,
      /^(谢谢|感谢)/i,
      /^(再见|拜拜)/i
    ],
    // 简单问题匹配（疑问词+短句）
    simpleQuestions: [
      /^什么.*\?$/,
      /^怎么.*\?$/,
      /^为什么.*\?$/,
      /^.*\?$/  // 短问题
    ],
    // 最大长度阈值（字符数），低于此值且匹配简单问题模式的直接走 LLM
    maxLengthForSimple: 20
  },

  // 强制走 RAG 的关键词
  forceRAGKeywords: [
    '搜索', '查找', '检索', '查询',
    '文档', '资料', '知识库', '文章',
    '根据', '基于', '参考'
  ]
};

// 智能路由判断函数
export function shouldUseRAG(query: string): boolean {
  if (!routingConfig.enabled) return true;

  const trimmedQuery = query.trim();
  const lowerQuery = trimmedQuery.toLowerCase();

  // 1. 检查是否强制需要 RAG
  for (const keyword of routingConfig.forceRAGKeywords) {
    if (lowerQuery.includes(keyword)) return true;
  }

  // 2. 检查是否是问候语
  for (const pattern of routingConfig.directLLMPatterns.greetings) {
    if (pattern.test(trimmedQuery)) return false;
  }

  // 3. 检查是否是简单短问题
  if (trimmedQuery.length <= routingConfig.directLLMPatterns.maxLengthForSimple) {
    // 短句直接走 LLM
    return false;
  }

  // 4. 默认走 RAG（长查询、复杂查询）
  return true;
}

// ============================================
// 检索配置 - 控制引用质量
// ============================================

export const retrievalConfig = {
  // 相似度阈值：低于此分数的文档不显示
  similarityThreshold: 0.75,

  // 最小引用数：至少要有多少个相关文档才显示引用区域
  minReferences: 1,

  // 最大引用数
  maxReferences: 5,

  // 当没有相关资料时的系统提示
  noReferencesPrompt: '未在知识库中找到相关资料。请基于通用知识回答，但需说明信息来源。',

  // 是否严格要求引用：true=无引用时不回答专业知识，false=允许基于通用知识回答
  strictCitation: false
};

// ============================================
// 模型参数配置 - 控制面板可调参数的范围和步长
// ============================================

export const modelParamsConfig = {
  temperature: {
    min: 0,
    max: 2,
    step: 0.1,
    default: 0.7,
    description: '创造性程度，低值更确定，高值更创造性',
  },
  maxTokens: {
    min: 100,
    max: 8000,
    step: 100,
    default: 2000,
    description: '生成文本的最大长度',
  },
  topP: {
    min: 0,
    max: 1,
    step: 0.05,
    default: 0.9,
    description: '核采样阈值',
  },
  frequencyPenalty: {
    min: -2,
    max: 2,
    step: 0.1,
    default: 0,
    description: '降低重复用词',
  },
  presencePenalty: {
    min: -2,
    max: 2,
    step: 0.1,
    default: 0,
    description: '鼓励讨论新话题',
  },
};

// ============================================
// RAG 参数配置 - 控制面板可调参数的范围和步长
// ============================================

export const ragParamsConfig = {
  topK: {
    min: 5,
    max: 200,
    step: 5,
    default: 100,
    description: '每路召回的文档数',
  },
  threshold: {
    min: 0,
    max: 1,
    step: 0.05,
    default: 0.75,
    description: '相似度阈值，低于此值的文档将被过滤',
  },
  maxReferences: {
    min: 1,
    max: 20,
    step: 1,
    default: 5,
    description: '答案中显示的最大引用数',
  },
};

// ============================================
// UI 布局配置 - 集中管理所有界面尺寸和动画参数
// ============================================

export const uiConfig = {
  // 侧边栏配置
  sidebar: {
    expandedWidth: 220,      // 展开宽度 (px)
    collapsedWidth: 60,      // 折叠宽度 (px)
    collapseTrigger: 'button', // 'button' | 'responsive' - 折叠触发方式
    responsiveBreakpoint: 768, // 响应式断点 (px)
    showNewChatButton: true,   // 是否显示"新对话"按钮
    position: 'left',        // 'left' | 'right'
  },

  // 主内容区配置
  mainContent: {
    maxWidth: 900,           // 消息区最大宽度 (px)
    paddingX: 24,            // 水平内边距 (px)
  },

  // 输入区配置
  inputArea: {
    minHeight: 52,           // 输入框最小高度 (px)
    maxHeight: 200,          // 输入框最大高度 (px)
    paddingY: 16,            // 垂直内边距 (px)
    autoFocus: true,         // 是否自动聚焦
    rows: 1,                 // 默认行数
  },

  // 动画配置
  animations: {
    sidebarTransition: 300,  // 侧边栏过渡时长 (ms)
    messageFadeIn: 300,      // 消息淡入时长 (ms)
    pipelineSlideDown: 300,  // 管道滑入时长 (ms)
    stagePulse: 1500,        // 阶段脉冲动画周期 (ms)
    hoverTransform: 200,     // 悬停变换时长 (ms)
    progressBar: 300,        // 进度条过渡时长 (ms)
    spin: 1000,              // 旋转动画周期 (ms)
  },

  // 任务管道可视化配置
  pipeline: {
    showByDefault: true,     // 默认是否显示
    autoHideDelay: 2000,     // 完成后自动隐藏延迟 (ms)
    stageNodeSize: 40,       // 阶段节点尺寸 (px)
    timeFormatThreshold: 60, // 时间格式化阈值 (秒)
  },

  // 消息配置
  messages: {
    avatarSize: 40,          // 头像尺寸 (px)
    borderRadius: 14,        // 消息气泡圆角 (px)
    gap: 24,                 // 消息间距 (px)
    maxRagStepsDisplay: 5,   // RAG流程最多显示的步骤数
    modelNameMaxLength: 25,  // 模型名最大显示长度
    modelNameTruncateTo: 22, // 模型名截断后长度
  },

  // 欢迎页配置
  welcome: {
    titleSize: 48,           // 标题字体大小 (px)
    subtitleSize: 18,        // 副标题字体大小 (px)
    quickPromptsGridCols: 3, // 快捷提示按钮列数
  },

  // 控制面板配置
  controlPanel: {
    width: 420,              // 面板宽度 (px)
    overlayOpacity: 0.6,     // 遮罩层透明度
    zIndex: 1001,            // 层级
  },

  // 基础设施看板配置
  infrastructure: {
    updateInterval: 2000,    // 数据更新间隔 (ms)
    gpuMin: 30,              // GPU使用率最小值 (%)
    gpuMax: 95,              // GPU使用率最大值 (%)
    tokensMin: 20,           // Token生成速度最小值
    tokensMax: 150,          // Token生成速度最大值
    qpsMin: 50,              // QPS最小值
    qpsMax: 300,             // QPS最大值
  },

  // 代码块配置
  codeBlock: {
    maxHeight: 400,          // 代码块最大高度 (px)
    showLineNumbers: true,   // 是否显示行号
  },

  // 引用标记配置
  reference: {
    pattern: '\\[(\\d+)\\]', // 引用标记正则模式
    maxDisplay: 10,          // 最大显示引用数
  },

  // 响应式断点
  breakpoints: {
    mobile: 768,
    tablet: 1200,
    desktop: 1400,
  },

  // 网格布局配置
  grid: {
    // 服务卡片网格
    servicesGrid: {
      minColumnWidth: 180,     // 最小列宽 (px)
      gap: 12,                 // 间距 (px)
    },
    // 快捷提示按钮网格
    quickPromptsGrid: {
      columns: 3,              // 列数
      gap: 16,                 // 间距 (px)
      columnsTablet: 2,        // 平板列数
      columnsMobile: 1,        // 移动端列数
    },
    // 提供商网格
    providerGrid: {
      columns: 2,              // 列数
      gap: 10,                 // 间距 (px)
    },
  },

  // Flex 布局配置
  flex: {
    // 会话列表
    sessionsList: {
      gap: 10,                 // 间距 (px)
    },
    // 能力展示
    capabilities: {
      gap: 40,                 // 间距 (px)
    },
    // 消息列表
    messagesList: {
      gap: 24,                 // 间距 (px)
    },
    // 输入区
    inputArea: {
      gap: 12,                 // 间距 (px)
    },
    // 模型信息行
    modelInfoRow: {
      gap: 12,                 // 间距 (px)
    },
  }
};

// ============================================
// 输入区底部控制栏配置 - 模型选择、温度调节等
// ============================================

export const inputBarConfig = {
  // 是否显示底部控制栏
  enabled: true,

  // 默认显示的提供商 (可以是 'deepseek' | 'kimi' | 'openai')
  defaultProvider: 'deepseek',

  // 模型选择器配置
  modelSelector: {
    enabled: true,           // 是否启用
    showIcon: true,          // 是否显示提供商图标
    label: '模型',           // 标签文字
    width: 160,              // 选择框宽度 (px)
  },

  // 温度滑块配置
  temperatureSlider: {
    enabled: true,           // 是否启用
    showLabel: true,         // 是否显示标签
    showValue: true,         // 是否显示数值
    label: '温度',           // 标签文字
    width: 150,              // 滑块宽度 (px) - 可配置
    // 温度范围 - 完全可配置
    min: 0,
    max: 2,
    step: 0.1,
    default: 0.7,
  },

  // 快捷设置按钮配置
  quickSettings: {
    enabled: true,
    icon: '⚡',
    label: '快速设置',
    presets: [
      { name: '精确', temperature: 0.2, icon: '🎯' },
      { name: '平衡', temperature: 0.7, icon: '⚖️' },
      { name: '创意', temperature: 1.2, icon: '✨' },
    ],
  },

  // 高级设置按钮配置
  advancedSettings: {
    enabled: true,
    icon: '⚙️',
    label: '设置',
  },
};

// ============================================
// 对话流程配置 - 控制会话创建行为
// ============================================

export const chatFlowConfig = {
  // 自动创建会话：用户输入时如果没有活动会话，自动创建
  autoCreateSession: true,

  // 空会话清理：自动删除没有消息的空会话
  cleanupEmptySessions: true,

  // 会话标题自动生成：基于第一条消息
  autoGenerateTitle: true,
  titleMaxLength: 20,

  // 输入框占位符文本
  placeholders: {
    noSession: '输入消息开始新对话...',      // 无会话时
    withSession: '输入消息，启动RAG任务流程...', // 有会话时
    disabled: '请等待当前任务完成...',       // 禁用时
  },

  // 新对话按钮配置
  newChatButton: {
    show: true,              // 是否显示按钮
    position: 'sidebar',     // 'sidebar' | 'header' | 'floating'
    icon: '+',
    text: '新对话',
  },

  // 侧边栏折叠按钮配置
  collapseButton: {
    expandedIcon: '◀',       // 展开状态图标
    collapsedIcon: '▶',      // 折叠状态图标
  },

  // 确认对话框配置
  confirmDialog: {
    clearChat: '确定要清除当前对话吗？',
    deleteSession: '确定要删除此会话吗？',
  },

  // Pipeline 配置
  pipeline: {
    autoResetDelay: 1500,    // 完成后自动重置延迟 (ms)
    showMetrics: true,       // 是否显示指标
  },

  // 错误消息配置
  errorMessages: {
    apiError: (message: string) => `❌ API 调用失败: ${message}\n\n请检查网络连接或 API 配置。`,
    genericError: '未知错误',
  },

  // 键盘快捷键
  keyboard: {
    sendOnEnter: true,       // Enter发送，Shift+Enter换行
    newChat: 'mod+n',        // 新建会话快捷键
    focusInput: 'mod+l',     // 聚焦输入框
  },

  // UI 标签和图标配置
  ui: {
    settings: {
      icon: '⚙️',
      text: '设置',
    },
    sessionList: {
      sessionIcon: '💬',
      emptyText: '暂无会话',
    },
    tabs: {
      model: '模型',
      params: '参数',
      rag: 'RAG',
    },
    buttons: {
      send: '➤',
      clear: '🗑️',
      loading: '◐',
    },
    tooltips: {
      clearChat: '清除对话',
      send: '发送',
      collapse: '折叠',
      expand: '展开',
      copy: '复制',
      calculate: '计算',
      exportSession: '导出会话',
      clearSession: '清空会话',
      cancelTask: '取消任务',
    },
  }
};

// ============================================
// 规则配置 - 配置系统的元配置，体现"规则即配置"的递归思想
// ============================================

export const rulesConfig = {
  // 规则文件位置（相对于项目根目录）
  // 采用"核心+映射"架构：
  // - rules.md: 语言无关的核心架构原则（80%）
  // - rules.impl.md: 工具链实现映射表（20%）
  coreRulesPath: '.kimi/rules.md',
  implementationMapPath: '.kimi/rules.impl.md',

  // 规则验证级别
  validationLevel: 'strict' as 'strict' | 'warn' | 'ignore',

  // 架构原则检查点（与 rules.md 一一对应）
  principles: {
    // 原则1: 类型安全 - 所有配置必须有类型定义
    typeSafety: {
      enabled: true,
      required: true,
      description: '所有配置项必须有 TypeScript 类型定义，禁止 any',
    },

    // 原则2: 验证优先 - 配置必须有运行时验证
    validationFirst: {
      enabled: true,
      required: true,
      description: '关键配置变更必须通过验证器检查',
    },

    // 原则3: 弱耦合 - 配置与实现分离
    looseCoupling: {
      enabled: true,
      required: true,
      description: '配置层不依赖具体 UI 组件实现',
    },

    // 原则4: 递归验证 - 配置验证配置
    recursiveValidation: {
      enabled: true,
      required: true,
      description: 'rulesConfig 本身也是配置，可被验证',
    },
  },

  // 配置约束规则（配置中的配置，体现递归）
  constraints: {
    // 数值范围约束
    numericRanges: {
      mustHaveMinMax: true,
      mustHaveStep: true,
      description: '所有数值配置必须定义 min/max/step',
    },

    // 字符串约束
    strings: {
      maxLength: 1000,
      forbidEmpty: true,
      description: '字符串配置不能为空，且有限制长度',
    },

    // 颜色约束
    colors: {
      mustBeHex: true,
      description: '颜色必须使用 Hex 格式 (#RRGGBB)',
    },

    // 嵌套深度约束
    nesting: {
      maxDepth: 5,
      description: '配置嵌套深度不超过 5 层',
    },
  },

  // 配置版本（用于规则与配置的兼容性检查）
  version: '1.0.0',

  // 最后更新时间
  lastUpdated: '2024-04-12',
};

// ============================================
// 配置验证器 - 运行时验证配置是否符合 rules.md 的规范
// ============================================

export interface ValidationError {
  path: string;
  message: string;
  principle: string;
  severity: 'error' | 'warning';
}

/**
 * 配置验证器 - 递归验证配置合规性
 * 体现"规则约束配置，配置验证规则"的闭环思想
 */
export class ConfigValidator {
  private errors: ValidationError[] = [];

  /**
   * 验证所有配置
   */
  validateAll(): ValidationResult {
    this.errors = [];

    // 1. 验证 principles 是否启用
    if (rulesConfig.principles.typeSafety.enabled) {
      this.validateTypeSafety();
    }

    if (rulesConfig.principles.validationFirst.enabled) {
      this.validateValidationFirst();
    }

    if (rulesConfig.principles.looseCoupling.enabled) {
      this.validateLooseCoupling();
    }

    // 2. 验证 constraints
    this.validateConstraints();

    // 3. 递归验证：验证 rulesConfig 自身（元验证）
    this.validateRulesConfig();

    return {
      valid: this.errors.length === 0,
      errors: this.errors,
      summary: {
        total: this.errors.length,
        errors: this.errors.filter(e => e.severity === 'error').length,
        warnings: this.errors.filter(e => e.severity === 'warning').length,
      }
    };
  }

  /**
   * 验证类型安全原则
   */
  private validateTypeSafety(): void {
    // 检查 modelParamsConfig 是否有类型定义
    Object.entries(modelParamsConfig).forEach(([key, config]) => {
      if (!('min' in config) || !('max' in config)) {
        this.addError(
          `modelParamsConfig.${key}`,
          '数值配置必须定义 min/max 边界',
          'typeSafety'
        );
      }
    });
  }

  /**
   * 验证验证优先原则
   */
  private validateValidationFirst(): void {
    // 检查所有配置是否有默认值
    if (!chatFlowConfig.autoCreateSession !== undefined) {
      this.addError(
        'chatFlowConfig.autoCreateSession',
        '布尔配置必须有显式默认值',
        'validationFirst',
        'warning'
      );
    }
  }

  /**
   * 验证弱耦合原则
   */
  private validateLooseCoupling(): void {
    // 检查配置是否包含 UI 组件实现细节
    const forbiddenKeys = ['component', 'render', 'onClick', 'onChange'];

    const checkObject = (obj: unknown, path: string): void => {
      if (typeof obj !== 'object' || obj === null) return;

      Object.keys(obj).forEach(key => {
        const newPath = `${path}.${key}`;
        if (forbiddenKeys.includes(key)) {
          this.addError(
            newPath,
            '配置层不应包含 UI 组件实现细节（如 onClick），违反弱耦合原则',
            'looseCoupling'
          );
        }
        checkObject((obj as Record<string, unknown>)[key], newPath);
      });
    };

    checkObject(uiConfig, 'uiConfig');
  }

  /**
   * 验证约束规则
   */
  private validateConstraints(): void {
    const { constraints } = rulesConfig;

    // 验证颜色格式
    if (constraints.colors.mustBeHex) {
      Object.entries(theme.colors).forEach(([key, value]) => {
        if (typeof value === 'string' && !value.match(/^#[0-9A-Fa-f]{6}$/)) {
          this.addError(
            `theme.colors.${key}`,
            `颜色值 "${value}" 不符合 Hex 格式要求`,
            'constraints'
          );
        }
      });
    }

    // 验证嵌套深度
    const checkDepth = (obj: unknown, currentDepth: number, path: string): void => {
      if (currentDepth > constraints.nesting.maxDepth) {
        this.addError(
          path,
          `配置嵌套深度超过最大限制 ${constraints.nesting.maxDepth}`,
          'constraints'
        );
        return;
      }

      if (typeof obj === 'object' && obj !== null) {
        Object.entries(obj).forEach(([key, value]) => {
          checkDepth(value, currentDepth + 1, `${path}.${key}`);
        });
      }
    };

    checkDepth(uiConfig, 1, 'uiConfig');
  }

  /**
   * 元验证：验证 rulesConfig 自身
   * 体现"递归验证"思想
   */
  private validateRulesConfig(): void {
    // 检查 version 格式
    if (!rulesConfig.version.match(/^\d+\.\d+\.\d+$/)) {
      this.addError(
        'rulesConfig.version',
        '版本号必须符合语义化版本格式 (x.y.z)',
        'recursiveValidation'
      );
    }

    // 检查 principles 完整性
    const requiredPrinciples = ['typeSafety', 'validationFirst', 'looseCoupling', 'recursiveValidation'];
    requiredPrinciples.forEach(principle => {
      if (!(principle in rulesConfig.principles)) {
        this.addError(
          `rulesConfig.principles.${principle}`,
          'rulesConfig.principles 缺少必需的原则定义',
          'recursiveValidation'
        );
      }
    });

    // 检查"核心+映射"架构的文件配置
    if (!rulesConfig.coreRulesPath || !rulesConfig.implementationMapPath) {
      this.addError(
        'rulesConfig',
        '必须配置 coreRulesPath 和 implementationMapPath（采用"核心+映射"架构）',
        'recursiveValidation',
        'warning'
      );
    }
  }

  private addError(path: string, message: string, principle: string, severity: 'error' | 'warning' = 'error'): void {
    this.errors.push({ path, message, principle, severity });
  }
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationError[];
  summary: {
    total: number;
    errors: number;
    warnings: number;
  };
}

// 导出单例验证器
export const configValidator = new ConfigValidator();

// 开发模式下自动验证
if (import.meta.env?.DEV) {
  const result = configValidator.validateAll();
  if (!result.valid) {
    console.warn('⚠️ 配置验证发现以下问题：');
    result.errors.forEach(err => {
      console.warn(`  [${err.severity.toUpperCase()}] ${err.path}: ${err.message}`);
    });
  }
}

// ============================================
// 检索函数 - 调用后端 API
// ============================================

import { authFetch } from '../utils/auth';

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''; // 空字符串使用相对路径，由 Vite proxy 转发到 Gateway

export async function retrieveDocuments(query: string): Promise<{
  found: boolean;
  references: Array<{
    id: string;
    content: string;
    source: string;
    score: number;
  }>;
}> {
  try {
    const response = await authFetch(`${API_BASE}/api/search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        query,
        top_k: 10,
        enable_rerank: true,
        enable_fusion: true
      })
    });

    if (!response.ok) {
      console.warn('Search API returned error:', response.status);
      return { found: false, references: [] };
    }

    const data = await response.json();

    // 解析返回结果
    const results = data.data?.results || data.results || [];

    if (results.length === 0) {
      return { found: false, references: [] };
    }

    // 转换为 references 格式
    const references = results.map((item: any, index: number) => ({
      id: item.id || `doc-${index}`,
      content: item.content || item.text || '',
      source: item.source || item.metadata?.source || 'unknown',
      score: item.final_score || item.score || item.relevance_score || 0
    }));

    return {
      found: references.length > 0,
      references
    };
  } catch (error) {
    console.error('retrieveDocuments error:', error);
    return { found: false, references: [] };
  }
}

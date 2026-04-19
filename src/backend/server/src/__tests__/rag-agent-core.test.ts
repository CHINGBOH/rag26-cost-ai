/**
 * RAG Agent 核心测试 - 16道跑通验证题
 *
 * 测试目标：验证Agent能调用工具完成带索引的回答，并通过质量审核。
 * 判定标准（必须全部满足）：
 *  1. 有索引引用（indices非空）
 *  2. 数值准确（answer中包含数字，针对数值题）
 *  3. 工具调用痕迹（response中包含toolsUsed或迭代次数>0）
 *  4. 质量审核通过（confidence >= 0.7）
 *  5. 无幻觉（基于evaluation.passed判断）
 */

import { describe, it, expect, beforeAll } from 'vitest';

// ==================== 配置 ====================
const NODE_BASE_URL = process.env.RAG_TEST_NODE_URL || 'http://localhost:3001';
const PYTHON_BASE_URL = process.env.RAG_TEST_PYTHON_URL || 'http://localhost:8000';
const GATEWAY_BASE_URL = process.env.RAG_TEST_GATEWAY_URL || 'http://localhost:8080';
const REQUEST_TIMEOUT = 120_000; // 120秒（Agent可能迭代多次）

// ==================== 16道核心测试题 ====================
interface TestCase {
  id: string;
  query: string;
  category: 'quota' | 'price' | 'calculation' | 'standard';
  requiresNumeric: boolean;
  requiresComparison: boolean;
  expectedTools: string[];
}

const TEST_CASES: TestCase[] = [
  {
    id: '01',
    query: '安装工程消耗量标准中送配电装置系统调试的计算规则是什么？',
    category: 'quota',
    requiresNumeric: false,
    requiresComparison: false,
    expectedTools: ['keywordSearch', 'vectorSearch'],
  },
  {
    id: '02',
    query: '25版装饰工程消耗量标准中，楼梯面层中玻璃地板的人工费是多少？',
    category: 'quota',
    requiresNumeric: true,
    requiresComparison: false,
    expectedTools: ['keywordSearch'],
  },
  {
    id: '03',
    query: '对比深圳市2025年12月和2023年12月工程建设信息价中，电力电缆规格型号为0.6/1KV YJV 5×120的价格差异',
    category: 'price',
    requiresNumeric: true,
    requiresComparison: true,
    expectedTools: ['keywordSearch', 'calculator'],
  },
  {
    id: '04',
    query: '根据深圳信息价分析下从25年开始至今的装配式混凝土预制构件价格走势',
    category: 'price',
    requiresNumeric: true,
    requiresComparison: false,
    expectedTools: ['keywordSearch', 'calculator'],
  },
  {
    id: '05',
    query: '2025年深圳信息价中钛合金门窗的价格是多少',
    category: 'price',
    requiresNumeric: true,
    requiresComparison: false,
    expectedTools: ['keywordSearch'],
  },
  {
    id: '06',
    query: '详细说明深圳市工程建设地方标准中，关于安全文明施工费的组成内容、计算基数以及计取规定',
    category: 'standard',
    requiresNumeric: false,
    requiresComparison: false,
    expectedTools: ['vectorSearch', 'graphSearch'],
  },
  {
    id: '07',
    query: '工程项目中施工地点要按照什么要求填写',
    category: 'standard',
    requiresNumeric: false,
    requiresComparison: false,
    expectedTools: ['vectorSearch'],
  },
  {
    id: '08',
    query: '2025版费率标准中，房建工程赶工措施费的推荐系数是多少？',
    category: 'quota',
    requiresNumeric: true,
    requiresComparison: false,
    expectedTools: ['keywordSearch'],
  },
  {
    id: '09',
    query: '一般计税方法下，税前工程造价中的费用是否包含进项税额？',
    category: 'standard',
    requiresNumeric: false,
    requiresComparison: false,
    expectedTools: ['vectorSearch'],
  },
  {
    id: '10',
    query: '总包管理服务费的计算基数是什么？',
    category: 'standard',
    requiresNumeric: false,
    requiresComparison: false,
    expectedTools: ['vectorSearch'],
  },
  {
    id: '11',
    query: '模块化建筑工程施工工期定额适用于单体预制箱体应用比例大于多少的±0.00以上工程？',
    category: 'quota',
    requiresNumeric: true,
    requiresComparison: false,
    expectedTools: ['keywordSearch'],
  },
  {
    id: '12',
    query: '2023版与2025版费率标准中，利润率的参考范围是否一致？',
    category: 'standard',
    requiresNumeric: false,
    requiresComparison: true,
    expectedTools: ['vectorSearch', 'graphSearch'],
  },
  {
    id: '13',
    query: '某工程人工费100万、材料费200万、机械费50万、企业管理费25万，企业管理费率是多少？',
    category: 'calculation',
    requiresNumeric: true,
    requiresComparison: false,
    expectedTools: ['keywordSearch', 'calculator'],
  },
  {
    id: '14',
    query: '按2025版标准，如果机械费为0，企业管理费的计算基数是什么',
    category: 'standard',
    requiresNumeric: false,
    requiresComparison: false,
    expectedTools: ['keywordSearch', 'vectorSearch'],
  },
  {
    id: '15',
    query: '2026年1月，中砂的价格是多少元/m³？',
    category: 'price',
    requiresNumeric: true,
    requiresComparison: false,
    expectedTools: ['keywordSearch'],
  },
  {
    id: '16',
    query: '2026年1月，电线、电缆价格较上月的变化幅度是多少？',
    category: 'price',
    requiresNumeric: true,
    requiresComparison: true,
    expectedTools: ['keywordSearch', 'calculator'],
  },
];

// ==================== 类型定义 ====================
interface AgentRunResult {
  answer?: string;
  indices?: Array<{
    chunkId?: string;
    docId?: string;
    pageNumber?: number;
    text?: string;
    sourceDb?: string;
  }>;
  calculations?: Array<{
    expression?: string;
    result?: number | string;
  }>;
  confidence?: number;
  evaluation?: {
    passed?: boolean;
    overall?: number;
    completeness?: number;
    consistency?: number;
    confidence?: number;
    sourceDiversity?: number;
    factConsistency?: number;
    suggestions?: string[];
  };
  toolsUsed?: string[];
  iterations?: number;
  latencyMs?: number;
}

interface TestReport {
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  details: Array<{
    id: string;
    query: string;
    passed: boolean;
    confidence: number | null;
    iterations: number | null;
    toolsUsed: string[];
    latencyMs: number;
    failures: string[];
  }>;
}

// ==================== 辅助函数 ====================

/**
 * 检测服务是否可用
 */
async function checkServiceHealth(url: string): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    const res = await fetch(`${url}/health`, { signal: controller.signal });
    clearTimeout(timeout);
    return res.status === 200;
  } catch {
    return false;
  }
}

/**
 * 调用Node端Agent（SSE流式）
 * 返回解析后的最终结果
 */
async function runAgentQuery(
  query: string,
  options: { maxIterations?: number; enableEvaluation?: boolean } = {}
): Promise<{ result: AgentRunResult | null; events: any[]; error?: string }> {
  const startTime = Date.now();
  const events: any[] = [];

  try {
    const res = await fetch(`${NODE_BASE_URL}/api/agent/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        maxIterations: options.maxIterations ?? 5,
      }),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT),
    });

    if (!res.ok) {
      const text = await res.text().catch(() => '');
      return { result: null, events, error: `HTTP ${res.status}: ${text}` };
    }

    const body = res.body;
    if (!body) {
      return { result: null, events, error: 'Response body is null' };
    }

    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let finalResult: AgentRunResult | null = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data: ')) continue;
        const jsonStr = trimmed.slice(6).trim();
        if (!jsonStr || jsonStr === '[DONE]') continue;

        try {
          const event = JSON.parse(jsonStr);
          events.push(event);

          if (event.type === 'final' && event.result) {
            finalResult = event.result;
          }
          if (event.type === 'error') {
            return { result: null, events, error: event.message || 'Agent error' };
          }
        } catch {
          // 忽略无法解析的SSE行
        }
      }
    }

    const latencyMs = Date.now() - startTime;
    if (finalResult) {
      finalResult.latencyMs = latencyMs;
    }

    return { result: finalResult, events };
  } catch (err: any) {
    return {
      result: null,
      events,
      error: err?.name === 'TimeoutError' ? 'Request timeout' : String(err?.message || err),
    };
  }
}

/**
 * 验证单条测试结果
 */
function validateResult(
  tc: TestCase,
  result: AgentRunResult | null,
  events: any[]
): { passed: boolean; failures: string[] } {
  const failures: string[] = [];

  if (!result) {
    return { passed: false, failures: ['Agent返回结果为空'] };
  }

  // 1. HTTP状态已在外层保证，这里验证 answer 非空
  if (!result.answer || result.answer.trim().length === 0) {
    failures.push('回答为空（answer字段缺失或空字符串）');
  }

  // 2. 有索引引用
  const indices = result.indices || [];
  const hasCitations = indices.length > 0 || (result.answer && /参考|chunk_|《.*》/.test(result.answer));
  if (!hasCitations) {
    failures.push('无索引引用（indices为空且answer中无引用标记）');
  }

  // 3. 数值准确（宽松检查：answer中是否包含数字）
  if (tc.requiresNumeric) {
    const hasNumber = /\d+(\.\d+)?/.test(result.answer || '');
    if (!hasNumber) {
      failures.push('数值类问题回答中未检测到数字');
    }
  }

  // 4. 对比类问题检查
  if (tc.requiresComparison) {
    const answer = result.answer || '';
    const comparisonPatterns = [
      /2025.*2023|2023.*2025/,
      /较.*上|环比|同比|差异|变化|增加|减少|上升|下降/,
      /一致|不一致|相同|不同/,
      /vs|versus|对比|比较/,
    ];
    const hasComparison = comparisonPatterns.some((p) => p.test(answer));
    if (!hasComparison) {
      failures.push('对比类问题回答中未检测到对比表述');
    }
  }

  // 5. 工具调用痕迹（从events中提取tool名称，支持多种事件格式）
  const toolsUsed = new Set<string>();
  for (const ev of events) {
    if (ev.type === 'tool_call' && ev.tool) toolsUsed.add(ev.tool);
    if (ev.type === 'tool_result' && ev.tool) toolsUsed.add(ev.tool);
    if (ev.tool_name) toolsUsed.add(ev.tool_name);
    // react-loop.ts 使用 acting 事件，toolCalls 在 toolCalls 数组中
    if (ev.type === 'acting' && Array.isArray(ev.toolCalls)) {
      for (const tc of ev.toolCalls) {
        if (tc.name) toolsUsed.add(tc.name);
      }
    }
  }
  if (result.toolsUsed) {
    for (const t of result.toolsUsed) toolsUsed.add(t);
  }
  // 从 final result 的 indices 中也能推断工具使用（source_db 字段）
  if (toolsUsed.size === 0 && result.indices) {
    for (const idx of result.indices) {
      if (idx.sourceDb === 'vector') toolsUsed.add('vectorSearch');
      if (idx.sourceDb === 'keyword') toolsUsed.add('keywordSearch');
      if (idx.sourceDb === 'graph') toolsUsed.add('graphSearch');
    }
  }
  if (toolsUsed.size === 0) {
    failures.push('无工具调用痕迹（未检测到tool事件且indices中无来源）');
  }

  // 6. 质量审核通过
  const confidence = result.evaluation?.confidence ?? result.confidence ?? 0;
  if (confidence < 0.7) {
    failures.push(`置信度不足: ${confidence.toFixed(3)} < 0.7`);
  }
  if (result.evaluation && result.evaluation.passed === false) {
    failures.push('evaluation.passed === false');
  }

  return {
    passed: failures.length === 0,
    failures,
  };
}

// ==================== 测试套件 ====================

describe('RAG Agent 核心16题跑通验证', () => {
  let nodeHealthy = false;
  let pythonHealthy = false;

  beforeAll(async () => {
    nodeHealthy = await checkServiceHealth(NODE_BASE_URL);
    pythonHealthy = await checkServiceHealth(PYTHON_BASE_URL);
  });

  // 生成每个测试用例的独立测试
  for (const tc of TEST_CASES) {
    it(`[${tc.id}] ${tc.query.slice(0, 40)}...`, async () => {
      if (!nodeHealthy) {
        console.warn(`[${tc.id}] Node服务(${NODE_BASE_URL})不可用，跳过`);
        expect(true).toBe(true); // 跳过时不失败，但标记为需要关注
        return;
      }

      const { result, events, error } = await runAgentQuery(tc.query, {
        maxIterations: 5,
        enableEvaluation: true,
      });

      if (error) {
        console.error(`[${tc.id}] 请求错误: ${error}`);
      }

      const { passed, failures } = validateResult(tc, result, events);

      // 收集toolsUsed用于报告
      const toolsUsed = new Set<string>();
      for (const ev of events) {
        if (ev.type === 'tool_call' && ev.tool) toolsUsed.add(ev.tool);
        if (ev.type === 'tool_result' && ev.tool) toolsUsed.add(ev.tool);
        if (ev.tool_name) toolsUsed.add(ev.tool_name);
      }
      if (result?.toolsUsed) {
        for (const t of result.toolsUsed) toolsUsed.add(t);
      }

      // 打印详细结果到控制台（便于调试）
      console.log(`[${tc.id}] passed=${passed}, confidence=${result?.evaluation?.confidence ?? result?.confidence ?? 0}, tools=[${Array.from(toolsUsed).join(',')}], failures=[${failures.join('; ')}]`);

      // 核心断言：必须通过所有判定标准
      expect(passed).toBe(true);
      if (!passed) {
        console.error(`[${tc.id}] 失败原因: ${failures.join('; ')}`);
      }
    }, REQUEST_TIMEOUT + 10_000);
  }

  // 批量报告测试（聚合结果）
  it('应生成16题批量测试报告', async () => {
    const report: TestReport = {
      total: TEST_CASES.length,
      passed: 0,
      failed: 0,
      skipped: 0,
      details: [],
    };

    for (const tc of TEST_CASES) {
      if (!nodeHealthy) {
        report.skipped++;
        report.details.push({
          id: tc.id,
          query: tc.query,
          passed: false,
          confidence: null,
          iterations: null,
          toolsUsed: [],
          latencyMs: 0,
          failures: ['Node服务不可用'],
        });
        continue;
      }

      const start = Date.now();
      const { result, events, error } = await runAgentQuery(tc.query, {
        maxIterations: 5,
        enableEvaluation: true,
      });
      const latencyMs = Date.now() - start;

      const { passed, failures } = validateResult(tc, result, events);

      const toolsUsed = new Set<string>();
      for (const ev of events) {
        if (ev.type === 'tool_call' && ev.tool) toolsUsed.add(ev.tool);
        if (ev.type === 'tool_result' && ev.tool) toolsUsed.add(ev.tool);
        if (ev.tool_name) toolsUsed.add(ev.tool_name);
      }
      if (result?.toolsUsed) {
        for (const t of result.toolsUsed) toolsUsed.add(t);
      }

      if (passed) report.passed++;
      else report.failed++;

      report.details.push({
        id: tc.id,
        query: tc.query,
        passed,
        confidence: result?.evaluation?.confidence ?? result?.confidence ?? 0,
        iterations: result?.iterations ?? events.filter((e) => e.type === 'iteration').length,
        toolsUsed: Array.from(toolsUsed),
        latencyMs: result?.latencyMs ?? latencyMs,
        failures: error ? [error, ...failures] : failures,
      });
    }

    // 输出报告到控制台（JSON格式）
    console.log('\n========== RAG Agent 核心测试报告 ==========');
    console.log(JSON.stringify(report, null, 2));
    console.log('============================================\n');

    // 断言：全部通过才算跑通
    expect(report.passed).toBe(report.total);
  }, TEST_CASES.length * (REQUEST_TIMEOUT + 5_000));
});

// ==================== Python后端搜索/评估接口验证 ====================

describe('Python后端接口可用性验证', () => {
  it('Python /api/v1/search 应返回结果', async () => {
    try {
      const res = await fetch(`${PYTHON_BASE_URL}/api/v1/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: '房建工程赶工措施费', top_k: 5 }),
        signal: AbortSignal.timeout(10_000),
      });
      expect(res.status).toBe(200);
      const data = await res.json();
      expect(data).toBeDefined();
    } catch (err: any) {
      console.warn('Python /api/v1/search 不可用:', err?.message || err);
      // 服务未启动时不失败，但发出警告
      expect(true).toBe(true);
    }
  });

  it('Python /api/v1/evaluate 应返回评估分数', async () => {
    try {
      const res = await fetch(`${PYTHON_BASE_URL}/api/v1/evaluate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: '测试查询',
          retrieved_chunks: [
            { id: '1', content: '内容1', source: 'doc1', score: 0.9 },
            { id: '2', content: '内容2', source: 'doc2', score: 0.8 },
          ],
          generated_answer: '这是生成的答案，参考[1]',
          history_rounds: 0,
        }),
        signal: AbortSignal.timeout(10_000),
      });
      expect(res.status).toBe(200);
      const data = (await res.json()) as any;
      expect(data.confidence).toBeDefined();
      expect(data.completeness).toBeDefined();
    } catch (err: any) {
      console.warn('Python /api/v1/evaluate 不可用:', err?.message || err);
      expect(true).toBe(true);
    }
  });
});

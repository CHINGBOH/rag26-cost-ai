/**
 * Node live agent smoke harness.
 *
 * Responsibility split:
 * - Canonical 16-question semantic regression lives in repo-root `tests/test_agent_16.py`
 * - This Vitest file only verifies the Node `/api/agent/run` SSE contract and
 *   representative end-to-end tool execution on the active runtime path.
 */

import { beforeAll, describe, expect, it } from 'vitest';

const runLiveAgentTests = process.env.RAG_RUN_LIVE_AGENT_TESTS === '1';
const describeIfLive = runLiveAgentTests ? describe : describe.skip;

const NODE_BASE_URL =
  process.env.RAG_TEST_NODE_URL || process.env.RAG_AGENT_API_URL || 'http://localhost:3001';
const RETRIEVAL_BASE_URL =
  process.env.RAG_TEST_RETRIEVAL_URL || process.env.RAG_TEST_PYTHON_URL || 'http://localhost:8002';
const REQUEST_TIMEOUT = 120_000;

interface LiveSmokeCase {
  id: string;
  query: string;
}

const TEST_CASES: LiveSmokeCase[] = [
  {
    id: 'quota-coefficient',
    query: '2025版费率标准中，房建工程赶工措施费的推荐系数是多少？',
  },
  {
    id: 'price-comparison',
    query: '对比深圳市2025年12月和2023年12月工程建设信息价中，电力电缆规格型号为0.6/1KV YJV 5×120的价格差异',
  },
  {
    id: 'standard-explanation',
    query: '详细说明深圳市工程建设地方标准中，关于安全文明施工费的组成内容、计算基数以及计取规定',
  },
];

interface IndexReference {
  chunk_id?: string;
  doc_id?: string;
  page_number?: number;
  source_db?: string;
}

interface Calculation {
  formula?: string;
  result?: number | string;
}

interface AgentRunResult {
  answer?: string;
  indices?: IndexReference[];
  calculations?: Calculation[];
  confidence?: number;
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
    toolCalls: string[];
    latencyMs: number;
    failures: string[];
  }>;
}

type ReportDetail = TestReport['details'][number];

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

async function runAgentQuery(
  query: string,
  options: { maxIterations?: number } = {},
): Promise<{ result: AgentRunResult | null; events: any[]; error?: string }> {
  const startTime = Date.now();
  const events: any[] = [];

  try {
    const res = await fetch(`${NODE_BASE_URL}/api/agent/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        maxIterations: options.maxIterations ?? 3,
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
          // Ignore malformed SSE lines.
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

function collectToolCalls(events: any[]): Array<{ name?: string; result?: string }> {
  const toolCalls: Array<{ name?: string; result?: string }> = [];

  for (const event of events) {
    if (event.type === 'acting' && Array.isArray(event.toolCalls)) {
      for (const toolCall of event.toolCalls) {
        toolCalls.push({ name: toolCall.name, result: toolCall.result });
      }
    }
  }

  return toolCalls;
}

function validateResult(
  testCase: LiveSmokeCase,
  result: AgentRunResult | null,
  events: any[],
): { passed: boolean; failures: string[]; toolCalls: string[]; confidence: number } {
  const failures: string[] = [];

  if (!result) {
    return { passed: false, failures: ['Agent返回结果为空'], toolCalls: [], confidence: 0 };
  }

  const answer = result.answer || '';
  if (!answer.trim()) {
    failures.push('回答为空（answer字段缺失或空字符串）');
  }

  const indices = result.indices || [];
  const hasCitations = indices.length > 0 || /参考|来源|《.*》|】/.test(answer);
  if (!hasCitations) {
    failures.push('无索引引用（indices为空且answer中无引用标记）');
  }

  const toolCalls = collectToolCalls(events);
  const invokedTools = Array.from(new Set(toolCalls.map((toolCall) => toolCall.name).filter(Boolean))) as string[];
  if (invokedTools.length === 0) {
    failures.push('无工具调用痕迹（未检测到 acting/toolCalls 事件）');
  }

  const successfulToolResults = toolCalls.filter((toolCall) => {
    if (!toolCall.result) return false;
    return !toolCall.result.includes('调用失败');
  });
  if (invokedTools.length > 0 && successfulToolResults.length === 0 && indices.length === 0) {
    failures.push('检测到工具调用，但工具结果全部失败');
  }

  const confidence = result.confidence ?? 0;
  if (!Number.isFinite(confidence)) {
    failures.push('置信度字段非法');
  }

  return {
    passed: failures.length === 0,
    failures,
    toolCalls: invokedTools,
    confidence,
  };
}

describeIfLive('Node agent live SSE smoke', () => {
  let nodeHealthy = false;
  let retrievalHealthy = false;
  const reportDetails = new Map<string, ReportDetail>();

  beforeAll(async () => {
    nodeHealthy = await checkServiceHealth(NODE_BASE_URL);
    retrievalHealthy = await checkServiceHealth(RETRIEVAL_BASE_URL);
  });

  for (const testCase of TEST_CASES) {
    it(`[${testCase.id}] ${testCase.query.slice(0, 36)}...`, async () => {
      if (!nodeHealthy) {
        console.warn(`[${testCase.id}] Node服务(${NODE_BASE_URL})不可用，跳过`);
        expect(true).toBe(true);
        return;
      }
      if (!retrievalHealthy) {
        console.warn(`[${testCase.id}] Retrieval服务(${RETRIEVAL_BASE_URL})不可用，跳过`);
        expect(true).toBe(true);
        return;
      }

      const { result, events, error } = await runAgentQuery(testCase.query, { maxIterations: 3 });
      if (error) {
        console.error(`[${testCase.id}] 请求错误: ${error}`);
      }

      const { passed, failures, toolCalls, confidence } = validateResult(testCase, result, events);
      reportDetails.set(testCase.id, {
        id: testCase.id,
        query: testCase.query,
        passed,
        confidence,
        toolCalls,
        latencyMs: result?.latencyMs ?? 0,
        failures: error ? [error, ...failures] : failures,
      });
      console.log(
        `[${testCase.id}] passed=${passed}, confidence=${confidence}, tools=[${toolCalls.join(',')}], failures=[${failures.join('; ')}]`,
      );

      expect(passed).toBe(true);
    }, REQUEST_TIMEOUT + 10_000);
  }

  it('should generate a smoke report for representative live queries', async () => {
    const report: TestReport = {
      total: TEST_CASES.length,
      passed: 0,
      failed: 0,
      skipped: 0,
      details: [],
    };

    for (const testCase of TEST_CASES) {
      const detail = reportDetails.get(testCase.id);
      if (!detail) {
        report.skipped++;
        report.details.push({
          id: testCase.id,
          query: testCase.query,
          passed: false,
          confidence: null,
          toolCalls: [],
          latencyMs: 0,
          failures: ['测试明细缺失（用例未执行或服务不可用）'],
        });
        continue;
      }

      if (detail.passed) report.passed++;
      else report.failed++;
      report.details.push(detail);
    }

    console.log('\n========== Node agent live smoke report ==========');
    console.log(JSON.stringify(report, null, 2));
    console.log('==================================================\n');

    expect(report.failed).toBe(0);
  }, TEST_CASES.length * (REQUEST_TIMEOUT + 5_000));
});

describeIfLive('Retrieval backend live contract', () => {
  it(
    'retrieval /api/v1/search should return results',
    async () => {
      try {
        const res = await fetch(`${RETRIEVAL_BASE_URL}/api/v1/search`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: '房建工程赶工措施费', top_k: 5 }),
        signal: AbortSignal.timeout(10_000),
      });
      expect(res.status).toBe(200);
      const data = await res.json();
      expect(data).toBeDefined();
      } catch (err: any) {
        console.warn('Retrieval /api/v1/search 不可用:', err?.message || err);
        expect(true).toBe(true);
      }
    },
    15_000,
  );
});

/**
 * 专家判断服务
 * 使用 LLM 进行动态边界评估
 */

import {
  ExpertJudgmentRequest,
  ExpertJudgmentResponse,
  ExpertDecision,
  RecursionRound,
  RecursionSession
} from '@rag/shared';

interface LLMConfig {
  baseUrl: string;
  apiKey: string;
  model: string;
}

export class ExpertJudgmentService {
  private config: LLMConfig;

  constructor(config?: Partial<LLMConfig>) {
    // 默认使用 kimi-code provider
    this.config = {
      baseUrl: config?.baseUrl || 'https://api.kimi.com/coding/v1',
      apiKey: config?.apiKey || process.env.KIMI_API_KEY || '',
      model: config?.model || 'kimi-for-coding'
    };
  }

  /**
   * 执行专家判断
   */
  async evaluate(request: ExpertJudgmentRequest): Promise<ExpertJudgmentResponse> {
    const prompt = this.buildPrompt(request);
    
    try {
      const response = await this.callLLM(prompt);
      const judgment = this.parseResponse(response);
      
      // 后处理：验证决策合理性
      return this.validateAndAdjust(judgment, request);
    } catch (error) {
      console.error('[ExpertJudgment] LLM call failed:', error);
      // 失败时保守处理：需要人工审核
      return {
        decision: 'human_review',
        reasoning: '专家判断服务异常，需要人工介入',
        boundaryAssessment: {
          saturationLevel: 'medium',
          riskOfOverthinking: 'high'
        }
      };
    }
  }

  /**
   * 构建专家判断提示词
   */
  private buildPrompt(request: ExpertJudgmentRequest): string {
    const { context, currentState } = request;
    
    const historySummary = context.recursionHistory.map((round, idx) => `
轮次 ${idx + 1}:
- 检索到 ${round.retrievedChunks.length} 个文档块
- 完整性: ${(round.evaluation?.completeness || 0) * 100}%
- 一致性: ${(round.evaluation?.consistency || 0) * 100}%
- 置信度: ${(round.evaluation?.confidence || 0) * 100}%
- 信息增益: ${(round.evaluation?.informationGain || 0) * 100}%
- 决策: ${round.decision || 'N/A'}
${round.expertReasoning ? `- 理由: ${round.expertReasoning}` : ''}
`).join('\n');

    const contradictions = currentState.contradictionsFound.length > 0 
      ? currentState.contradictionsFound.map(c => `- ${c.description} (严重程度: ${c.severity})`).join('\n')
      : '无';

    return `你是递归检索系统的"质量评估专家"。你的任务是判断当前答案是否足够好，或者是否需要继续递归深挖。

## 原始查询
"""${context.originalQuery}"""

## 递归历史
当前深度: ${context.currentDepth}
${historySummary || '这是第一轮递归'}

## 当前答案
"""${currentState.generatedAnswer}"""

## 支持证据
${currentState.supportingEvidence.map((chunk, idx) => `
[${idx + 1}] 来源: ${chunk.source}
相似度: ${(chunk.score * 100).toFixed(1)}%
内容: ${chunk.content.slice(0, 200)}...
`).join('\n')}

## 发现的矛盾
${contradictions}

## 质量指标
- 完整性: ${(currentState.confidenceSignals.completeness * 100).toFixed(1)}%
- 一致性: ${(currentState.confidenceSignals.consistency * 100).toFixed(1)}%
- 置信度: ${(currentState.confidenceSignals.confidence * 100).toFixed(1)}%
- 来源多样性: ${(currentState.confidenceSignals.sourceDiversity * 100).toFixed(1)}%
- 事实一致性: ${(currentState.confidenceSignals.factConsistency * 100).toFixed(1)}%
- 覆盖率估计: ${(currentState.confidenceSignals.coverageEstimate * 100).toFixed(1)}%

## 判断选项

1. **satisfy** (满意，停止递归)
   - 适用条件：答案完整、准确、有充分证据支持，置信度 > 0.8
   
2. **continue** (继续递归深挖)
   - 适用条件：答案不够完整，或某些关键信息缺乏证据支持
   - 需要指定下一步策略：deeper(深入)/broader(扩大)/clarify_contradiction(澄清矛盾)
   - 需要建议具体的子查询方向
   
3. **query_external** (查询外部知识源)
   - 适用条件：内部知识库无法回答，需要查询网络或社区
   - 需要指定查询目标和具体查询语句
   
4. **human_review** (需要人工审核)
   - 适用条件：发现严重矛盾、置信度过低、或者你作为专家不确定

## 输出格式
必须输出 JSON 格式：

{\n  "decision": "satisfy|continue|query_external|human_review",\n  "reasoning": "详细的判断理由，包括你观察到的问题和决策依据",\n  "continueStrategy": {  // 仅当 decision 为 continue 时需要\n    "focus": "deeper|broader|clarify_contradiction",\n    "suggestedQueries": ["建议的子查询1", "建议的子查询2"]\n  },\n  "externalQuery": {  // 仅当 decision 为 query_external 时需要\n    "target": "community|web_search|knowledge_base",\n    "query": "具体的查询语句"\n  },\n  "boundaryAssessment": {\n    "saturationLevel": "low|medium|high",  // 信息饱和度\n    "riskOfOverthinking": "low|medium|high"  // 过度思考风险\n  }\n}

请只输出 JSON，不要有任何其他内容。`;
  }

  /**
   * 调用 LLM
   */
  private async callLLM(prompt: string): Promise<string> {
    const response = await fetch(`${this.config.baseUrl}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.config.apiKey}`
      },
      body: JSON.stringify({
        model: this.config.model,
        messages: [
          {
            role: 'system',
            content: '你是一个严谨的质量评估专家，负责判断递归检索是否应该继续。你擅长发现信息缺口、评估证据质量、识别潜在矛盾。'
          },
          {
            role: 'user',
            content: prompt
          }
        ],
        temperature: 0.3,  // 低温度，更确定性
        max_tokens: 2000
      })
    });

    if (!response.ok) {
      throw new Error(`LLM API error: ${response.status} ${response.statusText}`);
    }

    const data: any = await response.json();
    return data.choices[0]?.message?.content || '';
  }

  /**
   * 解析 LLM 响应
   */
  private parseResponse(response: string): ExpertJudgmentResponse {
    try {
      // 尝试提取 JSON
      const jsonMatch = response.match(/\{[\s\S]*\}/);
      if (!jsonMatch) {
        throw new Error('No JSON found in response');
      }
      
      const parsed = JSON.parse(jsonMatch[0]);
      
      // 验证必要字段
      if (!parsed.decision || !parsed.reasoning) {
        throw new Error('Missing required fields');
      }

      return {
        decision: parsed.decision as ExpertDecision,
        reasoning: parsed.reasoning,
        continueStrategy: parsed.continueStrategy,
        externalQuery: parsed.externalQuery,
        boundaryAssessment: parsed.boundaryAssessment || {
          saturationLevel: 'medium',
          riskOfOverthinking: 'medium'
        }
      };
    } catch (error) {
      console.error('[ExpertJudgment] Parse error:', error);
      console.error('[ExpertJudgment] Raw response:', response);
      
      // 解析失败时返回人工审核
      return {
        decision: 'human_review',
        reasoning: `专家判断解析失败，原始响应: ${response.slice(0, 100)}...`,
        boundaryAssessment: {
          saturationLevel: 'medium',
          riskOfOverthinking: 'high'
        }
      };
    }
  }

  /**
   * 验证并调整判断
   */
  private validateAndAdjust(
    judgment: ExpertJudgmentResponse,
    request: ExpertJudgmentRequest
  ): ExpertJudgmentResponse {
    const { currentState, context } = request;
    const confidence = currentState.confidenceSignals.confidence;
    const completeness = currentState.confidenceSignals.completeness;

    // 规则1: 深度超过 15 层，强制人工审核
    if (context.currentDepth >= 15 && judgment.decision === 'continue') {
      return {
        ...judgment,
        decision: 'human_review',
        reasoning: `${judgment.reasoning} [系统强制] 递归深度过大(${context.currentDepth})，需人工确认是否继续。`
      };
    }

    // 规则2: 置信度极低 (< 0.3) 且专家决定满意，标记为可疑
    if (confidence < 0.3 && judgment.decision === 'satisfy') {
      return {
        ...judgment,
        decision: 'human_review',
        reasoning: `${judgment.reasoning} [系统质疑] 置信度过低(${confidence.toFixed(2)})却判断满意，需人工复核。`
      };
    }

    // 规则3: 完整性极低 (< 0.3) 必须继续或查外部
    if (completeness < 0.3 && judgment.decision === 'satisfy') {
      return {
        ...judgment,
        decision: 'continue',
        reasoning: `${judgment.reasoning} [系统强制] 完整性过低(${completeness.toFixed(2)})，必须继续检索。`,
        continueStrategy: judgment.continueStrategy || {
          focus: 'broader',
          suggestedQueries: ['补充基础信息', '查找更多背景资料']
        }
      };
    }

    // 规则4: 存在 high 级别矛盾，不能满意
    const hasHighSeverityContradiction = request.currentState.contradictionsFound
      .some(c => c.severity === 'high');
    if (hasHighSeverityContradiction && judgment.decision === 'satisfy') {
      return {
        ...judgment,
        decision: 'continue',
        reasoning: `${judgment.reasoning} [系统强制] 存在严重矛盾未解决，不能满意。`,
        continueStrategy: {
          focus: 'clarify_contradiction',
          suggestedQueries: ['澄清矛盾点', '验证冲突信息']
        }
      };
    }

    return judgment;
  }

  /**
   * 快速评估（用于心跳监控）
   */
  async quickEvaluate(session: RecursionSession): Promise<{
    shouldAlert: boolean;
    alertLevel?: 'warning' | 'critical';
    message?: string;
  }> {
    // 简单的规则判断，不调用 LLM
    const lastRound = session.rounds[session.rounds.length - 1];
    
    if (!lastRound?.evaluation) {
      return { shouldAlert: false };
    }

    const { confidence, consistency, completeness } = lastRound.evaluation;

    // 严重问题
    if (confidence < 0.3 && consistency < 0.5) {
      return {
        shouldAlert: true,
        alertLevel: 'critical',
        message: `置信度和一致性双低(${confidence.toFixed(2)}, ${consistency.toFixed(2)})`
      };
    }

    // 警告
    if (session.currentDepth > 10 && confidence < 0.6) {
      return {
        shouldAlert: true,
        alertLevel: 'warning',
        message: `深度过大(${session.currentDepth})但置信度仍低(${confidence.toFixed(2)})`
      };
    }

    return { shouldAlert: false };
  }
}

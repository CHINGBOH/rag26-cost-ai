/**
 * 专家模块 - 专家判断与评估
 * 提供管道式决策接口
 */

import {
  ExpertDecision,
  RecursionRound,
  RecursionMetrics,
  BoundaryAssessment,
  RoundEvaluation,
  SubQuery
} from '../../common/types'

export interface ExpertContext {
  query: string
  rounds: RecursionRound[]
  metrics: RecursionMetrics
}

export interface JudgmentConfig {
  confidenceThreshold: number
  maxAnomalies: number
  timeout: number
}

const defaultConfig: JudgmentConfig = {
  confidenceThreshold: 0.85,
  maxAnomalies: 5,
  timeout: 30000
}

/**
 * 专家判断 - 决定是否继续递归
 */
export function expertJudge(config?: Partial<JudgmentConfig>) {
  const cfg = { ...defaultConfig, ...config }

  return function judge(context: ExpertContext): ExpertDecision {
    const { rounds, metrics } = context
    const lastRound = rounds[rounds.length - 1]

    // 首次检索
    if (!lastRound) {
      return {
        shouldContinue: true,
        confidence: 0.5,
        reason: '首次检索，需要更多信息',
        nextAction: 'continue'
      }
    }

    const { evaluation } = lastRound

    // 基于置信度判断
    if (evaluation.confidence >= cfg.confidenceThreshold) {
      return {
        shouldContinue: false,
        confidence: evaluation.confidence,
        reason: '置信度满足阈值要求，可以结束递归',
        nextAction: 'stop'
      }
    }

    // 检查信息增益
    if (evaluation.informationGain < 0.1) {
      return {
        shouldContinue: false,
        confidence: evaluation.confidence,
        reason: '信息增益过低，继续检索效果有限',
        nextAction: 'stop'
      }
    }

    // 异常过多
    if (context.metrics.maxDepthReached > cfg.maxAnomalies) {
      return {
        shouldContinue: false,
        confidence: evaluation.confidence,
        reason: '异常次数过多，需要人工介入',
        nextAction: 'escalate'
      }
    }

    // 继续检索
    return {
      shouldContinue: true,
      confidence: evaluation.confidence,
      reason: '置信度不足，需要继续检索',
      nextAction: 'continue',
      suggestedQueries: generateSuggestedQueries(context)
    }
  }
}

/**
 * 边界评估 - 检查是否超出处理边界
 */
export function assessBoundary(config?: Partial<JudgmentConfig>) {
  const cfg = { ...defaultConfig, ...config }

  return function assess(context: ExpertContext): BoundaryAssessment {
    const { rounds, metrics } = context

    // 检查深度
    if (metrics.maxDepthReached > 5) {
      return {
        withinBoundaries: false,
        boundaryType: 'max_depth',
        suggestedAction: 'stop',
        confidence: 0.9
      }
    }

    // 检查异常
    if (metrics.maxDepthReached > cfg.maxAnomalies) {
      return {
        withinBoundaries: false,
        boundaryType: 'anomaly_count',
        suggestedAction: 'escalate',
        confidence: 0.8
      }
    }

    // 检查置信度
    if (metrics.averageConfidence > 0 && metrics.averageConfidence < 0.3) {
      return {
        withinBoundaries: false,
        boundaryType: 'low_confidence',
        suggestedAction: 'escalate',
        confidence: 0.7
      }
    }

    return {
      withinBoundaries: true,
      suggestedAction: 'continue',
      confidence: 0.9
    }
  }
}

/**
 * 评估检索质量
 */
export function evaluateQuality() {
  return function evaluate(rounds: RecursionRound[]): RoundEvaluation {
    if (rounds.length === 0) {
      return {
        completeness: 0,
        consistency: 0,
        confidence: 0,
        informationGain: 0,
        sourceDiversity: 0,
        factConsistency: 0,
        coverageEstimate: 0
      }
    }

    const lastRound = rounds[rounds.length - 1]
    const allChunks = rounds.flatMap(r => r.retrievedChunks)

    // 计算平均置信度
    const avgConfidence = rounds.reduce((sum, r) => sum + r.evaluation.confidence, 0) / rounds.length

    // 计算一致性
    const confidences = rounds.map(r => r.evaluation.confidence)
    const mean = confidences.reduce((a, b) => a + b, 0) / confidences.length
    const variance = confidences.reduce((sum, c) => sum + Math.pow(c - mean, 2), 0) / confidences.length
    const consistency = Math.max(0, 1 - variance)

    // 来源多样性
    const sources = new Set(allChunks.map(c => c.source))
    const sourceDiversity = Math.min(sources.size / 5, 1)

    // 信息增益
    const informationGain = rounds.length > 1
      ? lastRound.evaluation.confidence - rounds[rounds.length - 2].evaluation.confidence
      : lastRound.evaluation.confidence

    return {
      completeness: lastRound.evaluation.completeness,
      consistency,
      confidence: avgConfidence,
      informationGain: Math.max(0, informationGain),
      sourceDiversity,
      factConsistency: lastRound.evaluation.factConsistency,
      coverageEstimate: lastRound.evaluation.coverageEstimate
    }
  }
}

/**
 * 生成建议查询
 */
function generateSuggestedQueries(context: ExpertContext): string[] {
  const { query, rounds } = context
  const suggestions: string[] = []

  // 基于历史查询生成建议
  if (rounds.length > 0) {
    const lastRound = rounds[rounds.length - 1]
    const topics = extractTopics(lastRound.subQueries.map((sq: SubQuery) => sq.query))

    for (const topic of topics.slice(0, 3)) {
      suggestions.push(`${query} ${topic} 详细说明`)
      suggestions.push(`${topic} 与 ${query} 的关系`)
    }
  }

  return suggestions.slice(0, 5)
}

function extractTopics(queries: string[]): string[] {
  const stopWords = ['的', '是', '什么', '怎么', '如何', '为什么']
  const words = queries
    .flatMap(q => q.split(/[\s,，.。]+/))
    .filter(w => w.length > 1 && !stopWords.includes(w))

  const frequency: Record<string, number> = {}
  for (const word of words) {
    frequency[word] = (frequency[word] || 0) + 1
  }

  return Object.entries(frequency)
    .sort((a, b) => b[1] - a[1])
    .map(([word]) => word)
}

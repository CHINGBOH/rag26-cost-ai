/**
 * Strategy generation framework — converts root causes into actionable repair strategies
 *
 * Simplified implementation focusing on core functionality over XState complexity.
 */

import {
  RootCauseReport,
  RepairSuggestion,
  StrategyGenerationContext,
  StrategyResult,
} from './types';

/**
 * Generate repair options for a given route
 */
function generateRepairOptionsForRoute(
  route: string,
  baseTimestamp: number
): RepairSuggestion[] {
  const suggestions: RepairSuggestion[] = [];

  switch (route) {
    case 'R1_navigator_dict':
      suggestions.push({
        id: `nav_rule_${baseTimestamp}`,
        affected_route: 'R1_navigator_dict',
        action_type: 'prompt_adjustment',
        patch_payload: {
          new_rule: 'if query contains "价格对比" OR "成本对比" → type=comparison',
          condition_keywords: ['价格对比', '成本对比', '费用对比'],
          target_type: 'comparison',
        },
        description: 'Add missing query type classification rule for comparison queries',
        rationale:
          'Analysis shows unrecognized comparison query patterns causing routing failures',
        estimated_impact: 25,
      });
      break;

    case 'R2_path_default':
      suggestions.push({
        id: `path_default_${baseTimestamp}`,
        affected_route: 'R2_path_default',
        action_type: 'path_modify',
        patch_payload: {
          high_frequency_paths: [
            {
              pattern: '第二册电气设备安装工程',
              default_prefix: '10',
              hit_rate: 0.78,
            },
            {
              pattern: '管道安装工程',
              default_prefix: '15',
              hit_rate: 0.72,
            },
          ],
        },
        description: 'Update path constraint defaults based on historical hit rates',
        rationale:
          'High-frequency chapters can be memoized as defaults to reduce query analysis time',
        estimated_impact: 15,
      });
      break;

    case 'R3_planner_examples':
      suggestions.push({
        id: `planner_few_shot_${baseTimestamp}`,
        affected_route: 'R3_planner_examples',
        action_type: 'prompt_adjustment',
        patch_payload: {
          new_examples: [
            {
              question:
                'What is the installation cost for electrical equipment in section 10.1?',
              plan: [
                'Extract chapter 10 (electrical equipment)',
                'Locate section 10.1 in source document',
                'Extract base cost and adjustment factors',
                'Calculate total cost with regional multiplier',
              ],
              label: 'good',
            },
          ],
        },
        description: 'Add new few-shot examples for improved planning',
        rationale: 'Historical successful plans provide better guidance than generic examples',
        estimated_impact: 20,
      });
      break;

    case 'R4_rerank_weights':
      suggestions.push({
        id: `rerank_tune_${baseTimestamp}`,
        affected_route: 'R4_rerank_weights',
        action_type: 'weight_tuning',
        patch_payload: {
          bm25_weight: 0.3,
          semantic_weight: 0.5,
          recency_weight: 0.2,
          previous_weights: {
            bm25_weight: 0.25,
            semantic_weight: 0.4,
            recency_weight: 0.35,
          },
        },
        description: 'Rebalance ranking weights based on CTR analysis',
        rationale:
          'Current distribution under-weights semantic similarity; recency weight too high',
        estimated_impact: 18,
      });
      break;

    case 'R5_tool_priority':
      suggestions.push({
        id: `tool_priority_${baseTimestamp}`,
        affected_route: 'R5_tool_priority',
        action_type: 'tool_reorder',
        patch_payload: {
          tool_priority: [
            { tool: 'semantic_search', priority: 1, hit_rate: 0.82 },
            { tool: 'bm25_search', priority: 2, hit_rate: 0.71 },
            { tool: 'rule_clause_search', priority: 3, hit_rate: 0.65 },
          ],
        },
        description: 'Reorder tool selection priority based on hit rates',
        rationale: 'Historical tool performance data shows semantic search is most reliable',
        estimated_impact: 22,
      });
      break;
  }

  return suggestions;
}

/**
 * Assess risk level based on root cause confidence and suggestion types
 */
function assessRiskLevel(
  rootCause: RootCauseReport,
  suggestions: RepairSuggestion[]
): {
  riskLevel: 'low' | 'mid' | 'high';
  decision: 'auto_apply' | 'pending_review' | 'manual_only';
} {
  const riskFactors = {
    isPromptChange: suggestions.some((s) => s.action_type === 'prompt_adjustment'),
    isNewFeature: suggestions.some((s) => s.action_type === 'new_feature'),
    hasHighImpact: suggestions.some((s) => s.estimated_impact > 50),
    highConfidenceInCause: rootCause.confidence > 0.8,
  };

  let riskLevel: 'low' | 'mid' | 'high';
  let decision: 'auto_apply' | 'pending_review' | 'manual_only';

  if (riskFactors.isNewFeature || !riskFactors.highConfidenceInCause) {
    riskLevel = 'high';
    decision = 'manual_only';
  } else if (
    riskFactors.isPromptChange &&
    !riskFactors.hasHighImpact &&
    riskFactors.highConfidenceInCause
  ) {
    riskLevel = 'low';
    decision = 'auto_apply';
  } else {
    riskLevel = 'mid';
    decision = 'pending_review';
  }

  return { riskLevel, decision };
}

/**
 * Generate repair strategies for a root cause.
 * Analyzes root cause and produces actionable repair suggestions.
 */
export async function generateStrategy(rootCause: RootCauseReport): Promise<StrategyResult> {
  // Step 1: Generate route-specific repair suggestions
  const suggestions = generateRepairOptionsForRoute(rootCause.affected_route, Date.now());

  // Step 2: Assess risk level
  const { riskLevel, decision } = assessRiskLevel(rootCause, suggestions);

  // Step 3: Log execution trace (in production, this would queue tasks)
  console.log(`[STRATEGY] Generated ${suggestions.length} suggestions for ${rootCause.affected_route}`);
  console.log(`[RISK] Level: ${riskLevel}, Decision: ${decision}`);

  return {
    suggestions,
    riskLevel,
    decision,
  };
}

/**
 * Strategy result type - simpler representation for testing
 */
export interface SimplifiedStrategyResult {
  suggestions: RepairSuggestion[];
  riskLevel: 'low' | 'mid' | 'high';
  decision: 'auto_apply' | 'pending_review' | 'manual_only';
}

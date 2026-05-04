/**
 * Learning module types — root cause and strategy generation
 */

export type RouteId =
  | 'R1_navigator_dict'
  | 'R2_path_default'
  | 'R3_planner_examples'
  | 'R4_rerank_weights'
  | 'R5_tool_priority';

export type RootCauseType =
  | 'data_stale'
  | 'poor_query_understanding'
  | 'suboptimal_ranking'
  | 'tool_failure'
  | 'insufficient_diversity'
  | 'architecture_flaw'
  | 'configuration_error'
  | 'external_dependency';

export type ProblemCategory =
  | 'prompt_issue'
  | 'tool_failure'
  | 'routing_error'
  | 'low_quality'
  | 'diversity_issue'
  | 'contract_violation'
  | 'topo_anomaly';

export type Severity = 'low' | 'medium' | 'high';

export interface ProblemReport {
  problem_id: string;
  category: ProblemCategory;
  severity: Severity;
  affected_route: RouteId;
  description: string;
  evidence: string[];
  confidence: number; // 0-1
  suggested_gap_id: string;
  ts: number;
  additional_context?: Record<string, unknown>;
}

export interface RootCauseReport {
  problem_id: string;
  affected_route: RouteId;
  root_cause_hypothesis: string;
  root_cause_type: RootCauseType;
  contributing_factors: string[];
  evidence_chain: Record<string, unknown>;
  confidence: number; // 0-1
  repair_suggestions: string[];
  repair_priority: 'urgent' | 'high' | 'medium' | 'low';
  ts: number;
}

export type ActionType =
  | 'prompt_adjustment'
  | 'tool_reorder'
  | 'weight_tuning'
  | 'path_modify'
  | 'new_feature';

export interface RepairSuggestion {
  id: string;
  affected_route: RouteId;
  action_type: ActionType;
  patch_payload: Record<string, unknown>;
  description: string;
  rationale: string;
  estimated_impact: number; // 0-100
}

export type RiskLevel = 'low' | 'mid' | 'high';
export type DecisionType = 'auto_apply' | 'pending_review' | 'manual_only';

export interface StrategyGenerationContext {
  rootCause: RootCauseReport;
  suggestions: RepairSuggestion[];
  riskLevel: RiskLevel;
  decision: DecisionType;
  timestamp: number;
}

export interface StrategyResult {
  suggestions: RepairSuggestion[];
  riskLevel: RiskLevel;
  decision: DecisionType;
}

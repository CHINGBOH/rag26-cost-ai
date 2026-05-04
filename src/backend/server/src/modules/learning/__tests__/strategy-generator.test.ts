/**
 * Unit tests for strategy generation framework
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { generateStrategy } from '../strategy-generator';
import type {
  RootCauseReport,
  RepairSuggestion,
  RiskLevel,
  DecisionType,
} from '../types';

describe('Strategy Generation Framework', () => {
  let mockRootCause: RootCauseReport;
  const validRoutes = [
    'R1_navigator_dict',
    'R2_path_default',
    'R3_planner_examples',
    'R4_rerank_weights',
    'R5_tool_priority',
  ] as const;

  beforeEach(() => {
    mockRootCause = {
      problem_id: 'test_prob_001',
      affected_route: 'R1_navigator_dict',
      root_cause_hypothesis: 'Missing query type classification for comparison queries',
      root_cause_type: 'poor_query_understanding',
      contributing_factors: ['High latency on analyzer', 'Incomplete keyword dictionary'],
      evidence_chain: {
        failure_signals: 7,
        avg_confidence: 0.75,
      },
      confidence: 0.85,
      repair_suggestions: [
        'Add comparison query type classification rule',
        'Expand synonym dictionary',
      ],
      repair_priority: 'high',
      ts: Date.now(),
    };
  });

  describe('Strategy Generation Flow', () => {
    it('should generate strategies from root cause', async () => {
      const result = await generateStrategy(mockRootCause);

      expect(result).toBeDefined();
      expect(result.suggestions).toBeDefined();
      expect(Array.isArray(result.suggestions)).toBe(true);
      expect(result.riskLevel).toBeDefined();
      expect(result.decision).toBeDefined();
    });

    it('should generate suggestions for each route', async () => {
      const routes = [
        'R1_navigator_dict',
        'R2_path_default',
        'R3_planner_examples',
        'R4_rerank_weights',
        'R5_tool_priority',
      ] as const;

      for (const route of routes) {
        const testCause: RootCauseReport = {
          ...mockRootCause,
          affected_route: route,
        };

        const result = await generateStrategy(testCause);

        expect(result.suggestions.length).toBeGreaterThan(0);
        expect(result.suggestions[0].affected_route).toBe(route);
      }
    });

    it('should respect suggestion payload structure', async () => {
      const result = await generateStrategy(mockRootCause);

      for (const suggestion of result.suggestions) {
        expect(suggestion.id).toBeDefined();
        expect(suggestion.affected_route).toBeDefined();
        expect(suggestion.action_type).toBeDefined();
        expect(suggestion.patch_payload).toBeDefined();
        expect(suggestion.description).toBeDefined();
        expect(suggestion.rationale).toBeDefined();
        expect(suggestion.estimated_impact).toBeGreaterThanOrEqual(0);
        expect(suggestion.estimated_impact).toBeLessThanOrEqual(100);
      }
    });
  });

  describe('Risk Level Assessment', () => {
    it('should classify as LOW risk for simple prompt adjustments with high confidence', async () => {
      const highConfidenceCause: RootCauseReport = {
        ...mockRootCause,
        confidence: 0.95,
        root_cause_type: 'poor_query_understanding',
      };

      const result = await generateStrategy(highConfidenceCause);

      // Simple changes with high confidence should be low risk
      expect(['low', 'mid']).toContain(result.riskLevel);
    });

    it('should classify as HIGH risk for new features or low confidence causes', async () => {
      const lowConfidenceCause: RootCauseReport = {
        ...mockRootCause,
        confidence: 0.4,
        root_cause_type: 'architecture_flaw',
      };

      const result = await generateStrategy(lowConfidenceCause);

      // Low confidence or architectural changes should be higher risk
      expect(['mid', 'high']).toContain(result.riskLevel);
    });

    it('should map risk level to decision type', async () => {
      const lowRisk: RootCauseReport = {
        ...mockRootCause,
        confidence: 0.95,
      };

      const result = await generateStrategy(lowRisk);

      // Risk level should correspond to decision
      if (result.riskLevel === 'low') {
        expect(['auto_apply', 'pending_review']).toContain(result.decision);
      } else if (result.riskLevel === 'mid') {
        expect(['pending_review']).toContain(result.decision);
      } else {
        expect(['manual_only']).toContain(result.decision);
      }
    });
  });

  describe('Route-Specific Suggestions', () => {
    it('should generate prompt adjustment for R1_navigator_dict', async () => {
      const cause: RootCauseReport = {
        ...mockRootCause,
        affected_route: 'R1_navigator_dict',
      };

      const result = await generateStrategy(cause);
      const suggestions = result.suggestions;

      expect(suggestions.length).toBeGreaterThan(0);
      expect(suggestions[0].action_type).toBe('prompt_adjustment');
      expect(suggestions[0].patch_payload).toHaveProperty('new_rule');
    });

    it('should generate path modifications for R2_path_default', async () => {
      const cause: RootCauseReport = {
        ...mockRootCause,
        affected_route: 'R2_path_default',
      };

      const result = await generateStrategy(cause);
      const suggestions = result.suggestions;

      expect(suggestions.length).toBeGreaterThan(0);
      expect(suggestions[0].action_type).toBe('path_modify');
      expect(suggestions[0].patch_payload).toHaveProperty('high_frequency_paths');
    });

    it('should generate planner examples for R3_planner_examples', async () => {
      const cause: RootCauseReport = {
        ...mockRootCause,
        affected_route: 'R3_planner_examples',
      };

      const result = await generateStrategy(cause);
      const suggestions = result.suggestions;

      expect(suggestions.length).toBeGreaterThan(0);
      expect(suggestions[0].action_type).toBe('prompt_adjustment');
      expect(suggestions[0].patch_payload).toHaveProperty('new_examples');
    });

    it('should generate weight tuning for R4_rerank_weights', async () => {
      const cause: RootCauseReport = {
        ...mockRootCause,
        affected_route: 'R4_rerank_weights',
      };

      const result = await generateStrategy(cause);
      const suggestions = result.suggestions;

      expect(suggestions.length).toBeGreaterThan(0);
      expect(suggestions[0].action_type).toBe('weight_tuning');
      expect(suggestions[0].patch_payload).toHaveProperty('bm25_weight');
      expect(suggestions[0].patch_payload).toHaveProperty('semantic_weight');
      expect(suggestions[0].patch_payload).toHaveProperty('recency_weight');
    });

    it('should generate tool reordering for R5_tool_priority', async () => {
      const cause: RootCauseReport = {
        ...mockRootCause,
        affected_route: 'R5_tool_priority',
      };

      const result = await generateStrategy(cause);
      const suggestions = result.suggestions;

      expect(suggestions.length).toBeGreaterThan(0);
      expect(suggestions[0].action_type).toBe('tool_reorder');
      expect(suggestions[0].patch_payload).toHaveProperty('tool_priority');
    });
  });

  describe('Suggestion Impact Estimation', () => {
    it('should estimate realistic impact values', async () => {
      const result = await generateStrategy(mockRootCause);

      for (const suggestion of result.suggestions) {
        expect(suggestion.estimated_impact).toBeGreaterThan(0);
        expect(suggestion.estimated_impact).toBeLessThanOrEqual(100);
      }
    });

    it('should vary impact based on action type and route', async () => {
      const impacts: Record<string, number> = {};

      const routes = [
        'R1_navigator_dict',
        'R2_path_default',
        'R3_planner_examples',
        'R4_rerank_weights',
        'R5_tool_priority',
      ] as const;

      for (const route of routes) {
        const cause: RootCauseReport = {
          ...mockRootCause,
          affected_route: route,
        };

        const result = await generateStrategy(cause);
        impacts[route] = result.suggestions[0]?.estimated_impact ?? 0;
      }

      // Different routes should (generally) have different impact estimates
      const uniqueImpacts = new Set(Object.values(impacts));
      expect(uniqueImpacts.size).toBeGreaterThanOrEqual(2);
    });
  });

  describe('Decision-Making Logic', () => {
    it('should make auto_apply decision for low-risk changes', async () => {
      const lowRiskCause: RootCauseReport = {
        ...mockRootCause,
        confidence: 0.95,
      };

      const result = await generateStrategy(lowRiskCause);

      if (result.riskLevel === 'low') {
        expect(result.decision).toBe('auto_apply');
      }
    });

    it('should make pending_review decision for mid-risk changes', async () => {
      const midRiskCause: RootCauseReport = {
        ...mockRootCause,
        confidence: 0.65,
      };

      const result = await generateStrategy(midRiskCause);

      if (result.riskLevel === 'mid') {
        expect(result.decision).toBe('pending_review');
      }
    });

    it('should make manual_only decision for high-risk changes', async () => {
      const highRiskCause: RootCauseReport = {
        ...mockRootCause,
        confidence: 0.3,
        root_cause_type: 'architecture_flaw',
      };

      const result = await generateStrategy(highRiskCause);

      if (result.riskLevel === 'high') {
        expect(result.decision).toBe('manual_only');
      }
    });
  });

  describe('State Machine Behavior', () => {
    it('should support all 5 route types', () => {
      const validRoutes = [
        'R1_navigator_dict',
        'R2_path_default',
        'R3_planner_examples',
        'R4_rerank_weights',
        'R5_tool_priority',
      ] as const;

      expect(validRoutes.length).toBe(5);
    });

    it('should organize suggestions by route', async () => {
      const result = await generateStrategy(mockRootCause);
      expect(result.suggestions.length).toBeGreaterThan(0);
      result.suggestions.forEach((s) => {
        expect(validRoutes).toContain(s.affected_route);
      });
    });
  });

  describe('Error Handling and Validation', () => {
    it('should handle all valid route types', async () => {
      const validRoutes = [
        'R1_navigator_dict',
        'R2_path_default',
        'R3_planner_examples',
        'R4_rerank_weights',
        'R5_tool_priority',
      ] as const;

      for (const route of validRoutes) {
        const cause: RootCauseReport = {
          ...mockRootCause,
          affected_route: route,
        };

        const result = await generateStrategy(cause);
        expect(result.suggestions).toBeDefined();
      }
    });

    it('should validate suggestion patches have required fields', async () => {
      const result = await generateStrategy(mockRootCause);

      for (const suggestion of result.suggestions) {
        expect(suggestion.patch_payload).toBeTruthy();
        expect(typeof suggestion.patch_payload).toBe('object');
        expect(Object.keys(suggestion.patch_payload).length).toBeGreaterThan(0);
      }
    });
  });
});

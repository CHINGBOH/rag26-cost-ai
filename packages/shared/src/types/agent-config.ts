/**
 * Agent Configuration Schema - Shared between Frontend and Backend
 * 
 * Issue #125: Unified schema to prevent frontend-backend contract mismatch
 */

import { z } from 'zod';

/**
 * Agent Configuration Schema
 * 
 * This schema defines the contract for agent runtime configuration
 * that is sent from frontend to backend. Both sides must validate
 * against this schema to ensure type safety.
 */
export const AgentConfigSchema = z.object({
  // Search configuration
  searchMode: z.string().default('hybrid'),
  scoreThreshold: z.number().min(0).max(1).default(0.6),
  topK: z.number().int().positive().default(8),
  docTypes: z.array(z.string()).default([]),
  
  // Agent execution
  maxIterations: z.number().int().positive().max(10).default(3),
  
  // LLM configuration
  llmRoute: z.enum(['auto', 'local', 'deepseek']).default('deepseek'),
  llmProvider: z.string().optional(),  // Issue #125 fix: added missing field
  llmModel: z.string().optional(),
  llmEngine: z.string().optional(),
});

export type AgentConfig = z.infer<typeof AgentConfigSchema>;

/**
 * Resolve LLM provider from route if not explicitly provided
 * 
 * This function provides backward compatibility and sensible defaults
 * when frontend doesn't send llmProvider explicitly.
 */
export function resolveLLMProvider(config: AgentConfig): string {
  if (config.llmProvider) {
    return config.llmProvider;
  }
  
  // Fallback: infer provider from route
  const providerMap: Record<AgentConfig['llmRoute'], string> = {
    'deepseek': 'deepseek',
    'local': 'ollama',
    'auto': 'deepseek',
  };
  
  return providerMap[config.llmRoute];
}

/**
 * Default configuration values
 */
export const DEFAULT_AGENT_CONFIG: AgentConfig = {
  searchMode: 'hybrid',
  maxIterations: 3,
  scoreThreshold: 0.6,
  topK: 8,
  docTypes: [],
  llmRoute: 'deepseek',
  llmProvider: undefined,
  llmModel: 'deepseek-chat',
  llmEngine: 'api',
};

import { z } from 'zod'
import { RetrievedChunkSchema } from '../../common/types/src'

export const IndexReferenceSchema = z.object({
  chunk_id: z.string(),
  doc_id: z.string(),
  page_number: z.number().optional(),
  source_db: z.enum(['vector', 'keyword', 'graph', 'knowledge'])
})
export type IndexReference = z.infer<typeof IndexReferenceSchema>

export const CalculationSchema = z.object({
  formula: z.string(),
  steps: z.array(z.string()),
  result: z.union([z.number(), z.string()])
})
export type Calculation = z.infer<typeof CalculationSchema>

export const StructuredOutputSchema = z.object({
  answer: z.string(),
  indices: z.array(IndexReferenceSchema),
  calculations: z.array(CalculationSchema),
  confidence: z.number().min(0).max(1)
})
export type StructuredOutput = z.infer<typeof StructuredOutputSchema>

export const AgentOptionsSchema = z.object({
  maxIterations: z.number().min(1).max(20).default(5),
  confidenceThreshold: z.number().min(0).max(1).default(0.85)
})
export type AgentOptions = z.infer<typeof AgentOptionsSchema>

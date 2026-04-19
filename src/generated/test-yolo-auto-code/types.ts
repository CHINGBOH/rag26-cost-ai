// @ts-nocheck
export interface TestYoloAutoCodeConfig { enabled: boolean; timeout: number; }
export interface TestYoloAutoCodeResult { success: boolean; data: unknown; errors?: string[]; }
export type TestYoloAutoCodeStatus = 'idle' | 'running' | 'completed' | 'failed';
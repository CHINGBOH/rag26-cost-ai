/**
 * 管道模块 - 工作流编排引擎
 * 提供管道式数据处理流程
 */

import { PipelineJob, PipelineStep, PipelineConfig, PipelineStatus } from '../../common/types'
import { EventBus } from '../../common/event-bus'

export interface PipelineResult {
  job: PipelineJob
  success: boolean
  output?: any
  error?: string
}

export interface StepHandler {
  (input: any): Promise<any>
}

const defaultConfig: Partial<PipelineConfig> = {
  concurrency: 1,
  retryCount: 3,
  timeout: 30000
}

/**
 * 创建管道构建器
 */
export function createPipeline(name: string, config?: Partial<PipelineConfig>) {
  const steps: PipelineStep[] = []
  const cfg = { ...defaultConfig, ...config }

  const builder = {
    /**
     * 添加步骤
     */
    add(stepName: string, handler: StepHandler) {
      steps.push({
        id: `step_${name}_${steps.length}`,
        name: stepName,
        status: 'pending',
        handler
      })
      return builder
    },

    /**
     * 定义步骤
     */
    define(name: string, handler: StepHandler) {
      return { id: `step_${name}`, name, status: 'pending' as PipelineStatus, handler }
    },

    /**
     * 执行管道
     */
    async execute(input: any, eventBus?: EventBus): Promise<PipelineResult> {
      const job: PipelineJob = {
        id: `job_${Date.now()}`,
        name,
        status: 'running',
        steps: [...steps],
        currentStep: 0,
        data: input,
        createdAt: Date.now(),
        updatedAt: Date.now()
      }

      eventBus?.emit('pipeline:start', { job })

      try {
        for (let i = 0; i < steps.length; i++) {
          const step = steps[i]
          job.currentStep = i
          step.status = 'running'
          step.startedAt = Date.now()

          eventBus?.emit('pipeline:step:start', { job, step })

          try {
            step.input = i === 0 ? input : steps[i - 1].output
            step.output = await executeWithTimeout(
              () => step.handler!(step.input),
              cfg.timeout!
            )
            step.status = 'completed'
            step.completedAt = Date.now()

            cfg.onStepComplete?.(step, job)
            eventBus?.emit('pipeline:step:complete', { job, step })
          } catch (error) {
            step.status = 'failed'
            step.error = String(error)

            cfg.onStepError?.(step, error as Error, job)
            eventBus?.emit('pipeline:step:error', { job, step, error })

            throw error
          }
        }

        job.status = 'completed'
        job.updatedAt = Date.now()
        job.result = steps[steps.length - 1]?.output

        eventBus?.emit('pipeline:complete', { job })

        return { job, success: true, output: job.result }
      } catch (error) {
        job.status = 'failed'
        job.error = String(error)
        job.updatedAt = Date.now()

        eventBus?.emit('pipeline:error', { job, error })

        return { job, success: false, error: String(error) }
      }
    },

    /**
     * 获取步骤列表
     */
    getSteps() {
      return [...steps]
    }
  }

  return builder
}

/**
 * 创建任务
 */
export function createJob(data: any): PipelineJob {
  return {
    id: `job_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
    name: 'anonymous',
    status: 'pending',
    steps: [],
    currentStep: 0,
    data,
    createdAt: Date.now(),
    updatedAt: Date.now()
  }
}

/**
 * 并行执行多个任务
 */
export function parallel<T>(jobs: Array<() => Promise<T>>, concurrency: number = 5): Promise<T[]> {
  return Promise.all(jobs.map(job => job()))
}

/**
 * 串行执行多个任务
 */
export function serial<T>(jobs: Array<() => Promise<T>>): Promise<T[]> {
  const results: T[] = []

  return jobs.reduce((promise, job) => {
    return promise.then(async () => {
      const result = await job()
      results.push(result)
      return results
    })
  }, Promise.resolve(results))
}

async function executeWithTimeout<T>(fn: () => Promise<T>, timeout: number): Promise<T> {
  return Promise.race([
    fn(),
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error(`Timeout after ${timeout}ms`)), timeout)
    )
  ])
}

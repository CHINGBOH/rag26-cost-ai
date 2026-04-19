/**
 * 监控模块测试
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  initMetrics,
  collectMetrics,
  recordLatency,
  counter,
  gauge,
  createAlert,
  getMetrics,
  getStats,
  healthCheck,
  getMetricNames,
  createMetricsPipeline
} from '../src'

describe('Metrics 模块', () => {
  beforeEach(() => {
    // 初始化干净的指标状态
    initMetrics()
  })

  describe('指标收集', () => {
    it('应该收集指标', () => {
      const collect = collectMetrics('query_latency')
      collect(150)
      collect(200)
      collect(100)
      
      const metrics = getMetrics('query_latency')
      expect(metrics).toHaveLength(3)
      expect(metrics[0].value).toBe(150)
    })

    it('应该获取统计信息', () => {
      const collect = collectMetrics('requests')
      collect(10)
      collect(20)
      collect(30)
      
      const stats = getStats('requests')
      
      expect(stats.count).toBe(3)
      expect(stats.min).toBe(10)
      expect(stats.max).toBe(30)
      expect(stats.avg).toBe(20)
      expect(stats.last).toBe(30)
    })

    it('应该使用计数器', () => {
      const increment = counter('requests_total')
      
      increment()
      increment()
      increment()
      
      const stats = getStats('requests_total')
      expect(stats.count).toBe(3)
      expect(stats.last).toBe(3)
    })

    it('应该使用计数器增加指定值', () => {
      const increment = counter('errors')
      
      increment(5)
      increment(3)
      
      const stats = getStats('errors')
      expect(stats.last).toBe(8)
    })

    it('应该设置仪表盘值', () => {
      const set = gauge('cpu_usage')
      
      set(75.5)
      set(80.0)
      
      const stats = getStats('cpu_usage')
      expect(stats.count).toBe(2)
      expect(stats.last).toBe(80.0)
    })

    it('应该获取所有指标名称', () => {
      collectMetrics('metric1')(100)
      collectMetrics('metric2')(200)
      
      const names = getMetricNames()
      expect(names).toContain('metric1')
      expect(names).toContain('metric2')
    })
  })

  describe('延迟记录', () => {
    it('应该记录函数延迟', async () => {
      const measure = recordLatency('db_query')
      
      const result = await measure(async () => {
        await new Promise(resolve => setTimeout(resolve, 10))
        return 'success'
      })
      
      expect(result).toBe('success')
      
      const stats = getStats('db_query')
      expect(stats.count).toBe(1)
      expect(stats.last).toBeGreaterThan(0)
    })

    it('应该在错误时记录延迟', async () => {
      const measure = recordLatency('api_call')
      
      await expect(measure(async () => {
        await new Promise(resolve => setTimeout(resolve, 5))
        throw new Error('API Error')
      })).rejects.toThrow('API Error')
      
      const stats = getStats('api_call')
      expect(stats.count).toBe(1)
    })
  })

  describe('告警管理', () => {
    it('应该在满足条件时创建告警', () => {
      const check = createAlert({
        name: 'high_cpu',
        condition: (value) => value > 80,
        level: 'warning',
        category: 'performance'
      })
      
      const alert = check(85)
      
      expect(alert).not.toBeNull()
      expect(alert?.level).toBe('warning')
      expect(alert?.category).toBe('performance')
    })

    it('不应该在不满足条件时创建告警', () => {
      const check = createAlert({
        name: 'high_cpu',
        condition: (value) => value > 80,
        level: 'warning',
        category: 'performance'
      })
      
      const alert = check(70)
      
      expect(alert).toBeNull()
    })
  })

  describe('健康检查', () => {
    it('应该返回健康状态', async () => {
      const check = healthCheck('database')
      
      const status = await check(async () => true)
      
      expect(status.service).toBe('database')
      expect(status.status).toBe('healthy')
      expect(status.latency).toBeGreaterThanOrEqual(0)
      expect(status.timestamp).toBeGreaterThan(0)
    })

    it('应该检测不健康服务', async () => {
      const check = healthCheck('api')
      
      const status = await check(async () => false)
      
      expect(status.service).toBe('api')
      expect(status.status).toBe('unhealthy')
    })

    it('应该处理健康检查错误', async () => {
      const check = healthCheck('cache')
      
      const status = await check(async () => {
        throw new Error('Connection failed')
      })
      
      expect(status.service).toBe('cache')
      expect(status.status).toBe('unhealthy')
    })
  })

  describe('管道工厂', () => {
    it('应该创建监控管道', () => {
      const pipeline = createMetricsPipeline()
      
      expect(pipeline.collect).toBeDefined()
      expect(pipeline.recordLatency).toBeDefined()
      expect(pipeline.counter).toBeDefined()
      expect(pipeline.gauge).toBeDefined()
      expect(pipeline.createAlert).toBeDefined()
      expect(pipeline.getMetrics).toBeDefined()
      expect(pipeline.healthCheck).toBeDefined()
    })

    it('应该通过管道收集指标', () => {
      const pipeline = createMetricsPipeline()
      
      pipeline.counter('test.counter')(1)
      pipeline.gauge('test.gauge')(100)
      
      const stats = pipeline.getStats('test.gauge')
      expect(stats.last).toBe(100)
    })
  })
})

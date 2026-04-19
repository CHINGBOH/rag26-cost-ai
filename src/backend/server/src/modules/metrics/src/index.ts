/**
 * 监控模块 - 指标收集与告警
 * 提供管道式监控接口
 */

import { MetricData, Alert, HealthStatus } from '../../common/types'
import { EventBus } from '../../common/event-bus'

export interface MetricsConfig {
  interval: number
  retention: number
  onAlert?: (alert: Alert) => void
}

const defaultConfig: MetricsConfig = {
  interval: 60000, // 1分钟
  retention: 24 * 60 * 60 * 1000 // 24小时
}

// 指标存储
const metricsStore: Map<string, MetricData[]> = new Map()
const alerts: Alert[] = []
let eventBus: EventBus | null = null

/**
 * 初始化监控
 */
export function initMetrics(config?: Partial<MetricsConfig> & { eventBus?: EventBus }) {
  const cfg = { ...defaultConfig, ...config }
  eventBus = config?.eventBus || null

  // 定期清理过期指标
  setInterval(() => {
    cleanup(cfg.retention)
  }, cfg.interval)

  return cfg
}

/**
 * 收集指标
 */
export function collectMetrics(name: string, labels?: Record<string, string>) {
  return function collect(value: number): MetricData {
    const metric: MetricData = {
      name,
      value,
      timestamp: Date.now(),
      labels
    }

    if (!metricsStore.has(name)) {
      metricsStore.set(name, [])
    }
    metricsStore.get(name)!.push(metric)

    eventBus?.emit('metrics:collect', { metric })

    return metric
  }
}

/**
 * 记录延迟
 */
export function recordLatency(name: string, labels?: Record<string, string>) {
  return async function measure<T>(fn: () => Promise<T>): Promise<T> {
    const start = Date.now()
    try {
      const result = await fn()
      const duration = Date.now() - start
      collectMetrics(name, labels)(duration)
      return result
    } catch (error) {
      const duration = Date.now() - start
      collectMetrics(name, { ...labels, error: 'true' })(duration)
      throw error
    }
  }
}

/**
 * 创建计数器
 */
export function counter(name: string, labels?: Record<string, string>) {
  let count = 0

  return function increment(value: number = 1): number {
    count += value
    collectMetrics(name, labels)(count)
    return count
  }
}

/**
 * 创建Gauge
 */
export function gauge(name: string, labels?: Record<string, string>) {
  return function set(value: number): number {
    collectMetrics(name, labels)(value)
    return value
  }
}

/**
 * 创建告警
 */
export function createAlert(config: {
  name: string
  condition: (value: number) => boolean
  level: Alert['level']
  category: string
}) {
  return function check(value: number): Alert | null {
    if (!config.condition(value)) {
      return null
    }

    const alert: Alert = {
      id: `alert_${Date.now()}`,
      level: config.level,
      category: config.category,
      message: `${config.name}: ${value}`,
      timestamp: Date.now()
    }

    alerts.push(alert)
    eventBus?.emit('metrics:alert', { alert })

    return alert
  }
}

/**
 * 获取指标
 */
export function getMetrics(name: string, since?: number): MetricData[] {
  const data = metricsStore.get(name) || []
  if (!since) return data
  return data.filter(m => m.timestamp >= since)
}

/**
 * 获取所有指标名称
 */
export function getMetricNames(): string[] {
  return Array.from(metricsStore.keys())
}

/**
 * 获取统计信息
 */
export function getStats(name: string): {
  count: number
  min: number
  max: number
  avg: number
  last: number
} {
  const data = metricsStore.get(name) || []

  if (data.length === 0) {
    return { count: 0, min: 0, max: 0, avg: 0, last: 0 }
  }

  const values = data.map(m => m.value)
  const sum = values.reduce((a, b) => a + b, 0)

  return {
    count: data.length,
    min: Math.min(...values),
    max: Math.max(...values),
    avg: sum / data.length,
    last: values[values.length - 1]
  }
}

/**
 * 健康检查
 */
export function healthCheck(service: string) {
  return function check(checkFn: () => Promise<boolean>): Promise<HealthStatus> {
    const start = Date.now()

    return checkFn().then((healthy): HealthStatus => ({
      service,
      status: healthy ? 'healthy' : 'unhealthy',
      latency: Date.now() - start,
      timestamp: Date.now()
    })).catch((): HealthStatus => ({
      service,
      status: 'unhealthy',
      latency: Date.now() - start,
      timestamp: Date.now()
    }))
  }
}

/**
 * 清理过期指标
 */
function cleanup(retention: number): void {
  const cutoff = Date.now() - retention

  for (const [name, data] of metricsStore) {
    const filtered = data.filter(m => m.timestamp > cutoff)
    if (filtered.length === 0) {
      metricsStore.delete(name)
    } else {
      metricsStore.set(name, filtered)
    }
  }
}

/**
 * 获取所有告警
 */
export function getAlerts(resolved?: boolean): Alert[] {
  if (resolved === undefined) return [...alerts]
  return alerts.filter(a => a.resolved === resolved)
}

/**
 * 解决告警
 */
export function resolveAlert(alertId: string): boolean {
  const alert = alerts.find(a => a.id === alertId)
  if (!alert) return false

  alert.resolved = true
  alert.resolvedAt = Date.now()
  return true
}

/**
 * 创建监控管道
 */
export function createMetricsPipeline(config?: Partial<MetricsConfig> & { eventBus?: EventBus }) {
  initMetrics(config)

  return {
    collect: collectMetrics,
    recordLatency,
    counter,
    gauge,
    createAlert,
    getMetrics,
    getStats,
    healthCheck,
    getAlerts,
    resolveAlert
  }
}

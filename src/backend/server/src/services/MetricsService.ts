/**
 * 监控服务
 * Prometheus指标收集
 */

import { EventEmitter } from 'events';

interface MetricValue {
  value: number;
  timestamp: number;
  labels?: Record<string, string>;
}

type MetricType = 'counter' | 'gauge' | 'histogram';

interface MetricDefinition {
  name: string;
  help: string;
  type: MetricType;
  values: MetricValue[];
}

export class MetricsService {
  private metrics: Map<string, MetricDefinition> = new Map();
  private eventEmitter: EventEmitter;

  constructor(eventEmitter: EventEmitter) {
    this.eventEmitter = eventEmitter;
    this.initializeMetrics();
  }

  /**
   * 初始化默认指标
   */
  private initializeMetrics() {
    // 计数器
    this.registerMetric('rag_sessions_total', '总会话数', 'counter');
    this.registerMetric('rag_retrievals_total', '总检索次数', 'counter');
    this.registerMetric('rag_generations_total', '总生成次数', 'counter');
    
    // 仪表盘
    this.registerMetric('rag_active_sessions', '活跃会话数', 'gauge');
    this.registerMetric('rag_avg_confidence', '平均置信度', 'gauge');
    this.registerMetric('rag_queue_depth', '队列深度', 'gauge');
    
    // 直方图
    this.registerMetric('rag_retrieval_duration_ms', '检索耗时', 'histogram');
    this.registerMetric('rag_generation_duration_ms', '生成耗时', 'histogram');
  }

  /**
   * 注册指标
   */
  registerMetric(name: string, help: string, type: MetricType): void {
    this.metrics.set(name, {
      name,
      help,
      type,
      values: []
    });
  }

  /**
   * 增加计数器
   */
  incCounter(name: string, labels?: Record<string, string>, value: number = 1): void {
    const metric = this.metrics.get(name);
    if (!metric || metric.type !== 'counter') {
      console.warn(`[Metrics] 计数器不存在: ${name}`);
      return;
    }

    metric.values.push({
      value,
      timestamp: Date.now(),
      labels
    });

    // 只保留最近1000个值
    if (metric.values.length > 1000) {
      metric.values.shift();
    }
  }

  /**
   * 设置仪表盘值
   */
  setGauge(name: string, value: number, labels?: Record<string, string>): void {
    const metric = this.metrics.get(name);
    if (!metric || metric.type !== 'gauge') {
      console.warn(`[Metrics] 仪表盘不存在: ${name}`);
      return;
    }

    // 仪表盘只保留最新值
    metric.values = [{
      value,
      timestamp: Date.now(),
      labels
    }];
  }

  /**
   * 记录直方图
   */
  observeHistogram(name: string, value: number, labels?: Record<string, string>): void {
    const metric = this.metrics.get(name);
    if (!metric || metric.type !== 'histogram') {
      console.warn(`[Metrics] 直方图不存在: ${name}`);
      return;
    }

    metric.values.push({
      value,
      timestamp: Date.now(),
      labels
    });

    // 只保留最近1000个值
    if (metric.values.length > 1000) {
      metric.values.shift();
    }
  }

  /**
   * 生成Prometheus格式输出
   */
  generatePrometheusFormat(): string {
    const lines: string[] = [];

    for (const metric of this.metrics.values()) {
      lines.push(`# HELP ${metric.name} ${metric.help}`);
      lines.push(`# TYPE ${metric.name} ${metric.type}`);

      for (const value of metric.values) {
        const labelStr = value.labels 
          ? '{' + Object.entries(value.labels).map(([k, v]) => `${k}="${v}"`).join(',') + '}'
          : '';
        lines.push(`${metric.name}${labelStr} ${value.value}`);
      }

      lines.push('');
    }

    return lines.join('\n');
  }

  /**
   * 获取指标统计
   */
  getMetricStats(name: string): {
    count: number;
    sum: number;
    avg: number;
    min: number;
    max: number;
  } | null {
    const metric = this.metrics.get(name);
    if (!metric || metric.values.length === 0) return null;

    const values = metric.values.map(v => v.value);
    const sum = values.reduce((a, b) => a + b, 0);
    
    return {
      count: values.length,
      sum,
      avg: sum / values.length,
      min: Math.min(...values),
      max: Math.max(...values)
    };
  }

  /**
   * 获取所有指标
   */
  getAllMetrics(): Record<string, any> {
    const result: Record<string, any> = {};
    
    for (const [name, metric] of this.metrics) {
      result[name] = {
        ...metric,
        stats: this.getMetricStats(name)
      };
    }

    return result;
  }

  // ==================== 便捷方法 ====================

  recordSessionStarted(): void {
    this.incCounter('rag_sessions_total');
  }

  recordRetrieval(durationMs: number): void {
    this.incCounter('rag_retrievals_total');
    this.observeHistogram('rag_retrieval_duration_ms', durationMs);
  }

  recordGeneration(durationMs: number): void {
    this.incCounter('rag_generations_total');
    this.observeHistogram('rag_generation_duration_ms', durationMs);
  }

  updateActiveSessions(count: number): void {
    this.setGauge('rag_active_sessions', count);
  }

  updateAvgConfidence(confidence: number): void {
    this.setGauge('rag_avg_confidence', confidence);
  }
}

# RAG Dashboard 监控系统部署指南

**日期**: 2026-05-08  
**组件**: Prometheus + Grafana  
**状态**: ✅ 就绪

---

## 📋 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Grafana Dashboard                       │
│  (可视化面板: 队列状态、触发分布、性能指标)                │
└─────────────────────┬───────────────────────────────────────┘
                      │ PromQL Queries
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                   Prometheus Server                         │
│  (时序数据库: 采集、存储、查询 metrics)                    │
└─────────────────────┬───────────────────────────────────────┘
                      │ HTTP GET /metrics
                      ▼
┌─────────────────────────────────────────────────────────────┐
│          Retrieval Service (port 8002)                      │
│  /metrics endpoint → prometheus_client export               │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### Step 1: 安装 prometheus_client

```bash
cd src/backend/retrieval-service
pip install prometheus_client
```

### Step 2: 集成到 main.py

在 `main.py` 中添加 metrics 端点：

```python
from prometheus_client import make_asgi_app

# 在 FastAPI app 创建后
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
```

### Step 3: 启动 Prometheus

```bash
# 使用 Docker
docker run -d --name prometheus \
  -p 9090:9090 \
  -v $(pwd)/infrastructure/monitoring/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus
```

### Step 4: 启动 Grafana

```bash
# 使用 Docker
docker run -d --name grafana \
  -p 3100:3000 \
  grafana/grafana
```

### Step 5: 导入 Dashboard

1. 访问 http://localhost:3100
2. 默认登录: `admin / admin`
3. 添加 Prometheus 数据源: http://localhost:9090
4. 导入 dashboard JSON: `infrastructure/monitoring/grafana-dashboard-learning-system.json`

---

## 📊 关键指标说明

### 1. 队列指标

| Metric | 描述 | 类型 | Labels |
|--------|------|------|--------|
| `retest_queue_size` | 队列中任务数量 | Gauge | status (pending/running/success/failed) |
| `retest_queue_age_seconds` | 最老待处理任务年龄 | Histogram | - |
| `retest_deduplication_rate` | 去重率 (0-1) | Gauge | window (1h/24h/7d) |

**PromQL 示例**:
```promql
# 待处理任务数
retest_queue_size{status="pending"}

# 队列总大小
sum(retest_queue_size)

# 去重效率 (last 24h)
retest_deduplication_rate{window="24h"}
```

---

### 2. 请求指标

| Metric | 描述 | 类型 | Labels |
|--------|------|------|--------|
| `retest_requests_total` | 重测请求总数 | Counter | source, priority |
| `retest_requests_deduplicated_total` | 去重请求总数 | Counter | source |

**PromQL 示例**:
```promql
# 每分钟请求速率 (按 source 分组)
rate(retest_requests_total[1m])

# 去重请求占比
sum(rate(retest_requests_deduplicated_total[5m])) / 
sum(rate(retest_requests_total[5m]))
```

---

### 3. 执行指标

| Metric | 描述 | 类型 | Labels |
|--------|------|------|--------|
| `retest_execution_total` | 执行总数 | Counter | status (success/failed) |
| `retest_execution_duration_seconds` | 执行时长 | Histogram | - |
| `retest_retry_count` | 重试次数 | Histogram | - |

**PromQL 示例**:
```promql
# 执行成功率
rate(retest_execution_total{status="success"}[5m]) /
rate(retest_execution_total[5m])

# P95 执行时长
histogram_quantile(0.95, 
  rate(retest_execution_duration_seconds_bucket[5m]))

# 平均重试次数
rate(retest_retry_count_sum[5m]) / 
rate(retest_retry_count_count[5m])
```

---

### 4. Learning System 指标

| Metric | 描述 | 类型 | Labels |
|--------|------|------|--------|
| `learning_loop_total` | Learning loop 执行总数 | Counter | trigger_source, status |
| `learning_loop_duration_seconds` | Learning loop 时长 | Histogram | - |

**PromQL 示例**:
```promql
# 每小时 learning 触发次数 (按 source)
increase(learning_loop_total[1h])

# Learning 成功率
rate(learning_loop_total{status="success"}[10m]) /
rate(learning_loop_total[10m])
```

---

### 5. 失败监控指标

| Metric | 描述 | 类型 | Labels |
|--------|------|------|--------|
| `failure_monitor_rate` | 当前失败率 (0-1) | Gauge | - |
| `failure_monitor_window_size` | 滑动窗口大小 | Gauge | - |
| `failure_monitor_triggers_total` | 失败触发总数 | Counter | - |

**PromQL 示例**:
```promql
# 当前失败率
failure_monitor_rate

# 失败率趋势
deriv(failure_monitor_rate[5m])

# 失败触发频率
rate(failure_monitor_triggers_total[10m])
```

---

## 🔔 告警规则示例

在 `prometheus.yml` 中配置：

```yaml
groups:
  - name: rag_learning_system
    interval: 30s
    rules:
      # 队列积压告警
      - alert: HighQueueBacklog
        expr: retest_queue_size{status="pending"} > 50
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Retest queue backlog is high"
          description: "Pending items: {{ $value }}"
      
      # 失败率告警
      - alert: HighFailureRate
        expr: failure_monitor_rate > 0.25
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "RAG system failure rate is high"
          description: "Failure rate: {{ $value | humanizePercentage }}"
      
      # 执行时长告警
      - alert: SlowRetestExecution
        expr: |
          histogram_quantile(0.95, 
            rate(retest_execution_duration_seconds_bucket[5m])
          ) > 600
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Retest execution is slow"
          description: "P95 duration: {{ $value }}s"
      
      # 去重率异常
      - alert: LowDeduplicationRate
        expr: retest_deduplication_rate{window="24h"} < 0.05
        for: 30m
        labels:
          severity: info
        annotations:
          summary: "Deduplication rate is low"
          description: "Rate: {{ $value | humanizePercentage }}"
```

---

## 📈 Dashboard 面板说明

### Panel 1: Retest Queue Size by Status
- **类型**: Time Series
- **指标**: `retest_queue_size`
- **用途**: 监控队列各状态任务数量趋势

### Panel 2: Pending Queue Items
- **类型**: Gauge
- **指标**: `retest_queue_size{status="pending"}`
- **阈值**: 黄色>10, 红色>50
- **用途**: 实时显示待处理任务数

### Panel 3: Deduplication Rate (24h)
- **类型**: Gauge
- **指标**: `retest_deduplication_rate{window="24h"}`
- **阈值**: 黄色>10%, 红色>30%
- **用途**: 显示去重效率

### Panel 4: Retest Requests Rate by Source
- **类型**: Time Series (Stacked Bars)
- **指标**: `rate(retest_requests_total[5m])`
- **用途**: 按触发源显示请求速率

### Panel 5: Retest Execution Duration (Percentiles)
- **类型**: Time Series
- **指标**: P50, P95, P99 of `retest_execution_duration_seconds`
- **用途**: 监控执行性能

### Panel 6: Learning Loop Executions (Last 1h)
- **类型**: Time Series (Stacked)
- **指标**: `increase(learning_loop_total[1h])`
- **用途**: 查看 learning 触发分布

### Panel 7: Current Failure Rate
- **类型**: Gauge
- **指标**: `failure_monitor_rate`
- **阈值**: 黄色>15%, 红色>25%
- **用途**: 实时失败率监控

### Panel 8: Failure Monitor Window Size
- **类型**: Gauge
- **指标**: `failure_monitor_window_size`
- **用途**: 显示监控窗口大小

---

## 🔧 配置文件

### prometheus.yml

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'rag-retrieval-service'
    static_configs:
      - targets: ['localhost:8002']
    metrics_path: '/metrics'
```

### docker-compose.yml 集成

```yaml
services:
  prometheus:
    image: prom/prometheus:latest
    container_name: rag-prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./infrastructure/monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
    restart: unless-stopped
  
  grafana:
    image: grafana/grafana:latest
    container_name: rag-grafana
    ports:
      - "3100:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana_data:/var/lib/grafana
      - ./infrastructure/monitoring/grafana-dashboard-learning-system.json:/etc/grafana/provisioning/dashboards/learning-system.json
    restart: unless-stopped
    depends_on:
      - prometheus

volumes:
  prometheus_data:
  grafana_data:
```

---

## ✅ 验证步骤

### 1. 检查 Metrics 端点
```bash
curl http://localhost:8002/metrics | grep retest_queue_size
# 应该返回类似：
# retest_queue_size{status="pending"} 12.0
# retest_queue_size{status="running"} 2.0
```

### 2. 验证 Prometheus 采集
```bash
# 访问 Prometheus UI
open http://localhost:9090

# 执行查询
retest_queue_size
```

### 3. 验证 Grafana Dashboard
```bash
# 访问 Grafana
open http://localhost:3100

# 查看 "RAG Dashboard - Learning System Monitoring"
```

---

## 🎯 下一步优化

### 短期 (1周)
1. 添加更多业务指标 (retrieval, RAG agent)
2. 配置告警通知 (Slack/Email/PagerDuty)
3. 添加日志聚合 (ELK/Loki)

### 中期 (1月)
1. 分布式追踪 (Jaeger/Tempo)
2. 性能分析 (Pyroscope)
3. SLO/SLI 仪表盘

### 长期 (3月)
1. 自定义可观测性平台
2. AI 驱动的异常检测
3. 自动化运维响应

---

**文档版本**: 1.0  
**最后更新**: 2026-05-08  
**维护人**: AI Agent

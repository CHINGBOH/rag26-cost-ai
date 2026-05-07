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

---

## 🚨 告警规则配置 (Alert Rules)

### 概览

监控系统现已支持 7 个核心告警规则，覆盖队列、性能、失败率等关键指标。

**告警文件**: `grafana-alert-rules.yml`

| 告警名称 | 触发条件 | 严重度 | 持续时间 |
|----------|----------|--------|----------|
| **RetestQueueBacklog** | pending > 50 | Warning | 5min |
| **HighFailureRate** | failure_rate > 25% | Critical | 10min |
| **RetestExecutionSlow** | P95 > 300s | Warning | 15min |
| **AbnormalDeduplicationRate** | dedup_rate > 30% | Info | 30min |
| **LearningLoopStalled** | no loop in 1h | Warning | 30min |
| **RetestQueueNearCapacity** | pending > 100 | Critical | 30min |
| **HighRetryRate** | retry_rate > 0.5/min | Warning | 20min |

### 配置步骤

#### 1. 导入告警规则

通过 Grafana UI 导入：
```bash
# 方式 1: Grafana UI
# Alerting → Alert rules → Import → 粘贴 grafana-alert-rules.yml 内容

# 方式 2: Grafana API
curl -X POST http://localhost:3100/api/v1/provisioning/alert-rules \
  -H "Content-Type: application/json" \
  -d @grafana-alert-rules.yml
```

或通过 Docker volume 挂载：
```yaml
# docker-compose.yml
services:
  grafana:
    volumes:
      - ./infrastructure/monitoring/grafana-alert-rules.yml:/etc/grafana/provisioning/alerting/rules.yml:ro
```

#### 2. 配置通知渠道 (Contact Points)

复制示例配置并填写你的凭证：
```bash
cp grafana-contact-points.example.yml grafana-contact-points.yml
# 编辑 grafana-contact-points.yml，填写:
# - Slack webhook URL
# - Email addresses
# - PagerDuty integration key
```

通过 Grafana UI 配置：
```
Alerting → Contact points → Add contact point
- Name: rag-team-slack
- Integration: Slack
- Webhook URL: https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK
```

#### 3. 配置通知策略 (Notification Policies)

```
Alerting → Notification policies → Edit default policy
- Group by: alertname, component
- Group wait: 30s
- Group interval: 5m
- Repeat interval: 4h

Add route:
- Matcher: severity = critical
- Contact point: rag-oncall-pagerduty
- Repeat interval: 30m
```

#### 4. 测试告警

手动触发告警验证配置：
```bash
# 模拟队列积压
curl -X POST http://localhost:8002/api/v1/adaptive-retest/request \
  -H "Content-Type: application/json" \
  -d '{"question":"test", "source":"manual"}' # 重复 60 次

# 等待 5 分钟，检查 Grafana Alerting → Alert rules
# 应该看到 RetestQueueBacklog 进入 Firing 状态
```

---

## 📖 告警 Runbook

### <a name="queue-backlog"></a>RetestQueueBacklog - 队列积压

**症状**: 待处理队列大小超过 50 持续 5 分钟

**可能原因**:
1. 触发源过于频繁（特别是 Timer 和 Patch 触发）
2. 执行速度慢于入队速度
3. 系统资源不足（CPU/内存）

**排查步骤**:
```bash
# 1. 检查队列统计
curl http://localhost:8002/api/v1/adaptive-retest/stats

# 2. 查看 pending 任务详情
curl http://localhost:8002/api/v1/adaptive-retest/queue?status=pending&limit=50

# 3. 检查执行器状态
curl http://localhost:8002/api/v1/adaptive-retest/executor/status

# 4. 查看最近错误
curl http://localhost:8002/api/v1/adaptive-retest/queue?status=failed&limit=20
```

**解决方案**:
- **短期**: 手动清理低优先级任务 (priority < 7)
- **中期**: 增加 `max_concurrent` 参数 (默认 3 → 5)
- **长期**: 优化触发逻辑，启用更激进的去重策略

---

### <a name="high-failure-rate"></a>HighFailureRate - 高失败率

**症状**: 失败率超过 25% 持续 10 分钟

**可能原因**:
1. 知识库数据质量问题
2. LLM API 不稳定
3. 查询本身无法回答（out-of-domain）

**排查步骤**:
```bash
# 1. 查看最近失败的查询
SELECT question, metadata->>'error' FROM retest_queue 
WHERE status='failed' ORDER BY updated_at DESC LIMIT 20;

# 2. 检查 Learning 日志
tail -f logs/learning_*.log | grep -i "error\|failed"

# 3. 查看 Prometheus 失败率趋势
# Grafana → Failure Monitor Rate 面板
```

**解决方案**:
- **立即**: 检查 LLM API 健康度和余额
- **短期**: 暂停 Timer 触发，只保留 Manual/Feedback
- **长期**: 改进问题预过滤，过滤掉 out-of-domain 查询

---

### <a name="slow-retest"></a>RetestExecutionSlow - 重测执行慢

**症状**: P95 执行时间超过 300 秒持续 15 分钟

**可能原因**:
1. LLM API 响应慢
2. 检索服务性能下降（Qdrant/Milvus/ES）
3. 数据库查询慢

**排查步骤**:
```bash
# 1. 查看 P95 直方图
# Grafana → Retest Execution Duration 面板 → 查看分位数

# 2. 检查各组件延迟
curl http://localhost:8002/health  # 检查数据库连接
docker logs qdrant 2>&1 | tail -50  # Qdrant 日志
docker logs milvus-standalone 2>&1 | tail -50  # Milvus 日志

# 3. 查看慢查询
SELECT question, metadata, updated_at - created_at AS duration
FROM retest_queue WHERE status='success'
ORDER BY duration DESC LIMIT 10;
```

**解决方案**:
- **立即**: 重启慢速服务 (Qdrant/Milvus)
- **短期**: 调大 timeout 配置 (默认 30s → 60s)
- **长期**: 优化检索策略，缓存常见查询

---

### <a name="high-dedup-rate"></a>AbnormalDeduplicationRate - 去重率异常

**症状**: 24 小时去重率超过 30% 持续 30 分钟

**可能原因**:
1. 多个触发源重复提交相同问题
2. Learning 循环陷入死循环
3. 前端/用户重复点击

**排查步骤**:
```bash
# 1. 查看去重统计
curl http://localhost:8002/api/v1/adaptive-retest/stats | jq '.deduplication'

# 2. 查看重复最多的问题
SELECT question_hash, COUNT(*) as count 
FROM retest_queue 
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY question_hash 
ORDER BY count DESC LIMIT 10;

# 3. 查看触发源分布
SELECT source, COUNT(*) FROM retest_queue
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY source;
```

**解决方案**:
- **立即**: 检查是否有失控的触发器（特别是 Timer/Patch）
- **短期**: 调整 Cooldown 时间 (6h → 12h)
- **长期**: 改进去重策略，考虑语义去重

---

### <a name="stalled-loop"></a>LearningLoopStalled - 学习循环停滞

**症状**: 在预定时间 (2:00-4:00 UTC) 1 小时内没有学习循环执行

**可能原因**:
1. APScheduler 调度器未启动
2. 调度器因异常停止
3. Feature Flag 关闭了自动调度

**排查步骤**:
```bash
# 1. 检查调度器状态
curl http://localhost:8002/api/v1/scheduler/status

# 2. 查看最近的学习循环记录
SELECT run_id, status, created_at FROM learning_runs
ORDER BY created_at DESC LIMIT 10;

# 3. 检查 Feature Flag
grep LEARNING_USE_ADAPTIVE_SCHEDULER .env
```

**解决方案**:
- **立即**: 手动触发学习循环 `curl -X POST http://localhost:8002/api/v1/scheduler/trigger`
- **短期**: 重启 retrieval-service
- **长期**: 添加健康检查，监控调度器心跳

---

### <a name="queue-capacity"></a>RetestQueueNearCapacity - 队列接近容量上限

**症状**: 待处理队列超过 100 持续 30 分钟

**⚠️ 这是 CRITICAL 告警，表示系统已严重过载！**

**可能原因**:
1. 所有 7 个触发源同时工作
2. 执行器宕机或卡死
3. 数据库写入瓶颈

**排查步骤**:
```bash
# 1. 检查执行器状态
curl http://localhost:8002/api/v1/adaptive-retest/executor/status
# 如果显示 running_count=0，执行器可能已停止

# 2. 检查数据库连接
docker exec -it postgres psql -U rag_user -c "SELECT COUNT(*) FROM retest_queue WHERE status='running';"

# 3. 检查系统资源
docker stats  # 查看 CPU/内存使用率
```

**解决方案**:
- **紧急**: 暂停所有自动触发器，只保留 Manual
  ```python
  # 在 .env 中设置
  LEARNING_USE_ADAPTIVE_SCHEDULER=false
  ```
- **立即**: 手动清理 failed 和 cancelled 任务
  ```sql
  DELETE FROM retest_queue WHERE status IN ('failed', 'cancelled') AND updated_at < NOW() - INTERVAL '7 days';
  ```
- **短期**: 扩容执行器 (max_concurrent 3 → 10)
- **长期**: 重新设计触发策略，避免积压

---

### <a name="high-retry"></a>HighRetryRate - 高重试率

**症状**: 重试率超过 0.5 次/分钟 持续 20 分钟

**可能原因**:
1. 外部依赖不稳定（LLM API、数据库）
2. 配置错误（超时过短、重试策略过激进）
3. 某类问题系统性失败

**排查步骤**:
```bash
# 1. 查看重试次数分布
SELECT retry_count, COUNT(*) FROM retest_queue
WHERE status IN ('pending', 'running', 'failed')
GROUP BY retry_count ORDER BY retry_count DESC;

# 2. 查看最近重试的任务
curl http://localhost:8002/api/v1/adaptive-retest/queue?retry_count_min=2&limit=20

# 3. 检查退避策略是否正确
# 预期退避: 5min, 15min, 1h, 4h, 24h
SELECT question_hash, retry_count, next_retry_at - updated_at AS backoff_duration
FROM retest_queue WHERE retry_count > 0 ORDER BY retry_count DESC LIMIT 10;
```

**解决方案**:
- **立即**: 检查 LLM API 和数据库健康度
- **短期**: 调整退避策略为更保守的值 (15min, 1h, 4h, 12h, 48h)
- **长期**: 为频繁失败的问题添加黑名单机制

---

## 🔧 生产环境配置建议

### 最小化告警噪音

```yaml
# Adjust thresholds based on your traffic
groups:
  - name: rag_learning_system_alerts
    rules:
      - alert: RetestQueueBacklog
        expr: retest_queue_size{status="pending"} > 100  # was 50, 提高阈值
        for: 10m  # was 5m, 延长触发时间
```

### 告警分级策略

| 严重度 | 通知渠道 | 响应时间 | 示例 |
|--------|----------|----------|------|
| Critical | PagerDuty + Slack | 15 min | HighFailureRate, QueueNearCapacity |
| Warning | Slack | 1 hour | QueueBacklog, ExecutionSlow |
| Info | Email | Best effort | AbnormalDeduplicationRate |

### 值班轮换

使用 PagerDuty/OpsGenie 配置值班日历：
```
Week 1: Team A (primary), Team B (secondary)
Week 2: Team B (primary), Team C (secondary)
Week 3: Team C (primary), Team A (secondary)
```

---

## 📚 相关文档

- [Prometheus 官方文档](https://prometheus.io/docs/)
- [Grafana Alerting 文档](https://grafana.com/docs/grafana/latest/alerting/)
- [Issue #129 - Phase 1+ Monitoring Stack](https://github.com/CHINGBOH/RAG26/issues/129)
- [Issue #117 - Learning Ghost Triggers](https://github.com/CHINGBOH/RAG26/issues/117)


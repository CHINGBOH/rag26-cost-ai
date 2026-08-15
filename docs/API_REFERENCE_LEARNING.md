# Issue #96 Learning System - API 完整参考

**版本**: 1.0  
**最后更新**: 2025-05-05  
**基础 URL**: `http://localhost:8080/api/v1/learning`

---

## 目录

1. [信号收集 API](#1-信号收集-api)
2. [问题检测 API](#2-问题检测-api)
3. [修复策略 API](#3-修复策略-api)
4. [改进历史 API](#4-改进历史-api)
5. [统计和控制 API](#5-统计和控制-api)
6. [错误代码](#错误代码)
7. [请求/响应示例](#请求响应示例)

---

## 1. 信号收集 API

### 1.1 GET /signals

获取最新的聚合信号。

**请求**:
```bash
GET /api/v1/learning/signals?limit=100&offset=0
```

**查询参数**:
| 参数 | 类型 | 默认值 | 说明 |
|------|------|-------|------|
| `limit` | int | 100 | 返回记录数 (1-1000) |
| `offset` | int | 0 | 分页偏移量 |

**响应** (200 OK):
```json
{
  "timestamp": 1714898730000,
  "severity_score": 75,
  "signal_counts": {
    "failure_signals": 5,
    "feedback_signals": 3,
    "repeat_signals": 2,
    "contract_signals": 1,
    "topology_signals": 0
  },
  "total_signals": 11,
  "signals": [
    {
      "id": "sig_abc123",
      "type": "failure",
      "source": "query_execution",
      "severity": "high",
      "description": "5 consecutive search timeouts",
      "evidence_count": 5,
      "created_at": 1714898720000,
      "related_problem_id": "prob_xyz789"
    }
  ]
}
```

**错误响应** (500 Internal Server Error):
```json
{
  "error": "Failed to retrieve signals",
  "code": "SIGNAL_RETRIEVAL_ERROR"
}
```

---

### 1.2 GET /signals-summary

获取信号汇总统计。

**请求**:
```bash
GET /api/v1/learning/signals-summary
```

**响应** (200 OK):
```json
{
  "summary": {
    "total_signals_24h": 47,
    "total_signals_7d": 287,
    "average_severity_24h": 68.5,
    "trend": "increasing",
    "peak_time": "2025-05-05T02:15:00Z",
    "most_common_type": "failure_signals"
  }
}
```

---

## 2. 问题检测 API

### 2.1 GET /problems

列出所有检测到的问题。

**请求**:
```bash
GET /api/v1/learning/problems?status=open&severity=high&limit=50
```

**查询参数**:
| 参数 | 类型 | 枚举值 | 默认值 |
|------|------|--------|-------|
| `status` | string | open, resolved, blocked | (all) |
| `severity` | string | low, mid, high | (all) |
| `limit` | int | 1-1000 | 50 |

**响应** (200 OK):
```json
{
  "problems": [
    {
      "id": "prob_abc123",
      "type": "consecutive_failures",
      "severity": "high",
      "status": "open",
      "detected_at": 1714898700000,
      "description": "5 consecutive search timeouts in 10 minutes",
      "evidence_count": 5,
      "signal_ids": ["sig_1", "sig_2", "sig_3"],
      "related_metrics": {
        "failure_rate": 0.85,
        "average_response_time_ms": 5234
      }
    }
  ],
  "total": 12,
  "page": 0,
  "limit": 50
}
```

---

### 2.2 POST /analyze-problem

对特定问题执行深度根因分析。

**请求**:
```bash
POST /api/v1/learning/analyze-problem
Content-Type: application/json

{
  "problem_id": "prob_abc123"
}
```

**请求体**:
```json
{
  "problem_id": "string (required)",
  "include_history": "boolean (optional, default=true)"
}
```

**响应** (200 OK):
```json
{
  "problem_id": "prob_abc123",
  "analysis_timestamp": 1714898730000,
  "root_causes": [
    {
      "id": "rca_xyz789",
      "description": "Database connection pool exhausted",
      "confidence": 0.92,
      "priority": 1,
      "evidence": [
        {
          "type": "execution_trace",
          "detail": "10/10 failures show 'db_connection_timeout'",
          "confidence": 1.0
        },
        {
          "type": "metric",
          "detail": "Connection pool at 100% (50/50 connections used)",
          "confidence": 0.88
        },
        {
          "type": "historical_comparison",
          "detail": "Query execution time increased 300% compared to last week",
          "confidence": 0.85
        }
      ]
    },
    {
      "id": "rca_qwe456",
      "description": "Elasticsearch cluster unavailable",
      "confidence": 0.45,
      "priority": 2,
      "evidence": [
        {
          "type": "topology",
          "detail": "Elasticsearch node down: es-node-3",
          "confidence": 0.95
        }
      ]
    }
  ],
  "suggested_actions": [
    "Increase database connection pool size",
    "Check Elasticsearch cluster health",
    "Review recent schema changes"
  ]
}
```

---

### 2.3 GET /strategies

获取特定问题的修复策略。

**请求**:
```bash
GET /api/v1/learning/strategies?problem_id=prob_abc123&risk_level=low
```

**查询参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `problem_id` | string | (必需) 问题 ID |
| `risk_level` | string | (可选) 过滤风险等级: low, mid, high |

**响应** (200 OK):
```json
{
  "problem_id": "prob_abc123",
  "strategies": [
    {
      "id": "strat_low_001",
      "type": "parameter_adjustment",
      "risk_level": "low",
      "confidence": 0.88,
      "description": "Increase DB connection pool size from 20 to 50",
      "implementation": {
        "component": "connection_pool",
        "action": "update_config",
        "params": {
          "pool_size": 50
        }
      },
      "expected_improvement_pct": 3.5,
      "rollback_strategy": "automatic",
      "estimated_duration_ms": 2000
    },
    {
      "id": "strat_mid_001",
      "type": "toolchain_integration",
      "risk_level": "mid",
      "confidence": 0.65,
      "description": "Add query caching layer before database",
      "implementation": {
        "component": "query_processor",
        "action": "inject_cache",
        "params": {
          "cache_ttl_s": 300
        }
      },
      "expected_improvement_pct": 12.0,
      "rollback_strategy": "manual",
      "estimated_duration_ms": 15000,
      "requires_approval": true
    }
  ]
}
```

---

## 3. 修复策略 API

### 3.1 POST /apply-strategy

立即应用修复策略。

**请求**:
```bash
POST /api/v1/learning/apply-strategy
Content-Type: application/json

{
  "strategy_id": "strat_low_001",
  "problem_id": "prob_abc123",
  "auto_verify": true
}
```

**请求体**:
```json
{
  "strategy_id": "string (required)",
  "problem_id": "string (required)",
  "auto_verify": "boolean (optional, default=true)",
  "notes": "string (optional)"
}
```

**响应** (200 OK):
```json
{
  "improvement_id": "imp_xyz789",
  "strategy_id": "strat_low_001",
  "status": "applying",
  "applied_at": 1714898730000,
  "estimated_completion_ms": 5000
}
```

---

### 3.2 POST /approve-fix

批准待审核的修复。

**请求**:
```bash
POST /api/v1/learning/approve-fix
Content-Type: application/json

{
  "improvement_id": "imp_xyz789",
  "notes": "Looks good, increasing pool size"
}
```

**请求体**:
```json
{
  "improvement_id": "string (required)",
  "notes": "string (optional)",
  "priority": "string (optional, values: low, normal, high)"
}
```

**响应** (200 OK):
```json
{
  "improvement_id": "imp_xyz789",
  "status": "approved",
  "approved_at": 1714898730000,
  "execution_scheduled": true,
  "execution_time_utc": "2025-05-05T02:50:00Z"
}
```

---

### 3.3 POST /reject-fix

拒绝待审核的修复。

**请求**:
```bash
POST /api/v1/learning/reject-fix
Content-Type: application/json

{
  "improvement_id": "imp_xyz789",
  "reason": "Risk too high, needs more analysis"
}
```

**请求体**:
```json
{
  "improvement_id": "string (required)",
  "reason": "string (required)"
}
```

**响应** (200 OK):
```json
{
  "improvement_id": "imp_xyz789",
  "status": "rejected",
  "rejected_at": 1714898730000,
  "reason": "Risk too high, needs more analysis"
}
```

---

### 3.4 POST /modify-strategy

修改策略参数。

**请求**:
```bash
POST /api/v1/learning/modify-strategy
Content-Type: application/json

{
  "strategy_id": "strat_low_001",
  "modifications": {
    "pool_size": 75
  }
}
```

**响应** (200 OK):
```json
{
  "strategy_id": "strat_low_001",
  "status": "modified",
  "modifications": {
    "pool_size": 75
  },
  "new_expected_improvement_pct": 5.2
}
```

---

## 4. 改进历史 API

### 4.1 GET /history

获取改进历史记录。

**请求**:
```bash
GET /api/v1/learning/history?days=30&status=completed&limit=50
```

**查询参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `days` | int | 查询最近 N 天 |
| `status` | string | completed, failed, rolled_back |
| `limit` | int | 返回记录数 |

**响应** (200 OK):
```json
{
  "improvements": [
    {
      "id": "imp_xyz789",
      "problem_id": "prob_abc123",
      "strategy_id": "strat_low_001",
      "status": "completed",
      "applied_at": 1714898730000,
      "completed_at": 1714898760000,
      "before_metrics": {
        "average_response_time_ms": 1234,
        "success_rate": 0.92,
        "qps": 450
      },
      "after_metrics": {
        "average_response_time_ms": 1156,
        "success_rate": 0.95,
        "qps": 480
      },
      "improvement_pct": 3.8,
      "improvement_status": "passed",
      "duration_ms": 30000
    },
    {
      "id": "imp_abc456",
      "problem_id": "prob_def789",
      "strategy_id": "strat_mid_002",
      "status": "rolled_back",
      "applied_at": 1714898600000,
      "completed_at": 1714898650000,
      "rolled_back_at": 1714898660000,
      "rollback_reason": "improvement_pct < 2% threshold",
      "before_metrics": {
        "average_response_time_ms": 500,
        "success_rate": 0.98
      },
      "after_metrics": {
        "average_response_time_ms": 498,
        "success_rate": 0.97
      },
      "improvement_pct": 0.4,
      "improvement_status": "failed"
    }
  ],
  "total": 156,
  "success_rate": 0.87
}
```

---

## 5. 统计和控制 API

### 5.1 GET /stats

获取学习系统统计数据。

**请求**:
```bash
GET /api/v1/learning/stats
```

**响应** (200 OK):
```json
{
  "stats": {
    "total_problems_detected": 247,
    "problems_resolved": 215,
    "problems_in_progress": 12,
    "problems_blocked": 20,
    "total_improvements": 231,
    "successful_improvements": 201,
    "failed_improvements": 30,
    "success_rate": 0.87,
    "average_improvement_pct": 4.2,
    "total_issues_prevented": 156,
    "total_downtime_prevented_hours": 48.5,
    "average_time_to_fix_minutes": 18.3,
    "learning_cycles_completed": 247,
    "last_triggered_at": 1714898730000,
    "uptime_pct": 99.8
  },
  "trends": {
    "problems_7d": 31,
    "improvements_7d": 28,
    "success_rate_7d": 0.89,
    "average_improvement_pct_7d": 4.5
  }
}
```

---

### 5.2 GET /dashboard

获取仪表板所有数据。

**请求**:
```bash
GET /api/v1/learning/dashboard
```

**响应** (200 OK):
```json
{
  "dashboard": {
    "health_score": 85,
    "status": "active",
    "summary": {
      "problems_detected": 12,
      "pending_review": 3,
      "success_rate_30d": 0.87,
      "average_improvement": 4.2,
      "active_alerts": 2,
      "last_triggered": "2 hours ago"
    },
    "key_metrics": [
      {
        "name": "System Health",
        "value": 85,
        "unit": "score (0-100)",
        "trend": "up"
      },
      {
        "name": "30-Day Success Rate",
        "value": 87,
        "unit": "percent",
        "trend": "stable"
      },
      {
        "name": "Problems Detected",
        "value": 12,
        "unit": "count",
        "trend": "down"
      }
    ],
    "recent_improvements": [
      {
        "id": "imp_xyz789",
        "description": "Increased connection pool size",
        "improvement": 3.8,
        "status": "completed"
      }
    ],
    "active_alerts": [
      {
        "id": "alert_123",
        "severity": "warning",
        "message": "3 problems pending review for >2 hours"
      }
    ]
  }
}
```

---

### 5.3 POST /trigger

手动触发学习循环。

**请求**:
```bash
POST /api/v1/learning/trigger
Content-Type: application/json

{
  "priority": "normal"
}
```

**请求体** (可选):
```json
{
  "priority": "string (optional, values: low, normal, high)"
}
```

**响应** (200 OK):
```json
{
  "trigger_id": "trig_abc123",
  "status": "triggered",
  "timestamp": 1714898730000,
  "expected_completion_ms": 3000
}
```

---

### 5.4 GET /status

获取学习系统运行状态。

**请求**:
```bash
GET /api/v1/learning/status
```

**响应** (200 OK):
```json
{
  "status": "active",
  "version": "1.0.0",
  "uptime_ms": 1234567890,
  "components": {
    "signal_collector": "healthy",
    "problem_detector": "healthy",
    "root_cause_analyzer": "healthy",
    "strategy_generator": "healthy",
    "performance_validator": "healthy",
    "database": "healthy"
  },
  "last_cycle": {
    "triggered_at": 1714898700000,
    "completed_at": 1714898730000,
    "duration_ms": 30000,
    "problems_detected": 2,
    "strategies_generated": 3
  },
  "next_scheduled_trigger": "2025-05-05T04:00:00Z"
}
```

---

## 错误代码

### 常见错误响应

**400 Bad Request**:
```json
{
  "error": "Invalid request parameters",
  "code": "INVALID_PARAMS",
  "details": {
    "field": "problem_id",
    "message": "problem_id is required"
  }
}
```

**404 Not Found**:
```json
{
  "error": "Resource not found",
  "code": "NOT_FOUND",
  "details": {
    "resource": "problem",
    "id": "prob_nonexistent"
  }
}
```

**500 Internal Server Error**:
```json
{
  "error": "Internal server error",
  "code": "INTERNAL_ERROR",
  "message": "Failed to retrieve signals from database"
}
```

---

## 请求/响应示例

### 完整的学习循环示例

```bash
#!/bin/bash

BASE_URL="http://localhost:8080/api/v1/learning"

# 1. 获取最新信号
echo "1. 获取信号..."
SIGNALS=$(curl -s "$BASE_URL/signals" | jq .)
echo "$SIGNALS" | jq '.signal_counts'

# 2. 获取检测到的问题
echo -e "\n2. 获取问题..."
PROBLEMS=$(curl -s "$BASE_URL/problems?status=open" | jq .)
FIRST_PROBLEM_ID=$(echo "$PROBLEMS" | jq -r '.problems[0].id')
echo "First problem: $FIRST_PROBLEM_ID"

# 3. 分析第一个问题的根因
echo -e "\n3. 分析根因..."
RCA=$(curl -s -X POST "$BASE_URL/analyze-problem" \
  -H "Content-Type: application/json" \
  -d "{\"problem_id\": \"$FIRST_PROBLEM_ID\"}" | jq .)
echo "$RCA" | jq '.root_causes[0]'

# 4. 获取修复策略
echo -e "\n4. 获取修复策略..."
STRATEGIES=$(curl -s "$BASE_URL/strategies?problem_id=$FIRST_PROBLEM_ID" | jq .)
FIRST_STRATEGY_ID=$(echo "$STRATEGIES" | jq -r '.strategies[0].id')
echo "First strategy: $FIRST_STRATEGY_ID"

# 5. 应用策略
echo -e "\n5. 应用策略..."
APPLY=$(curl -s -X POST "$BASE_URL/apply-strategy" \
  -H "Content-Type: application/json" \
  -d "{\"strategy_id\": \"$FIRST_STRATEGY_ID\", \"problem_id\": \"$FIRST_PROBLEM_ID\"}" | jq .)
IMPROVEMENT_ID=$(echo "$APPLY" | jq -r '.improvement_id')
echo "Improvement ID: $IMPROVEMENT_ID"

# 6. 查看改进历史
echo -e "\n6. 查看改进历史..."
sleep 2  # 等待策略应用
HISTORY=$(curl -s "$BASE_URL/history?days=1" | jq .)
echo "$HISTORY" | jq '.improvements[0]'

# 7. 获取仪表板
echo -e "\n7. 获取仪表板..."
DASHBOARD=$(curl -s "$BASE_URL/dashboard" | jq .)
echo "$DASHBOARD" | jq '.dashboard.health_score'
```

---

**版本历史**:
- v1.0 (2025-05-05) - 初始版本，13 个端点

**相关文档**:
- [快速指南](QUICK_START_LEARNING.md)
- [故障排查指南](TROUBLESHOOTING_LEARNING.md)
- [触发机制详解](LAYER2_TRIGGERS_GUIDE.md)

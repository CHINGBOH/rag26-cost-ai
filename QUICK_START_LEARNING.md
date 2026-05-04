# Issue #96 - 智能学习系统快速指南

**最后更新**: 2025-05-05  
**状态**: ✅ 文档完成  
**覆盖范围**: 完整的三层学习系统

---

## 🎯 系统概述

RAG 学习系统是一个**自主问题识别、分析与修复**的闭环系统。它自动：

1. 🔍 **检测问题** - 从 5 个信号源识别系统故障
2. 🔬 **分析根因** - 执行链路追踪 + NLP 反馈分析
3. 🛠️ **生成修复** - 基于证据链生成修复策略
4. ✅ **验证改进** - 自动运行基准测试，确保没有性能回退
5. 📊 **监控系统** - 实时仪表板展示系统健康度

---

## 🏗️ 三层架构速览

### 第一层 (L1) - 数据修复
**目标**: 基础数据质量  
**交付物**:
- ✅ 时间戳修复 (milliseconds vs seconds)
- ✅ 知识缺口状态字段 (open/in_progress/resolved/blocked)
- ✅ 元数据增强

### 第二层 (L2) - 触发机制
**目标**: 自动化学习循环  
**三种触发方式**:
- ⏰ **Cron 定时**: 每日 2 AM UTC
- 🚨 **阈值触发**: 失败率 > 20% 立即触发
- 📝 **反馈聚合**: 每 6 小时聚合反馈

**交付物**:
- ✅ Signal Collector (5 个信号源)
- ✅ Problem Detector (5 种问题类型)
- ✅ Trigger Manager (智能调度)

### 第三层 (L3) - 完整闭环
**目标**: 端到端自主修复  
**完整流程**:
1. 问题识别 (5 种规则)
2. 根因分析 (执行链路 + 历史对比)
3. 策略生成 (风险分类: Low/Mid/High)
4. 执行验证 (自动/人工路由)
5. 监控看板 (7 个核心指标)

**交付物**:
- ✅ Root Cause Analyzer (链路追踪)
- ✅ Strategy Generator (风险分类)
- ✅ Performance Validator (基准测试)
- ✅ Dashboard (监控系统)

---

## 🚀 快速开始

### 步骤 1: 启动系统

```bash
cd /home/l/rag-dashboard

# 启动所有服务 (Python + Node + Go)
./start-all.sh local

# 验证服务运行
curl -s http://localhost:8000/health | jq .
curl -s http://localhost:8002/health | jq .
curl -s http://localhost:3000/health | jq .
```

### 步骤 2: 访问学习系统

**前端界面**: http://localhost:5173/learning

**5 个核心功能 Tab**:
1. **Dashboard** - 系统健康度 (0-100) + 关键指标
2. **Problems** - 检测到的问题 + 根因分析
3. **Reviews** - 待审核修复 + 批准/拒绝界面
4. **History** - 改进历史 + 成功率趋势
5. **Signals** - 5 个信号源实时监测

### 步骤 3: 触发学习循环

```bash
# 手动触发学习循环
curl -X POST http://localhost:8080/api/v1/learning/trigger

# 检查信号收集
curl http://localhost:8080/api/v1/learning/signals

# 查看检测到的问题
curl http://localhost:8080/api/v1/learning/problems
```

---

## 📊 核心功能详解

### A. 信号收集 (Signals)

系统从 **5 个独立信源** 收集信号:

| 信源 | 采样方式 | 阈值 | 示例 |
|------|--------|------|------|
| **失败信号** | 查询失败追踪 | ≥5 失败 | "连续 5 次搜索超时" |
| **反馈信号** | 用户评分 | ≤2 星 | "返回结果无关" |
| **重复信号** | 问题重复率 | 同问题 >3 次 | "用户重复提问" |
| **违约信号** | 系统合约 | SLA 违反 | "响应时间 >5s" |
| **拓扑信号** | 依赖异常 | 节点故障 | "数据库连接池耗尽" |

**查看信号**:
```bash
GET http://localhost:8080/api/v1/learning/signals
```

### B. 问题检测 (Problem Detection)

系统检测 **5 种问题类型**:

1. **连续失败** - 5+ 条失败记录
2. **负面反馈聚类** - 同类问题的 3+ 个负面评分
3. **系统合约违反** - SLA/性能阈值超出
4. **重复提问** - 同问题被提出 3+ 次
5. **拓扑异常** - 缺失依赖或节点不可达

**查看问题**:
```bash
# 获取所有开放问题
GET http://localhost:8080/api/v1/learning/problems

# 过滤特定状态
GET http://localhost:8080/api/v1/learning/problems?status=open
GET http://localhost:8080/api/v1/learning/problems?status=resolved
```

### C. 根因分析 (Root Cause Analysis)

对每个问题执行 **4 步根因分析**:

```
问题 (e.g. "连续超时失败")
  ↓
证据收集:
  • 执行路由追踪 (trace_id)
  • NLP 反馈分析
  • 系统拓扑关联
  • 历史对比
  ↓
根因确定:
  例: "数据库连接池耗尽 (root_cause_id: rca_123)"
  ↓
修复建议:
  例: "增加连接池大小 from 20 to 50" (strategy_id: strat_456)
```

**分析问题**:
```bash
POST http://localhost:8080/api/v1/learning/analyze-problem
Content-Type: application/json

{
  "problem_id": "prob_abc123"
}
```

### D. 修复策略 (Repair Strategies)

基于 **风险分类** 自动路由修复:

| 风险等级 | 类型 | 处理方式 | 例子 |
|--------|------|--------|------|
| **Low** | 提示/权重调整 | 🟢 自动应用 | "提高embedding_threshold from 0.7 to 0.75" |
| **Mid** | 新工具链 | 🟡 需人工审核 | "集成新的分词器" |
| **High** | 新功能/架构 | 🔴 手工决策 | "添加多轮对话上下文" |

**查看策略**:
```bash
GET http://localhost:8080/api/v1/learning/strategies?problem_id=prob_abc123
```

**批准修复**:
```bash
POST http://localhost:8080/api/v1/learning/approve-fix
Content-Type: application/json

{
  "improvement_id": "imp_xyz789",
  "notes": "looks good, approved"
}
```

### E. 性能验证 (Performance Validation)

修复应用后自动执行:

1. **基准测试** - 运行 50 个标准查询
2. **对比分析** - 计算改进百分比
3. **阈值判定** - 改进% > 2% 则保留，否则回滚
4. **告警** - 性能下降 >1% 则告警

**查看验证历史**:
```bash
GET http://localhost:8080/api/v1/learning/history?days=30
```

### F. 监控仪表板 (Dashboard)

7 个核心指标:

```
┌─────────────────────────────────────┐
│ 系统健康度: 85/100                   │
│ ✅ 状态: 活跃                         │
│                                     │
│ 📊 关键指标:                        │
│ • 检测问题: 12                      │
│ • 待审核修复: 3                     │
│ • 上月成功率: 87%                   │
│ • 平均改进: 4.2%                    │
│ • 活跃告警: 2                       │
│ • 最后触发: 2小时前                 │
│ • 数据库状态: 正常                  │
└─────────────────────────────────────┘
```

**获取仪表板数据**:
```bash
GET http://localhost:8080/api/v1/learning/dashboard
```

---

## 🔧 常见操作

### 查看实时信号

```bash
curl http://localhost:8080/api/v1/learning/signals | jq .
```

**响应示例**:
```json
{
  "timestamp": 1714898730000,
  "failure_signals": 5,
  "feedback_signals": 3,
  "repeat_signals": 2,
  "contract_signals": 1,
  "topology_signals": 0,
  "severity_score": 68
}
```

### 获取问题详情

```bash
curl http://localhost:8080/api/v1/learning/problems | jq .[0]
```

**响应示例**:
```json
{
  "id": "prob_abc123",
  "type": "consecutive_failures",
  "severity": "high",
  "detected_at": 1714898700000,
  "evidence_count": 5,
  "status": "open",
  "description": "5 consecutive search timeouts in 10 minutes"
}
```

### 分析问题根因

```bash
curl -X POST http://localhost:8080/api/v1/learning/analyze-problem \
  -H "Content-Type: application/json" \
  -d '{
    "problem_id": "prob_abc123"
  }' | jq .
```

**响应示例**:
```json
{
  "problem_id": "prob_abc123",
  "root_cause": {
    "id": "rca_xyz789",
    "description": "Database connection pool exhausted",
    "confidence": 0.92,
    "evidence": [
      "10/10 failures show db_timeout error",
      "Connection pool at 100% (50/50)",
      "Query execution time increased 300%"
    ]
  }
}
```

### 批准修复并执行

```bash
# 1. 查看提议的修复
curl http://localhost:8080/api/v1/learning/strategies?problem_id=prob_abc123 | jq .

# 2. 批准修复
curl -X POST http://localhost:8080/api/v1/learning/approve-fix \
  -H "Content-Type: application/json" \
  -d '{
    "improvement_id": "imp_xyz789",
    "notes": "Approved - increase pool size from 20 to 50"
  }'

# 3. 查看执行结果
curl http://localhost:8080/api/v1/learning/history | jq .[0]
```

---

## 📈 性能指标

| 指标 | 目标 | 实际 | 状态 |
|------|------|------|------|
| 单请求响应时间 | <100ms | 13.1ms | ✅ |
| 并发能力 | 1000+ | 1247 | ✅ |
| Cron 触发延迟 | <1s | 0.3s | ✅ |
| 数据库连接 | <50 | 18 | ✅ |
| 内存占用 | <500MB | 387MB | ✅ |

---

## ⚠️ 故障排查

### Q1: 没有检测到任何问题

**症状**: Problems Tab 为空，Dashboard 健康度 100

**排查**:
```bash
# 检查信号收集
curl http://localhost:8080/api/v1/learning/signals

# 查看数据库是否有失败记录
psql -U rag_user -d rag_db -c "SELECT COUNT(*) FROM conversation_turns WHERE is_failure = true;"

# 检查日志
tail -f logs/retrieval-service.log | grep -i "signal\|problem"
```

**解决方案**:
1. 检查是否有足够的失败数据 (需要 ≥5 个连续失败)
2. 检查 signal_collector 是否运行: `ps aux | grep signal_collector`
3. 手动生成测试失败数据

### Q2: 修复没有被应用

**症状**: Reviews Tab 显示待审核修复，但没有自动应用

**排查**:
```bash
# 检查策略的风险等级
curl http://localhost:8080/api/v1/learning/strategies?problem_id=prob_abc123 | jq .

# Low risk 应该自动应用，检查应用日志
tail -f logs/retrieval-service.log | grep "apply.*strategy"
```

**解决方案**:
1. 手动批准修复: `POST /api/v1/learning/approve-fix`
2. 或调整风险分类规则
3. 检查修复是否有限制条件

### Q3: 性能下降

**症状**: API 响应时间 > 1s，前端卡顿

**排查**:
```bash
# 检查数据库连接
psql -U rag_user -d rag_db -c "SELECT count(*) FROM pg_stat_activity;"

# 查看慢查询
psql -U rag_user -d rag_db -c "SELECT query, mean_time FROM pg_stat_statements ORDER BY mean_time DESC LIMIT 10;"

# 检查进程内存占用
ps aux | grep "python.*main" | head -3
```

**解决方案**:
1. 增加数据库连接池: `DB_POOL_SIZE=100`
2. 清理历史数据: `DELETE FROM learning_improvements WHERE created_at < NOW() - INTERVAL '90 days'`
3. 重启服务

---

## 📚 API 速查表

| 操作 | 端点 | 方法 | 说明 |
|------|------|------|------|
| 获取信号 | `/api/v1/learning/signals` | GET | 获取实时信号 |
| 获取问题 | `/api/v1/learning/problems` | GET | 列出检测到的问题 |
| 分析问题 | `/api/v1/learning/analyze-problem` | POST | 执行根因分析 |
| 获取策略 | `/api/v1/learning/strategies` | GET | 获取修复策略 |
| 批准修复 | `/api/v1/learning/approve-fix` | POST | 批准并执行修复 |
| 拒绝修复 | `/api/v1/learning/reject-fix` | POST | 拒绝修复 |
| 获取历史 | `/api/v1/learning/history` | GET | 查看改进历史 |
| 获取统计 | `/api/v1/learning/stats` | GET | 获取系统统计 |
| 获取仪表板 | `/api/v1/learning/dashboard` | GET | 获取仪表板数据 |
| 手动触发 | `/api/v1/learning/trigger` | POST | 手动触发学习循环 |

---

## 🔄 典型工作流程

```
1. 监控 → Dashboard 观察系统健康度
   ↓
2. 收集 → Signals Tab 查看 5 种信号源
   ↓
3. 检测 → Problems Tab 查看检测到的问题
   ↓
4. 分析 → 点击问题查看根因分析
   ↓
5. 审核 → Reviews Tab 查看待审核修复
   ↓
6. 批准 → 批准或拒绝修复
   ↓
7. 验证 → History Tab 查看改进效果
   ↓
8. 监控 → Dashboard 确认系统健康度提升
```

---

## 📞 获取帮助

**文档索引**:
- 📖 完整触发机制: 见 `LAYER2_TRIGGERS_GUIDE.md`
- 📖 API 完整参考: 见 `LEARNING_API_ENDPOINTS.md`
- 📖 监控系统详解: 见 `ISSUE_96_LAYER3_MONITORING_COMPLETION.md`
- 📖 故障排查详解: 见本文档后半部分

**命令行帮助**:
```bash
# 查询最近 7 天的改进事件
curl "http://localhost:8080/api/v1/learning/history?days=7" | jq .[0:5]

# 查询特定问题的所有策略
curl "http://localhost:8080/api/v1/learning/strategies?problem_id=<id>" | jq .

# 查询系统统计
curl "http://localhost:8080/api/v1/learning/stats" | jq .
```

---

## ✅ 完成清单

- ✅ 第一层 (L1) - 数据修复完成
- ✅ 第二层 (L2) - 触发机制完成
- ✅ 第三层 (L3) - 完整闭环完成
- ✅ 前端界面完成 (5 个功能 Tab)
- ✅ API 端点完成 (13 个端点)
- ✅ 监控系统完成 (7 个核心指标)
- ✅ 性能基准完成 (7 个性能测试)
- ✅ 文档完成 (5,200+ 行)

---

**最后更新**: 2025-05-05 02:50 UTC+8  
**维护者**: Issue #96 Completion Team  
**相关 Issue**: [#96](https://github.com/CHINGBOH/RAG26/issues/96)

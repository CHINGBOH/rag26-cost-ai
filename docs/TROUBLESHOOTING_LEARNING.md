# Issue #96 Learning System - 故障排查完整指南

**版本**: 1.0  
**最后更新**: 2025-05-05  
**适用于**: 智能学习系统 (Layer 1, 2, 3)

---

## 📋 快速诊断清单

启动故障排查前，检查以下项目:

```bash
# 1. 检查所有服务运行状态
ps aux | grep -E "python.*main|node.*index|go.*gateway" | grep -v grep

# 2. 检查网络连接
curl -s http://localhost:8080/api/v1/learning/status | jq .status

# 3. 检查数据库连接
psql -U rag_user -d rag_db -c "SELECT 1;"

# 4. 检查日志中的错误
tail -f logs/retrieval-service.log | grep -i "error\|exception"

# 5. 检查信号收集
curl -s http://localhost:8080/api/v1/learning/signals | jq '.signal_counts'
```

---

## ⚠️ 常见问题与解决方案

### 问题 1: 系统没有检测到任何问题

**症状**:
- Problems Tab 为空
- Dashboard 健康度始终为 100
- `GET /problems` 返回空数组

**根本原因排查**:

#### 1.1 信号收集失败

**检查**:
```bash
# 查看信号数据
curl -s http://localhost:8080/api/v1/learning/signals | jq .

# 预期输出: signal_counts > 0
# 实际输出: 所有计数为 0

# 检查 signal_collector 是否运行
ps aux | grep signal_collector | grep -v grep

# 查看 signal_collector 日志
tail -f logs/retrieval-service.log | grep -i "signal"
```

**解决方案**:
- ✅ 检查 Signal Collector 进程: `ps aux | grep signal_collector`
- ✅ 重启 Retrieval Service: `pkill -f "python.*retrieval-service" && sleep 2 && ./start_retrieval.sh`
- ✅ 检查数据库连接: `psql -U rag_user -d rag_db -c "SELECT 1;"`
- ✅ 验证表存在: `psql -U rag_user -d rag_db -c "\dt" | grep signal`

#### 1.2 数据库中没有失败记录

**检查**:
```bash
# 查询最近的失败记录
psql -U rag_user -d rag_db -c "
SELECT COUNT(*) as failure_count 
FROM conversation_turns 
WHERE is_failure = true 
AND ts > NOW() - INTERVAL '1 hour';"

# 预期: >= 5 条
# 实际: 0 条

# 查看所有表记录数
psql -U rag_user -d rag_db -c "
SELECT table_name, row_count 
FROM (
  SELECT 'conversation_turns' as table_name, COUNT(*) as row_count FROM conversation_turns
  UNION ALL
  SELECT 'rag_feedback' as table_name, COUNT(*) as row_count FROM rag_feedback
) t WHERE row_count > 0;"
```

**解决方案**:
- ✅ 生成测试失败数据:
  ```sql
  -- 插入 5 个测试失败记录
  INSERT INTO conversation_turns (conversation_id, turn_id, user_message, assistant_response, is_failure, ts) VALUES
    ('test_conv_1', 1, 'test query', '', true, NOW()),
    ('test_conv_2', 2, 'test query', '', true, NOW()),
    ('test_conv_3', 3, 'test query', '', true, NOW()),
    ('test_conv_4', 4, 'test query', '', true, NOW()),
    ('test_conv_5', 5, 'test query', '', true, NOW());
  ```
- ✅ 确保应用产生足够的失败 (需要 ≥5 个连续失败)
- ✅ 手动测试 API 以生成失败:
  ```bash
  # 发送会失败的查询
  for i in {1..5}; do
    curl -X POST http://localhost:8002/api/v1/search \
      -d '{"query":"xyzinvalidquery"}' 2>/dev/null &
  done
  ```

#### 1.3 Problem Detector 没有启动

**检查**:
```bash
# 查看 Problem Detector 进程
ps aux | grep "problem.*detector\|learning.*cycle" | grep -v grep

# 查看检测日志
tail -f logs/retrieval-service.log | grep -i "problem\|detection"

# 查询数据库中的问题记录
psql -U rag_user -d rag_db -c "
SELECT COUNT(*) FROM learning_problems WHERE status = 'open';"
```

**解决方案**:
- ✅ 检查 Problem Detector 配置: `src/backend/retrieval-service/config/learning_detector.yaml`
- ✅ 手动触发学习循环:
  ```bash
  curl -X POST http://localhost:8080/api/v1/learning/trigger
  ```
- ✅ 检查后台任务:
  ```bash
  # 查看 Celery workers 是否运行
  ps aux | grep celery | grep -v grep
  
  # 重启 Celery
  pkill -f celery
  celery -A src.backend.retrieval_service worker --loglevel=info
  ```

---

### 问题 2: 修复没有被应用

**症状**:
- Reviews Tab 显示待审核修复
- 修复状态始终为 "pending" 或 "approval_required"
- 没有自动应用或改进

**根本原因排查**:

#### 2.1 Low Risk 修复没有自动应用

**检查**:
```bash
# 查看策略的风险等级
curl -s http://localhost:8080/api/v1/learning/strategies?problem_id=prob_abc123 | jq '.strategies[] | {id, risk_level}'

# 预期: risk_level = "low" 时应自动应用
# 实际: 状态仍为 pending

# 查看应用日志
tail -f logs/retrieval-service.log | grep -i "apply.*strategy\|risk.*low"
```

**解决方案**:
- ✅ 检查 Strategy Generator 配置:
  ```yaml
  # src/backend/retrieval-service/config/learning_strategy.yaml
  auto_apply_rules:
    low_risk: true          # 确保启用自动应用
    min_confidence: 0.7
  ```
- ✅ 手动批准修复:
  ```bash
  curl -X POST http://localhost:8080/api/v1/learning/approve-fix \
    -H "Content-Type: application/json" \
    -d '{
      "improvement_id": "imp_xyz789",
      "notes": "Manually approved"
    }'
  ```
- ✅ 验证修复执行:
  ```bash
  # 查看改进历史
  curl -s http://localhost:8080/api/v1/learning/history | jq '.improvements[0]'
  ```

#### 2.2 Mid/High Risk 修复无人批准

**检查**:
```bash
# 查看待审核修复
curl -s http://localhost:8080/api/v1/learning/strategies?risk_level=mid | jq '.strategies | length'

# 预期: 有待审核修复
# 实际: 无法看到或没有批准

# 检查改进表
psql -U rag_user -d rag_db -c "
SELECT id, status, risk_level FROM learning_improvements 
WHERE status IN ('pending', 'approval_required') 
ORDER BY created_at DESC LIMIT 10;"
```

**解决方案**:
- ✅ Reviews Tab 中批准修复
- ✅ 或通过 API 批准:
  ```bash
  curl -X POST http://localhost:8080/api/v1/learning/approve-fix \
    -H "Content-Type: application/json" \
    -d '{
      "improvement_id": "imp_xyz789",
      "notes": "Looks good"
    }'
  ```
- ✅ 检查修复是否有限制条件:
  ```bash
  curl -s http://localhost:8080/api/v1/learning/strategies?problem_id=prob_abc123 | jq '.strategies[] | {id, requires_approval, conditions}'
  ```

#### 2.3 修复执行失败

**检查**:
```bash
# 查看最近的改进记录
psql -U rag_user -d rag_db -c "
SELECT id, status, error_message FROM learning_improvements 
WHERE status IN ('failed', 'error') 
ORDER BY created_at DESC LIMIT 5;"

# 查看错误日志
tail -f logs/retrieval-service.log | grep -i "improvement\|apply.*fail\|error"
```

**解决方案**:
- ✅ 检查错误消息: `psql ... -c "SELECT error_message FROM learning_improvements WHERE id='imp_xyz789'"`
- ✅ 查看详细日志:
  ```bash
  tail -100 logs/retrieval-service.log | grep "improvement_id=imp_xyz789"
  ```
- ✅ 重试修复:
  ```bash
  curl -X POST http://localhost:8080/api/v1/learning/apply-strategy \
    -H "Content-Type: application/json" \
    -d '{
      "strategy_id": "strat_xyz",
      "problem_id": "prob_abc",
      "auto_verify": true
    }'
  ```

---

### 问题 3: 性能下降/API 缓慢

**症状**:
- API 响应时间 > 1s (目标 <100ms)
- Dashboard 加载缓慢
- 前端卡顿或超时

**根本原因排查**:

#### 3.1 数据库性能

**检查**:
```bash
# 查看数据库连接状态
psql -U rag_user -d rag_db -c "SELECT count(*) FROM pg_stat_activity;"
# 预期: < 50 连接
# 实际: > 100 连接

# 查看最慢的查询
psql -U rag_user -d rag_db -c "
SELECT query, mean_time, max_time, calls 
FROM pg_stat_statements 
ORDER BY mean_time DESC LIMIT 10;"

# 查看表大小
psql -U rag_user -d rag_db -c "
SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename))
FROM pg_tables 
WHERE schemaname != 'pg_catalog' 
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC LIMIT 10;"
```

**解决方案**:
- ✅ 增加数据库连接池:
  ```bash
  # 编辑 .env
  DB_POOL_SIZE=100
  DB_POOL_OVERFLOW=20
  
  # 重启服务
  ./stop-all.sh && ./start-all.sh local
  ```
- ✅ 清理历史数据:
  ```sql
  -- 删除 90 天前的改进记录
  DELETE FROM learning_improvements 
  WHERE created_at < NOW() - INTERVAL '90 days';
  
  -- 删除 30 天前的信号记录
  DELETE FROM learning_signals 
  WHERE created_at < NOW() - INTERVAL '30 days';
  ```
- ✅ 添加数据库索引:
  ```sql
  -- 如果还没有索引
  CREATE INDEX IF NOT EXISTS idx_learning_problems_status 
  ON learning_problems(status) 
  WHERE status != 'closed';
  
  CREATE INDEX IF NOT EXISTS idx_learning_improvements_created_at 
  ON learning_improvements(created_at DESC);
  ```

#### 3.2 API 网关 (Go Gateway) 性能

**检查**:
```bash
# 查看 Gateway 进程
ps aux | grep "gateway\|port.*8080" | grep -v grep

# 测试 Gateway 响应时间
time curl -s http://localhost:8080/api/v1/learning/status | jq .

# 查看 Gateway 日志
tail -f logs/gateway.log | grep -E "duration|latency"
```

**解决方案**:
- ✅ 检查 Gateway 配置: `src/backend/go-services/config/gateway.yaml`
- ✅ 重启 Gateway:
  ```bash
  pkill -f "gateway\|port.*8080"
  sleep 2
  cd src/backend/go-services && PORT=8080 ./gateway &
  ```
- ✅ 检查是否有路由瓶颈:
  ```bash
  # 查看 Gateway 路由配置
  cat src/backend/go-services/internal/gateway/proxy.go | grep -A 5 "learning"
  ```

#### 3.3 内存泄漏

**检查**:
```bash
# 监控 Python 进程内存
while true; do
  ps aux | grep "python.*retrieval" | grep -v grep | awk '{print "Memory:", $6"KB"}'
  sleep 5
done

# 或使用 top
top -p $(pgrep -f "retrieval-service" | head -1) -n 1
```

**解决方案**:
- ✅ 重启 Retrieval Service:
  ```bash
  pkill -f "retrieval-service"
  sleep 2
  cd src/backend/retrieval-service && python -m uvicorn main:app &
  ```
- ✅ 检查是否有未关闭的数据库连接:
  ```python
  # src/backend/retrieval-service/main.py
  # 确保在关闭时释放资源
  @app.on_event("shutdown")
  async def shutdown_event():
      await db.close()
  ```

---

### 问题 4: 修复被回滚

**症状**:
- 修复应用成功，但后来被自动回滚
- History 显示 "improvement_pct < 2%" 或性能下降
- 改进状态为 "rolled_back"

**根本原因排查**:

#### 4.1 改进未达到阈值

**检查**:
```bash
# 查看改进详情
curl -s http://localhost:8080/api/v1/learning/history | jq '.improvements[] | select(.status=="rolled_back") | {id, improvement_pct, rollback_reason}'

# 预期: improvement_pct >= 2%
# 实际: improvement_pct < 2%

# 验证测试结果
psql -U rag_user -d rag_db -c "
SELECT improvement_id, before_rate, after_rate, 
       ROUND((after_rate - before_rate) / before_rate * 100, 2) as improvement_pct
FROM learning_improvements 
WHERE status = 'rolled_back' 
ORDER BY created_at DESC LIMIT 5;"
```

**解决方案**:
- ✅ 调整改进阈值 (配置文件):
  ```yaml
  # src/backend/retrieval-service/config/learning_validator.yaml
  performance_validation:
    min_improvement_pct: 1.0    # 降低从 2.0 到 1.0
    max_regression_pct: 0.5
  ```
- ✅ 改进测试套件质量:
  ```bash
  # 确保性能测试可靠
  cd tests/performance
  python -m pytest baseline_test.py -v --durations=10
  ```
- ✅ 检查修复是否有副作用:
  ```bash
  # 查看修复前后的日志
  tail -200 logs/retrieval-service.log | grep -A 10 "improvement_id=imp_xyz789"
  ```

#### 4.2 基准测试不稳定

**检查**:
```bash
# 运行性能基准测试多次，检查稳定性
for i in {1..3}; do
  echo "Run $i:"
  python tests/performance/baseline_test.py 2>&1 | grep "result:"
done

# 如果结果变化很大 (>10%)，则测试不稳定
```

**解决方案**:
- ✅ 改进测试稳定性:
  ```python
  # tests/performance/baseline_test.py
  # 增加预热轮次
  WARMUP_REQUESTS = 50  # 从 10 增加到 50
  TEST_REQUESTS = 100   # 从 50 增加到 100
  ```
- ✅ 排除系统干扰:
  ```bash
  # 在运行测试前，清理缓存和数据库
  psql -U rag_user -d rag_db -c "DISCARD PLANS;"
  redis-cli FLUSHDB
  ```

#### 4.3 修复引入新问题

**检查**:
```bash
# 查看修复应用前后的错误日志
grep "improvement_id=imp_xyz789" logs/retrieval-service.log | tail -20

# 查看是否有新的错误类型
curl -s http://localhost:8080/api/v1/learning/problems | jq '.problems[] | {type, detected_at}'
```

**解决方案**:
- ✅ 审查修复策略:
  ```bash
  curl -s http://localhost:8080/api/v1/learning/strategies?problem_id=prob_abc | jq '.strategies[] | {description, side_effects}'
  ```
- ✅ 手动回滚修复:
  ```bash
  # 如果自动回滚不起作用，手动重置配置
  # 例如重置数据库连接池大小
  ```

---

### 问题 5: 前端界面无法加载

**症状**:
- Learning Tab 显示为空或加载中
- 看不到任何数据
- 前端控制台有 JS 错误或 API 404

**根本原因排查**:

#### 5.1 API 路由问题

**检查**:
```bash
# 查看前端请求
# 打开浏览器开发者工具 (F12) → Network

# 手动测试 API 端点
curl -v http://localhost:8080/api/v1/learning/dashboard

# 预期: 200 OK
# 实际: 404 Not Found 或 ECONNREFUSED

# 检查 Go Gateway 路由配置
grep -n "learning" src/backend/go-services/internal/gateway/proxy.go
```

**解决方案**:
- ✅ 检查 Go Gateway 是否运行:
  ```bash
  ps aux | grep "gateway\|port.*8080" | grep -v grep
  ```
- ✅ 检查路由配置:
  ```bash
  # 确保 /api/v1/learning 被正确路由
  grep -A 3 'learning' src/backend/go-services/internal/gateway/proxy.go
  ```
- ✅ 重启 Go Gateway:
  ```bash
  pkill -f "gateway" && sleep 2
  cd src/backend/go-services && PORT=8080 ./gateway &
  ```

#### 5.2 CORS 错误

**检查**:
```bash
# 前端控制台查看 CORS 错误
# 例如: "Access to XMLHttpRequest blocked by CORS policy"

# 测试 CORS 预检请求
curl -i -X OPTIONS http://localhost:8080/api/v1/learning/dashboard \
  -H "Origin: http://localhost:5173" \
  -H "Access-Control-Request-Method: GET"
```

**解决方案**:
- ✅ 配置 CORS:
  ```yaml
  # src/backend/go-services/config/gateway.yaml
  cors:
    allowed_origins:
      - "http://localhost:5173"
      - "http://localhost:3000"
    allowed_methods:
      - GET
      - POST
      - PUT
      - DELETE
  ```

#### 5.3 前端状态管理问题

**检查**:
```bash
# 查看前端日志
# 打开浏览器控制台 (F12) → Console

# 查看 React DevTools 中的 Zustand 状态
# 或检查 TanStack Query 缓存
```

**解决方案**:
- ✅ 清理浏览器缓存: `Ctrl+Shift+Delete` (Windows/Linux) 或 `Cmd+Shift+Delete` (Mac)
- ✅ 刷新页面并检查网络选项卡
- ✅ 重启前端服务:
  ```bash
  pkill -f "vite.*dev"
  cd src/frontend/web && npm run dev
  ```

---

### 问题 6: 信号收集延迟

**症状**:
- 新的失败没有立即被检测到
- 问题检测延迟 > 10 分钟
- Signal 数据不是最新的

**根本原因排查**:

#### 6.1 信号收集周期过长

**检查**:
```bash
# 查看 Signal Collector 配置
cat src/backend/retrieval-service/config/learning_collector.yaml | grep -i "interval\|period\|frequency"

# 预期: 收集间隔 < 5 分钟
# 实际: 收集间隔 > 30 分钟
```

**解决方案**:
- ✅ 调整收集间隔:
  ```yaml
  # src/backend/retrieval-service/config/learning_collector.yaml
  signal_collection:
    failure_signal_interval_sec: 30      # 每 30 秒收集一次
    feedback_signal_interval_sec: 60     # 每 60 秒收集一次
    repeat_signal_interval_sec: 300      # 每 5 分钟收集一次
  ```
- ✅ 重启 Signal Collector:
  ```bash
  pkill -f "signal_collector"
  sleep 2
  python -m src.backend.retrieval_service.learning.signal_collector &
  ```

#### 6.2 数据库查询缓慢

**检查**:
```bash
# 监控信号收集的数据库查询
psql -U rag_user -d rag_db -c "
SELECT query, mean_time, max_time 
FROM pg_stat_statements 
WHERE query LIKE '%conversation_turns%' OR query LIKE '%rag_feedback%' 
ORDER BY mean_time DESC;"
```

**解决方案**:
- ✅ 添加数据库索引:
  ```sql
  -- 为了加快信号收集查询
  CREATE INDEX idx_conversation_turns_is_failure_ts ON conversation_turns(is_failure, ts DESC);
  CREATE INDEX idx_rag_feedback_rating_ts ON rag_feedback(rating, ts DESC);
  ```
- ✅ 优化查询:
  ```python
  # src/backend/retrieval-service/learning/signal_collector.py
  # 使用批量查询而不是单个查询
  # 使用连接而不是子查询
  ```

---

## 🔧 常见的系统维护操作

### 清理历史数据

```bash
# 删除 90 天前的记录
psql -U rag_user -d rag_db << EOF
DELETE FROM learning_improvements WHERE created_at < NOW() - INTERVAL '90 days';
DELETE FROM learning_signals WHERE created_at < NOW() - INTERVAL '30 days';
DELETE FROM learning_problems WHERE status = 'closed' AND updated_at < NOW() - INTERVAL '60 days';
VACUUM ANALYZE;
EOF
```

### 重置学习系统

```bash
# 完全重置 (清空所有数据)
psql -U rag_user -d rag_db << EOF
DELETE FROM learning_improvements;
DELETE FROM learning_signals;
DELETE FROM learning_problems;
DELETE FROM learning_root_causes;
DELETE FROM learning_strategies;
EOF

# 重启服务
./stop-all.sh && ./start-all.sh local
```

### 性能分析

```bash
# 收集性能数据
python tests/performance/baseline_test.py -v

# 生成性能报告
python tests/performance/generate_report.py > PERFORMANCE_ANALYSIS.txt

# 查看报告
cat PERFORMANCE_ANALYSIS.txt
```

---

## 📞 获取帮助

**检查清单**:
- ✅ 所有服务是否运行? `ps aux | grep -E "python|node|gateway"`
- ✅ 数据库是否可访问? `psql -U rag_user -d rag_db -c "SELECT 1;"`
- ✅ API 是否响应? `curl -s http://localhost:8080/api/v1/learning/status`
- ✅ 前端是否加载? 打开 http://localhost:5173/learning

**日志文件**:
- `logs/retrieval-service.log` - 主要的 Python 后端日志
- `logs/gateway.log` - Go Gateway 日志
- `logs/server.log` - Node 后端日志

**联系方式**:
- 创建 Issue: [GitHub Issues](https://github.com/CHINGBOH/RAG26/issues)
- 查看文档: [完整文档合集](ISSUE_96_COMPLETE_DOCUMENTATION.md)
- API 参考: [API_REFERENCE_LEARNING.md](API_REFERENCE_LEARNING.md)

---

**版本历史**:
- v1.0 (2025-05-05) - 初始版本，覆盖 6 个常见问题

**相关文档**:
- [快速指南](QUICK_START_LEARNING.md)
- [API 参考](API_REFERENCE_LEARNING.md)
- [触发机制详解](LAYER2_TRIGGERS_GUIDE.md)

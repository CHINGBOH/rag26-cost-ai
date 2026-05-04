# 学习系统监控看板 - 快速开始指南

## 🚀 快速部署（5分钟）

### 1. 启动后端服务
```bash
cd src/backend/retrieval-service
python -m uvicorn main:app --host 0.0.0.0 --port 8002 --reload
```

### 2. 启动前端开发服务器
```bash
cd src/frontend/web
npm run dev
```

### 3. 访问应用
打开浏览器访问: **http://localhost:5173**

### 4. 查看看板
- 自动打开 Learning Page
- 默认显示 Dashboard 看板 (📊 监控看板 Tab)

---

## 📊 看板功能一览

| 功能 | 描述 | 位置 |
|------|------|------|
| 系统健康度 | 0-100 分数，颜色编码（绿/黄/红） | 顶部卡片 |
| 关键指标 | 待审核数、最后运行时间、系统状态 | 3 列网格 |
| 告警面板 | Critical/Warning 级别告警 | 中间部分 |
| 改进趋势 | 30天历史数据折线图 | 下方图表 |
| 最近事件 | 应用、验证、撤销的修复历史 | 底部列表 |

---

## 🔌 API 端点

```
GET /api/v1/learning/dashboard
```

### 响应示例
```json
{
  "health": {
    "status": "good",
    "score": 85,
    "last_check": 1714898730000
  },
  "key_metrics": {
    "last_run": 1714898730000,
    "next_run": null,
    "running": false,
    "pending_approvals": 3
  },
  "improvement_trend": [
    {
      "date": "2026-05-05",
      "rate": 0.75,
      "problems": 3,
      "fixed": 2
    }
  ],
  "alerts": [
    {
      "severity": "warning",
      "message": "3 patches pending human review",
      "created_at": 1714898730000,
      "acknowledged": false
    }
  ],
  "recent_events": [
    {
      "timestamp": 1714898730000,
      "route": "/api/search",
      "description": "Applied fix for navigator_dict",
      "status": "verified"
    }
  ]
}
```

---

## 🧪 运行测试

### 后端 API 测试
```bash
python tests/test_dashboard_api.py
```

**测试项目:**
- ✅ 端点可达性
- ✅ 响应状态码 (200)
- ✅ 响应结构完整性
- ✅ 数据类型验证
- ✅ 健康度分数范围 (0-100)

### 前端集成测试
```bash
bash tests/test_dashboard_frontend_integration.sh
```

**测试项目:**
- ✅ 后端连接
- ✅ API 端点可达性
- ✅ 响应字段完整性

---

## 📱 响应式设计

看板在所有设备上完美适配:

- **桌面** (> 768px): 完整布局，多列网格，完整图表
- **平板** (481-768px): 简化布局，单列网格，紧凑图表
- **手机** (≤ 480px): 堆叠布局，单列设计，简化事件列表

---

## 📈 健康度计算公式

```
Health Score = (
  run_success_rate × 0.3 × 100 +      # 30%
  fix_effectiveness × 0.3 +            # 30%
  approval_health × 0.2 +              # 20%
  80 × 0.2                             # 20% (固定)
)
```

### 状态映射

| 分数范围 | 状态 | 图标 | 颜色 |
|---------|------|------|------|
| 70-100 | Good | ✅ | 绿色 |
| 50-69 | Warning | ⚠️ | 黄色 |
| 0-49 | Critical | 🚨 | 红色 |

---

## 🚨 告警规则

看板会自动生成以下告警:

### 1. 系统健康度告警
- **触发条件**: health_score < 60
- **Critical**: health_score < 40
- **Warning**: health_score 40-60

### 2. 待审核堆积告警
- **触发条件**: pending_count > 5
- **级别**: Warning
- **消息**: "N patches pending human review"

### 3. 最近运行失败告警
- **触发条件**: 最近 24h 有失败运行
- **级别**: Warning
- **消息**: "N learning runs failed in last 24h"

---

## 🔄 自动刷新

看板每 **30 秒** 自动刷新一次数据:

```typescript
useEffect(() => {
  const interval = setInterval(fetchDashboard, 30000);
  return () => clearInterval(interval);
}, []);
```

可以点击 "刷新" 按钮手动刷新。

---

## 💡 使用建议

1. **监控系统健康**: 定期检查健康度分数，及时处理告警
2. **趋势分析**: 查看 30 天改进趋势，评估系统改进效果
3. **审核管理**: 关注待审核数，及时批准或拒绝修复建议
4. **事件追踪**: 查看最近事件，了解系统最新动态

---

## 🐛 故障排查

### 看板无法加载数据？

1. 确认后端服务正在运行:
   ```bash
   curl http://localhost:8002/health
   ```

2. 检查 API 端点是否可用:
   ```bash
   curl http://localhost:8002/api/v1/learning/dashboard
   ```

3. 查看浏览器控制台错误信息

### 图表显示异常？

- 检查是否有历史数据 (improvement_trend 需要数据)
- 验证日期格式是否正确

### 性能问题？

- 后端使用了优化的 SQL 查询，应该很快
- 如果仍然缓慢，检查数据库索引:
  ```sql
  CREATE INDEX IF NOT EXISTS idx_improvement_events_verified_at 
  ON improvement_events(verified_at);
  ```

---

## 📚 相关文件

| 文件 | 说明 |
|------|------|
| `src/backend/retrieval-service/app/api.py` | 后端 API 实现 |
| `src/frontend/web/src/components/learning/DashboardPanel.tsx` | 前端组件 |
| `src/frontend/web/src/components/learning/DashboardPanel.css` | 样式表 |
| `src/frontend/web/src/pages/LearningPage.tsx` | LearningPage 集成 |
| `tests/test_dashboard_api.py` | 后端测试 |
| `tests/test_dashboard_frontend_integration.sh` | 前端测试 |
| `ISSUE_96_LAYER3_MONITORING_COMPLETION.md` | 完整文档 |

---

## 📞 支持

遇到问题？检查:
1. 完整实现文档: `ISSUE_96_LAYER3_MONITORING_COMPLETION.md`
2. 运行测试验证功能: `test_dashboard_api.py`
3. 查看 API 响应格式

---

**最后更新**: 2026-05-05
**版本**: 1.0.0 (完成)
**状态**: ✅ 生产就绪


# 快速启动指南 - Layer 1 + Layer 2 集成

## 🎯 一键验证集成

```bash
# 进入项目根目录
cd /home/l/rag-dashboard

# 验证 API 端点
python src/backend/retrieval-service/app/api.py

# 运行集成测试
cd src/backend/retrieval-service
pytest tests/test_integration_layer1_layer2.py -v
```

## 📦 启动整个堆栈

### 方式 1：使用 Docker Compose（推荐）
```bash
docker-compose up -d
```

### 方式 2：手动启动各个服务

#### 1️⃣ 启动 PostgreSQL 数据库（如果还未启动）
```bash
docker run -d \
  --name postgres-rag \
  -e POSTGRES_USER=rag_user \
  -e POSTGRES_PASSWORD=rag_password \
  -e POSTGRES_DB=rag_db \
  -p 5432:5432 \
  postgres:16
```

#### 2️⃣ 启动 retrieval-service（端口 8002）
```bash
cd src/backend/retrieval-service
python -m uvicorn main:app --host 0.0.0.0 --port 8002 --reload
```

#### 3️⃣ 启动 Go Gateway（端口 8080）
```bash
cd src/backend/go-services
go build -o gateway cmd/gateway/main.go
PORT=8080 ./gateway
```

#### 4️⃣ 启动前端（端口 5173）
```bash
cd src/frontend/web
npm install
npm run dev
```

## 🌐 访问应用

- **前端**：http://localhost:5173
- **API Gateway**：http://localhost:8080
- **Retrieval Service**：http://localhost:8002
- **学习看板**：http://localhost:5173/learning

## 📡 信号监控面板位置

1. 登录后进入应用
2. 导航到：**自学习看板** 页面
3. 点击标签页：**📡 信号监控**

## 🧪 测试 API 端点

```bash
# 获取最新信号数据
curl -s http://localhost:8080/api/v1/learning/signals | jq .

# 获取信号摘要
curl -s http://localhost:8080/api/v1/learning/signals-summary | jq .

# 带限制参数
curl -s "http://localhost:8080/api/v1/learning/signals?limit=50" | jq .
```

## 📋 预期响应示例

### GET /api/v1/learning/signals
```json
{
  "timestamp": 1714898730000,
  "feedback_signals": [...],
  "failure_signals": [...],
  "repeat_signals": [...],
  "violation_signals": [...],
  "topo_signals": [...],
  "total_count": 8,
  "severity_score": 41.5,
  "collection_time_ms": 5.8
}
```

### GET /api/v1/learning/signals-summary
```json
{
  "last_collection": 1714898730000,
  "next_scheduled": 1714898790000,
  "signal_counts": {
    "feedback": 7,
    "failures": 1,
    "repeats": 0,
    "violations": 0,
    "topo": 0
  },
  "severity_trend": [41.5],
  "health_status": "good"
}
```

## ✅ 验收检查清单

在启动后，验证以下内容：

- [ ] 前端可以访问（http://localhost:5173）
- [ ] 学习看板页面加载正常
- [ ] 信号监控 Tab 可见
- [ ] API 端点返回数据（使用上述 curl 命令）
- [ ] 时间戳格式正确（毫秒）
- [ ] 健康指示器显示正确的状态

## 🐛 故障排除

### 数据库连接失败
```
错误：connection to server at "localhost" (127.0.0.1), port 5432 failed
解决：确保 PostgreSQL 已启动，或使用上面的 Docker 命令启动它
```

### API 端点返回 404
```
错误：Route not found
解决：确保 Go Gateway 正在运行，并且路由已正确映射
```

### 前端无法连接到 API
```
错误：CORS 或连接错误
解决：检查 vite.config.ts 中的代理配置，确保 API_BASE_URL 正确
```

## 📚 相关文档

- [完整集成报告](./LAYER1_LAYER2_INTEGRATION_REPORT.md)
- [信号采集器文档](./src/backend/retrieval-service/app/agent/signal_collector.py)
- [API 定义](./src/backend/retrieval-service/app/api.py)

## 🎉 完成！

现在您的系统已具备完整的信号采集和监控功能。享受使用吧！

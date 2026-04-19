# Go网关服务

RAG系统的统一API网关，提供反向代理、负载均衡、监控和认证功能。

## 功能特性

- 🔀 **反向代理**：代理到Node.js后端(3001)、Python后端(8000)、OCR服务(8001)
- 🔒 **认证中间件**：请求ID生成、CORS支持、请求日志
- 📊 **监控指标**：Prometheus指标端点 (`/metrics`)
- 🏥 **健康检查**：聚合所有后端服务的健康状态 (`/health`)
- 🚦 **智能路由**：基于路径前缀的路由映射
- 📝 **结构化日志**：请求追踪和性能监控

## 快速开始

### 前提条件

- Go 1.21+ ([安装指南](https://go.dev/doc/install))
- Docker (可选，用于容器化部署)

### 本地运行

1. **安装依赖**：
   ```bash
   cd src/backend/go-services
   go mod download
   ```

2. **构建并运行**：
   ```bash
   ./start_gateway.sh
   ```

3. **或手动运行**：
   ```bash
   go run cmd/gateway/main.go
   ```

### Docker运行

```bash
# 构建镜像
docker build -f deployments/Dockerfile.gateway -t rag-gateway .

# 运行容器
docker run -p 8080:8080 --name rag-gateway rag-gateway
```

### 验证安装

```bash
# 健康检查
curl http://localhost:8080/health

# 指标端点
curl http://localhost:8080/metrics

# 测试代理 (Node.js后端)
curl http://localhost:8080/api/sessions

# 测试代理 (Python后端)
curl http://localhost:8080/api/search -X POST -H "Content-Type: application/json" -d '{"query": "test"}'
```

## 路由映射

| 路径前缀 | 目标服务 | 端口 | 说明 |
|---------|---------|------|------|
| `/api/sessions`, `/api/activity`, `/api/auth`, `/api/llm/chat` | Node.js后端 | 3001 | 会话管理、用户认证、LLM聊天 |
| `/api/search`, `/api/documents`, `/api/v1/rerank`, `/api/v1/evaluate` | Python后端 | 8000 | 检索、文档处理、重排序 |
| `/api/ocr` | OCR服务 | 8001 | OCR文档处理 |
| `/health` | 网关自身 | 8080 | 聚合健康检查 |
| `/metrics` | 网关自身 | 8080 | Prometheus指标 |

## 配置

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | 8080 | 网关监听端口 |
| `DEBUG` | false | 启用调试模式 |
| `GOPROXY` | https://proxy.golang.org,direct | Go模块代理 |

### 服务配置

在 `cmd/gateway/main.go` 中修改 `services` 映射：

```go
var services = map[string]ServiceConfig{
    "nodejs": {
        Name:    "nodejs-backend",
        URL:     "http://localhost:3001",  // 修改为目标地址
        Health:  "http://localhost:3001/health",
        Timeout: 30,
    },
    // ...
}
```

## 监控

网关提供以下监控端点：

- **`/metrics`**: Prometheus格式的指标
  - `gateway_requests_total`: 总请求数
  - `gateway_request_duration_seconds`: 请求延迟直方图

## 部署

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rag-gateway
spec:
  replicas: 2
  selector:
    matchLabels:
      app: rag-gateway
  template:
    metadata:
      labels:
        app: rag-gateway
    spec:
      containers:
      - name: gateway
        image: rag-gateway:latest
        ports:
        - containerPort: 8080
        env:
        - name: PORT
          value: "8080"
```

### Docker Compose

```bash
docker-compose -f deployments/docker-compose.gateway.yml up
```

## 开发

### 项目结构

```
src/backend/go-services/
├── cmd/gateway/main.go     # 网关主程序
├── internal/              # 内部包
│   ├── proxy/            # 代理逻辑
│   └── middleware/       # 中间件
├── proto/                # Protobuf定义
├── config/               # 配置文件
├── deployments/          # 部署配置
│   ├── Dockerfile.gateway
│   └── docker-compose.gateway.yml
├── go.mod               # Go模块定义
├── go.sum               # 依赖校验
└── README.md            # 本文档
```

### 添加新路由

1. 在 `getRouteMapping()` 函数中添加路由映射：
```go
"/api/new-endpoint": "target-service",
```

2. 确保目标服务在 `services` 映射中定义

### 添加新中间件

在 `internal/middleware/` 中创建新的中间件，并在 `main.go` 中注册：

```go
router.Use(customMiddleware())
```

## 故障排除

### 依赖下载失败

设置中国镜像代理：
```bash
export GOPROXY=https://goproxy.cn,direct
go mod download
```

### 服务连接失败

检查后端服务是否运行：
```bash
curl http://localhost:3001/health
curl http://localhost:8000/health
curl http://localhost:8001/health
```

### 构建失败

确保Go版本 >= 1.21：
```bash
go version
```

## 下一步计划

1. ✅ 阶段2: 基础网关实现
2. ➡️ 阶段3: WebSocket网关迁移
3. 阶段4: 会话服务迁移到Go
4. 阶段5: Python服务拆分
5. 阶段6: Go编排器实现

## 许可证

MIT License
# RAG Dashboard - 企业级检索增强生成系统

<div align="center">

![RAG System](https://img.shields.io/badge/RAG-Enterprise-blue)
![Python](https://img.shields.io/badge/Python-3.8+-green)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109.0-red)
![License](https://img.shields.io/badge/License-MIT-yellow)

**完整的RAG系统解决方案 | embedding + 四库 + rerank精排召回 + 延迟高并发**

[快速开始](#快速开始) • [功能特性](#功能特性) • [架构设计](#架构设计) • [部署指南](#部署指南) • [API文档](#api文档)

</div>

---

## 📖 项目简介

RAG Dashboard 是一个功能完整的企业级检索增强生成（RAG）系统，采用"embedding + 四库 + rerank精排召回 + 延迟高并发"架构，提供高性能、可扩展的智能检索和生成能力。

### 核心特性

- ✨ **四库整合**: Qdrant + PostgreSQL + 知识库 + 知识图谱
- 🚀 **高性能**: 支持高并发、低延迟的查询处理
- 🤖 **多模型支持**: Embedding、Rerank、LLM多种模型
- 🔍 **智能检索**: 向量搜索 + 关键词搜索 + 图谱查询
- 🎯 **精确重排**: 多特征融合的Rerank算法
- 📊 **完整监控**: 系统统计、性能监控、日志追踪
- 🛠️ **易部署**: 一键启动脚本，自动化部署
- 📚 **完整文档**: 详细的架构设计和部署指南

---

## 🎯 功能特性

### 核心四库

| 数据库 | 用途 | 特性 |
|--------|------|------|
| **Qdrant** | 向量数据库 | 语义搜索、HNSW索引、批量查询 |
| **PostgreSQL** | 结构化数据库 | 元数据管理、关系存储、全文搜索 |
| **知识库** | 文档管理 | PDF管理、OCR结果、处理状态 |
| **Neo4j** | 知识图谱 | 实体关系、复杂查询、图算法 |

### 核心服务

- **Embedding服务**: 文本向量化，支持多种模型（sentence-transformers）
- **Rerank服务**: 精确重排，多特征融合、多样性优化
- **LLM服务**: 大语言模型推理，支持llama.cpp和vLLM
- **四库整合服务**: 统一管理四库，多路召回、结果合并
- **统一模型调用器**: API调用接口，支持本地和云端模型

### 支撑工具

- **Elasticsearch**: 全文搜索引擎
- **Redis**: 缓存和消息队列
- **MinIO**: 对象存储
- **RabbitMQ**: 任务队列

---

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    RAG系统架构                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Qdrant张量库  │  │ PostgreSQL   │  │   知识库     │  │
│  │ (向量存储)   │  │  (结构化数据) │  │ (文档管理)   │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │             知识图谱库 (Neo4j)                         │  │
│  │             (知识关系存储)                           │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              核心服务层                               │  │
│  │  Embedding | Rerank | LLM | 四库整合 | 高并发处理      │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              FastAPI应用层                            │  │
│  │              RESTful API + Web UI                     │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

详细的架构设计请参考 [RAG_ARCHITECTURE_DESIGN.md](RAG_ARCHITECTURE_DESIGN.md)

---

## 🚀 快速开始

### 前置要求

- **Docker**: 20.10+
- **Docker Compose**: 1.29+ (可选)
- **Python**: 3.8+
- **内存**: 16GB+ (推荐32GB)
- **存储**: 100GB+ SSD

### 一键启动

```bash
# 1. 克隆项目
git clone <repository_url>
cd rag-dashboard

# 2. 启动服务
chmod +x start_rag.sh
./start_rag.sh

# 3. 访问API文档
open http://localhost:8000/docs
```

### 验证安装

```bash
# 检查服务状态
curl http://localhost:8000/health

# 测试搜索
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "深圳市建设工程计价费率标准",
    "top_k": 10
  }'
```

### 停止服务

```bash
./stop_rag.sh
```

---

## 📡 API文档

### 核心API端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/api/v1/search` | POST | 四库搜索 |
| `/api/v1/embedding` | POST | 文档向量化 |
| `/api/v1/rerank` | POST | 结果重排 |
| `/api/v1/llm/generate` | POST | LLM生成 |
| `/api/v1/documents/process` | POST | 文档处理 |
| `/api/v1/stats` | GET | 系统统计 |
| `/api/v1/models` | GET | 模型信息 |

详细的API文档请访问: http://localhost:8000/docs

### 快速示例

#### 1. 四库搜索

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "深圳市建设工程计价费率标准",
    "top_k": 10,
    "use_rerank": true,
    "use_llm": false
  }'
```

#### 2. 文档向量化

```bash
curl -X POST http://localhost:8000/api/v1/embedding \
  -H "Content-Type: application/json" \
  -d '{
    "texts": ["深圳市建设工程计价费率标准"],
    "model_name": "default",
    "normalize": true
  }'
```

#### 3. LLM生成

```bash
curl -X POST http://localhost:8000/api/v1/llm/generate \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "什么是计价费率？"}
    ],
    "max_tokens": 512,
    "temperature": 0.7
  }'
```

---

## 📊 性能指标

| 指标 | 数值 |
|------|------|
| 文档处理速度 | 10-20 docs/min |
| 向量化速度 | 100-200 texts/sec |
| 查询响应时间 | 500ms - 2s |
| 并发处理能力 | 100+ req/s |
| 向量搜索延迟 | 50-200ms |

---

## 📁 项目结构

```
rag-dashboard/
├── data/                           # 数据目录
│   ├── knowledge_base/            # 知识库
│   │   ├── raw_pdfs/             # 原始PDF
│   │   ├── ocr_results/          # OCR结果
│   │   ├── processed/            # 处理后文档
│   │   └── metadata/             # 元数据
│   └── ocr_outputs/              # OCR输出
├── sql/                           # SQL脚本
│   └── init/                     # 初始化脚本
│       └── 01_init_database.sql  # 数据库初始化
├── src/                           # 源代码
│   └── backend/
│       └── python-legacy/
│           ├── services/         # 服务层
│           │   ├── embedding_service.py      # Embedding服务
│           │   ├── four_database_service.py  # 四库整合服务
│           │   ├── rerank_service.py         # Rerank服务
│           │   ├── llm_service.py            # LLM服务
│           │   └── model_caller.py           # 模型调用器
│           └── rag_api_service.py            # FastAPI服务
├── docker-compose.rag.yml        # RAG系统Docker配置
├── requirements.txt              # Python依赖
├── start_rag.sh                  # 启动脚本
├── stop_rag.sh                   # 停止脚本
├── RAG_ARCHITECTURE_DESIGN.md    # 架构设计文档
├── RAG_DEPLOYMENT_GUIDE.md       # 部署指南
├── PROJECT_SUMMARY.md            # 项目总结
├── QUICK_REFERENCE.md            # 快速参考
└── README.md                     # 本文件
```

---

## 🔧 配置说明

### 环境变量

创建 `.env` 文件：

```bash
# Redis配置
REDIS_HOST=localhost
REDIS_PORT=6379

# PostgreSQL配置
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=rag_db
POSTGRES_USER=rag_user
POSTGRES_PASSWORD=rag_password

# Qdrant配置
QDRANT_HOST=localhost
QDRANT_PORT=6333

# Neo4j配置
NEO4J_URI=bolt://neo4j:rag_password@localhost:7687

# API配置
API_HOST=0.0.0.0
API_PORT=8000
```

### 数据库配置

- **PostgreSQL**: 默认端口5432，用户rag_user
- **Qdrant**: 默认端口6333 (HTTP), 6334 (gRPC)
- **Neo4j**: 默认端口7474 (HTTP), 7687 (Bolt)
- **Redis**: 默认端口6379

---

## 📚 文档

- **[架构设计文档](RAG_ARCHITECTURE_DESIGN.md)** - 详细的系统架构设计
- **[部署指南](RAG_DEPLOYMENT_GUIDE.md)** - 完整的部署和配置指南
- **[项目总结](PROJECT_SUMMARY.md)** - 项目开发总结和技术细节
- **[快速参考](QUICK_REFERENCE.md)** - 常用命令和API快速查询

---

## 🐛 故障排查

### 常见问题

#### 1. PostgreSQL连接失败
```bash
# 检查PostgreSQL是否运行
docker ps | grep rag-postgres

# 查看日志
docker logs rag-postgres

# 重启服务
docker restart rag-postgres
```

#### 2. Qdrant连接失败
```bash
# 检查Qdrant是否运行
docker ps | grep rag-qdrant

# 测试连接
curl http://localhost:6333/healthz
```

#### 3. 内存不足
```bash
# 清理Docker缓存
docker system prune -a

# 调整服务内存限制
# 在docker-compose.yml中添加mem_limit配置
```

更多故障排查请参考 [部署指南](RAG_DEPLOYMENT_GUIDE.md)

---

## 🤝 贡献指南

欢迎贡献代码、报告问题、提出建议！

1. Fork项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建Pull Request

### 开发规范

- 使用Black格式化代码
- 遵循PEP 8编码规范
- 添加类型注解
- 编写单元测试

---

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

---

## 📞 技术支持

如有问题，请联系：

- **GitHub Issues**: [项目Issues页面](<repository_url>/issues)
- **Email**: support@example.com
- **文档**: [在线文档](https://docs.example.com)

---

## 🙏 致谢

感谢所有为本项目贡献代码、文档和想法的开发者！

特别感谢以下开源项目：

- [FastAPI](https://fastapi.tiangolo.com/)
- [Qdrant](https://qdrant.tech/)
- [PostgreSQL](https://www.postgresql.org/)
- [Neo4j](https://neo4j.com/)
- [Sentence-Transformers](https://www.sbert.net/)
- [llama.cpp](https://github.com/ggerganov/llama.cpp)
- [vLLM](https://github.com/vllm-project/vllm)

---

## 🎉 总结

RAG Dashboard 提供了一个完整的企业级RAG系统解决方案，包括：

✅ **核心四库**: Qdrant + PostgreSQL + 知识库 + 知识图谱
✅ **支撑工具**: Elasticsearch + Redis + MinIO + RabbitMQ
✅ **核心服务**: Embedding + Rerank + LLM + 四库整合
✅ **高性能**: 支持高并发、低延迟
✅ **易扩展**: 模块化设计，易于扩展
✅ **易部署**: 一键启动，自动化部署
✅ **完整文档**: 详细的架构设计和部署指南

**系统已准备就绪，开始使用吧！🚀**

---

<div align="center">

**如果这个项目对你有帮助，请给它一个 ⭐️**

Made with ❤️ by RAG Team

</div>
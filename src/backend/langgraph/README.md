# LangGraph 集成文档

## 概述

LangGraph 是一个用于构建基于状态的 LLM 应用程序的框架，专为复杂的多步骤工作流设计。本文档介绍如何在 RAG 系统中集成和使用 LangGraph。

## 安装

### 环境要求
- Python 3.10+
- pip 21.0+
- 已安装的依赖：
  - langgraph
  - langchain
  - langchain-core
  - langchain-openai

### 安装命令

```bash
# 激活 py310 环境
source /home/l/miniconda3/bin/activate py310

# 安装依赖
pip install langgraph langchain langchain-core langchain-openai
```

## 目录结构

```
src/backend/langgraph/
├── config.py        # LangGraph 配置文件
├── example.py       # LangGraph 示例代码
└── README.md        # 本文档
```

## 配置

### 环境变量

| 环境变量 | 描述 | 默认值 |
|---------|------|--------|
| LANGGRAPH_CHECKPOINT_TYPE | 检查点类型 (in_memory, sqlite, redis) | in_memory |
| LANGGRAPH_CHECKPOINT_PATH | 检查点存储路径 | ./langgraph_checkpoints |
| LANGGRAPH_MAX_WORKERS | 最大工作线程数 | 4 |
| LANGGRAPH_MONITORING | 是否启用监控 | false |
| LLM_API_BASE | LLM API 基础 URL | http://localhost:8080 |
| LLM_API_KEY | LLM API 密钥 | empty |
| LLM_MODEL | LLM 模型名称 | DeepSeek-R1-Distill-Qwen-14B-Q4_K_M.gguf |
| LLM_TEMPERATURE | LLM 温度参数 | 0.7 |
| LLM_MAX_TOKENS | LLM 最大 tokens | 1024 |
| VECTOR_SEARCH_ENDPOINT | 向量搜索服务地址 | http://localhost:6333 |
| GRAPH_SEARCH_ENDPOINT | 图搜索服务地址 | bolt://localhost:7687 |
| NEO4J_USER | Neo4j 用户名 | neo4j |
| NEO4J_PASSWORD | Neo4j 密码 | password |
| KEYWORD_SEARCH_ENDPOINT | 关键词搜索服务地址 | http://localhost:9200 |

## 使用示例

### 运行示例

```bash
# 激活环境
source /home/l/miniconda3/bin/activate py310

# 运行示例
python src/backend/langgraph/example.py
```

### 预期输出

```
🚀 运行 RAG 示例: 什么是 LangGraph？
🔍 检索: 什么是 LangGraph？
🤖 生成回答
✅ 验证回答

📊 结果:
查询: 什么是 LangGraph？
思考: 根据检索到的内容，我需要生成一个全面的回答...
回答: 根据检索到的信息，关于 '什么是 LangGraph？' 的回答是：这是一个示例回答。
来源: ['文档1', '文档2']
```

## 核心功能

### 1. 状态管理

LangGraph 使用状态图管理复杂的工作流，每个节点处理特定的任务：

- **检索节点**：从多个数据源获取相关信息
- **生成节点**：使用 LLM 生成回答
- **验证节点**：验证回答的质量和完整性

### 2. 检查点系统

支持多种检查点存储方式：
- **内存存储**：适合开发和测试
- **SQLite**：适合小规模部署
- **Redis**：适合大规模生产环境

### 3. 并发处理

通过配置最大工作线程数，优化多任务处理效率。

## 与现有 RAG 系统集成

### 集成方式

1. **替换现有 Agent 系统**：使用 LangGraph 替代现有的 ReAct Agent
2. **作为补充组件**：在现有系统基础上添加 LangGraph 工作流
3. **混合模式**：结合两者优势，根据任务类型选择合适的处理方式

### 集成步骤

1. 配置 LangGraph 连接到现有的 LLM 服务
2. 配置工具连接到现有的向量搜索、图搜索等服务
3. 定义适合业务场景的工作流节点
4. 部署并测试集成效果

## 高级功能

### 1. 条件分支

```python
# 示例：根据检索结果决定下一步
workflow.add_conditional_edges(
    "retrieve",
    lambda state: "generate" if state.contexts else "fallback"
)
```

### 2. 循环处理

```python
# 示例：实现迭代检索-生成
workflow.add_edge("validate", "retrieve")  # 形成循环
```

### 3. 并行处理

```python
# 示例：并行执行多个检索
workflow.add_node("parallel_retrieve", parallel_retrieve_function)
```

## 故障排查

### 常见问题

1. **LangGraph 安装失败**
   - 确保 Python 版本 >= 3.10
   - 检查网络连接
   - 尝试使用 `--no-cache-dir` 选项

2. **LLM 连接失败**
   - 确保 llama-server 正在运行
   - 检查 LLM_API_BASE 配置是否正确

3. **工具连接失败**
   - 确保各服务（Qdrant、Neo4j 等）正在运行
   - 检查相关环境变量配置

### 日志和监控

启用监控后，LangGraph 会记录工作流执行情况：

```bash
# 启用监控
export LANGGRAPH_MONITORING=true
export LANGGRAPH_MONITORING_ENDPOINT="http://localhost:9090"
```

## 性能优化

1. **检查点优化**：生产环境建议使用 Redis 检查点
2. **并发优化**：根据硬件配置调整 `LANGGRAPH_MAX_WORKERS`
3. **缓存策略**：对频繁访问的结果进行缓存
4. **批处理**：对批量请求使用并行处理

## 部署建议

### 开发环境
- 使用内存检查点
- 启用详细日志
- 较低的并发设置

### 生产环境
- 使用 Redis 检查点
- 启用监控
- 适当的并发设置
- 负载均衡

## 版本兼容性

| LangGraph 版本 | Python 版本 | 推荐环境 |
|---------------|------------|----------|
| 1.1.x | 3.10+ | py310 环境 |
| 1.0.x | 3.9+ | py39 环境 |

## 参考资源

- [LangGraph 官方文档](https://langchain-ai.github.io/langgraph/)
- [LangChain 文档](https://python.langchain.com/docs/get_started/introduction)
- [RAG 系统设计指南](https://www.langchain.com/use-cases/retrieval-augmented-generation)

## 联系方式

如有问题，请联系系统管理员或查看相关文档。
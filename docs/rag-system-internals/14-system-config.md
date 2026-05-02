# 系统配置参数说明

## 检索核心参数

系统的检索行为由几个核心参数控制。top_k 决定每次检索返回多少候选段落，默认 8，范围 1-20；增大 top_k 能提高召回率但增加 LLM 上下文负担。score_threshold 是相关性阈值，默认 0.60，低于此分数的段落被过滤，设置过高会导致有效内容被误滤，设置过低会引入噪声。search_mode 控制检索模式：hybrid（向量+全文混合，默认推荐）、dense（纯向量语义）、keyword（纯关键词）、bm25（BM25 稀疏检索）。max_iterations 控制 Agent 最大推理循环次数，默认 3。

## 图书馆模式的固定配置

企业知识库（图书馆模式）对用户隐藏所有参数，使用经过测试的最优固定值：top_k=8、score_threshold=0.60、search_mode=hybrid、max_iterations=3、model=deepseek-v4-flash。这些参数在多轮测试中表现最稳定，平衡了准确性和响应速度。普通用户不需要了解这些参数，系统自动用最佳配置工作。

## LLM 配置参数

与 LLM 相关的配置：model 指定使用的 LLM 模型（当前为 deepseek-v4-flash，100 万 token 上下文，推理速度快）；llm_route 指定路由方式（deepseek/auto/local），auto 模式会根据问题复杂度自动选择合适模型；temperature 控制回答的随机性（0.5 适合事实查询，0.7 适合需要分析综合的问题）；stream_output 控制是否流式输出（默认 True，用户能实时看到答案逐字输出）。

## 嵌入服务配置

嵌入服务（TEI）配置：TEI_URL 默认 http://localhost:8003，指向 BGE-M3 模型推理服务；EMBEDDING_BACKEND 可以设置为 tei（使用 TEI 服务，推荐）或 local（直接加载模型到 Python 进程，内存占用大）；向量维度固定为 1024（由模型决定，不可改变）；批处理大小默认 32（批量嵌入时每批最多处理 32 个文本块，平衡速度和内存）。

## 数据库连接配置

各数据库的连接参数通过环境变量配置，从 .env 文件加载（位于项目根目录，不提交到 git）。PostgreSQL：PG_HOST、PG_PORT（默认 5432）、PG_DB（默认 rag_db）、PG_USER（默认 rag_user）、POSTGRES_PASSWORD。Qdrant：QDRANT_URL（默认 http://localhost:6333）。Elasticsearch：ES_URL（默认 http://localhost:9200）。Neo4j：NEO4J_URI（默认 bolt://localhost:7687）、NEO4J_USER、NEO4J_PASSWORD。LLM API：LLM_BASE_URL（如 https://api.deepseek.com/v1）、OPENAI_API_KEY（DeepSeek API Key）。

## 性能调优指南

针对不同使用场景的参数调优建议。快速查询场景（追求速度）：降低 top_k 到 5，提高 score_threshold 到 0.65，限制 max_iterations 为 2。深度分析场景（追求全面）：提高 top_k 到 12-15，降低 score_threshold 到 0.55，增加 max_iterations 到 5。精确查询场景（精确术语）：search_mode 设为 keyword 或 bm25，top_k 设为 5-8，score_threshold 维持默认 0.60。图书馆模式下这些参数由系统固定，用户无法调整。

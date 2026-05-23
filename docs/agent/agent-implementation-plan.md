# Agentic RAG 四库检索系统 - 详细实施计划

## 版本信息
- 版本: 1.0
- 日期: 2026-04-18
- 状态: 初稿

---

## 一、系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Node.js (API层/管家)                      │
│  - HTTP接口                                                  │
│  - 四库连接管理                                              │
│  - 调用Python Agent服务                                      │
└─────────────────────────────────────────────────────────────┘
                            ↓ HTTP/gRPC
┌─────────────────────────────────────────────────────────────┐
│               Python (LLM逻辑层/Agent核心)                   │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              LangChain / LangGraph Agent             │    │
│  │  ┌─────────┐  ┌──────────┐  ┌─────────────────┐    │    │
│  │  │ Query   │→│ Retrieval │→│  Verification   │    │    │
│  │  │ Planner │  │ (四库)   │  │  Loop          │    │    │
│  │  └─────────┘  └──────────┘  └─────────────────┘    │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、技术选型

### 2.1 核心框架

| 组件 | 推荐方案 | 版本 | 说明 |
|-----|---------|------|------|
| **Agent框架** | LangGraph | 0.3.x | 2026年主流，比LangChain更灵活 |
| **LLM调用** | langchain-openai / langchain-deepseek | latest | 支持DeepSeek |
| **结构化输出** | with_structured_output() | - | 强制输出schema |
| **工具定义** | @tool decorator (Pydantic) | - | 类型安全 |

### 2.2 四库连接

| 库 | Python SDK | 说明 |
|---|-----------|------|
| Qdrant | qdrant-client | 向量检索 |
| Elasticsearch | elasticsearch-py | 关键词检索 |
| Neo4j | neo4j-driver | 知识图谱 |
| PostgreSQL | asyncpg / psycopg2 | 结构化数据 |

### 2.3 辅助库

| 用途 | 库 |
|-----|---|
| Retry/容错 | tenacity, backoff |
| Embedding | langchain-embeddings, sentence-transformers |
| 计算器 | sympy (符号计算) |

---

## 三、文件结构设计

```
src/backend/python-legacy/agent/
├── __init__.py
├── main.py                      # 入口，FastAPI服务
├── config.py                    # 配置管理
│
├── core/                        # 核心模块
│   ├── __init__.py
│   ├── llm.py                   # LLM初始化
│   ├── prompt.py                 # Prompt模板
│   └── output_schema.py          # 结构化输出Schema
│
├── tools/                       # 工具定义
│   ├── __init__.py
│   ├── base.py                   # 工具基类
│   ├── vector_tool.py            # Qdrant检索
│   ├── keyword_tool.py           # ES检索
│   ├── graph_tool.py            # Neo4j检索
│   ├── struct_tool.py           # PostgreSQL查询
│   └── calculator_tool.py       # 计算器
│
├── agent/                       # Agent定义
│   ├── __init__.py
│   ├── react_agent.py            # ReAct Agent
│   ├── query_planner.py          # 查询规划
│   └── verifier.py               # 验证器
│
└── utils/                       # 工具函数
    ├── __init__.py
    ├── retry.py                  # 重试机制
    └── response.py                # 响应格式化
```

**文件数量**: 约 15 个 .py 文件

---

## 四、各模块详细设计

### 4.1 配置管理 (config.py)

```python
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # LLM配置
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # Agent配置
    max_iterations: int = 10
    max_retries: int = 3
    temperature: float = 0.1

    # 四库配置
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "document_chunks"

    es_host: str = "localhost"
    es_port: int = 9200

    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str

    pg_host: str
    pg_port: int
    pg_db: str
    pg_user: str
    pg_password: str

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings():
    return Settings()
```

**需要安装**: `pydantic-settings`

---

### 4.2 LLM初始化 (core/llm.py)

```python
from langchain_openai import ChatOpenAI
from langchain_deepseek import ChatDeepSeek
from config import get_settings

def create_llm(model_name: str = "deepseek-chat"):
    """创建LLM实例"""
    settings = get_settings()

    if model_name == "deepseek-chat":
        return ChatDeepSeek(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            temperature=settings.temperature,
        )
    else:
        return ChatOpenAI(model=model_name, temperature=settings.temperature)
```

**需要安装**: `langchain-openai`, `langchain-deepseek`

---

### 4.3 结构化输出Schema (core/output_schema.py)

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class IndexEntry(BaseModel):
    """索引条目 - 强制输出"""
    chunk_id: str = Field(description="文档块唯一ID")
    doc_id: str = Field(description="文档ID")
    page_number: int = Field(description="页码")
    source_db: str = Field(description="来源库: qdrant/es/neo4j/pg")

class CalculationStep(BaseModel):
    """计算步骤"""
    formula: str = Field(description="计算公式")
    inputs: dict = Field(description="输入参数")
    result: float = Field(description="计算结果")
    explanation: str = Field(description="步骤说明")

class AgentResponse(BaseModel):
    """Agent最终输出"""
    answer: str = Field(description="最终答案")
    indices: List[IndexEntry] = Field(description="引用的索引条目列表")
    calculations: Optional[List[CalculationStep]] = Field(
        default=None,
        description="计算过程（如果有）"
    )
    confidence: float = Field(description="置信度 0-1")
    reasoning: str = Field(description="推理过程简述")

class ToolSelection(BaseModel):
    """工具选择决策"""
    tool_name: str = Field(description="选择的工具: vector_search/keyword_search/knowledge_graph_search/structured_query/calculator")
    reasoning: str = Field(description="选择理由")
    input_params: dict = Field(description="工具输入参数")
```

**关键点**: 每个结果必须包含 `IndexEntry`，强制溯源！

---

### 4.4 工具定义基类 (tools/base.py)

```python
from abc import ABC, abstractmethod
from typing import Any, Dict
from pydantic import BaseModel

class ToolInput(BaseModel, ABC):
    """工具输入基类"""
    pass

class ToolResult(BaseModel):
    """工具输出基类"""
    success: bool
    content: str
    metadata: Dict[str, Any] = {}
    error: Optional[str] = None

class BaseTool(ABC):
    """工具基类"""

    name: str  # 工具名称
    description: str  # 工具描述（给LLM看）
    input_schema: type[ToolInput]  # 输入Schema

    @abstractmethod
    async def execute(self, tool_input: ToolInput) -> ToolResult:
        """执行工具"""
        pass

    def to_langchain_tool(self):
        """转换为LangChain工具"""
        from langchain_core.tools import tool

        @tool(args_schema=self.input_schema)
        def wrapper(**kwargs):
            return self.execute(self.input_schema(**kwargs))

        wrapper.name = self.name
        wrapper.description = self.description
        return wrapper
```

---

### 4.5 向量检索工具 (tools/vector_tool.py)

```python
from typing import Optional
from pydantic import Field
from qdrant_client import QdrantClient
from tools.base import BaseTool, ToolInput, ToolResult

class VectorSearchInput(ToolInput):
    query: str = Field(description="查询文本")
    top_k: int = Field(default=10, description="返回数量")

class VectorSearchTool(BaseTool):
    name = "vector_search"
    description = """
    语义相似度检索，通过向量匹配找到语义相关的文档。
    适用场景：概念理解、模糊查询、同义词相关。
    """
    input_schema = VectorSearchInput

    def __init__(self, qdrant_client: QdrantClient, collection: str):
        self.client = qdrant_client
        self.collection = collection

    async def execute(self, tool_input: VectorSearchInput) -> ToolResult:
        try:
            # 1. 嵌入查询
            from langchain_openai import OpenAIEmbeddings
            embeddings = OpenAIEmbeddings(
                model="text-embedding-3-small",
                api_key=os.getenv("OPENAI_API_KEY")
            )
            query_vector = await embeddings.aembed_query(tool_input.query)

            # 2. 检索
            results = self.client.search(
                collection_name=self.collection,
                query_vector=query_vector,
                limit=tool_input.top_k,
                with_payload=True
            )

            # 3. 格式化（强制包含索引字段）
            formatted = []
            for hit in results:
                payload = hit.payload or {}
                formatted.append({
                    "chunk_id": payload.get("chunk_id", str(hit.id)),
                    "doc_id": payload.get("doc_id", ""),
                    "page_number": payload.get("page_number", 0),
                    "source_db": "qdrant",
                    "content": payload.get("content", ""),
                    "score": hit.score
                })

            return ToolResult(
                success=True,
                content=json.dumps(formatted, ensure_ascii=False),
                metadata={"count": len(formatted), "source": "qdrant"}
            )

        except Exception as e:
            return ToolResult(success=False, content="", error=str(e))
```

**需要安装**: `qdrant-client`, `langchain-openai`

---

### 4.6 其他工具（结构类似）

| 文件 | 工具 | 关键参数 |
|-----|------|---------|
| `keyword_tool.py` | Elasticsearch | query, top_k |
| `graph_tool.py` | Neo4j | entities, top_k |
| `struct_tool.py` | PostgreSQL | chunk_ids 或 conditions |
| `calculator_tool.py` | eval/sympy | expression |

---

### 4.7 ReAct Agent (agent/react_agent.py)

```python
from langgraph.prebuilt import create_react_agent
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated
import operator

from core.llm import create_llm
from core.output_schema import AgentResponse
from tools import AllTools

class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    iterations: int
    max_iterations: int
    context: dict  # 存储各工具返回结果

def create_rag_agent():
    """创建四库RAG Agent"""

    # 1. 创建LLM（支持结构化输出）
    llm = create_llm()

    # 2. 创建工具
    tools = AllTools().get_all_tools()

    # 3. 创建Agent（LangGraph ReAct）
    agent = create_react_agent(
        model=llm,
        tools=tools,
        state_schema=AgentState,
        max_iterations=10,
        # 结构化输出配置
        response_format=AgentResponse,
    )

    return agent

async def run_agent(query: str) -> AgentResponse:
    """运行Agent"""
    agent = create_rag_agent()

    result = await agent.ainvoke({
        "messages": [("user", query)],
        "iterations": 0,
        "max_iterations": 10,
        "context": {}
    })

    return result["structured_response"]
```

---

### 4.8 查询规划器 (agent/query_planner.py)

```python
from pydantic import BaseModel
from typing import List

class QueryPlan(BaseModel):
    """查询规划"""
    sub_queries: List[str] = Field(description="分解的子查询")
    tool_sequence: List[str] = Field(description="工具调用序列")
    reasoning: str = Field(description="规划理由")

class QueryPlanner:
    """查询规划器 - LLM决定如何分解和执行"""

    def __init__(self, llm):
        self.llm = llm

    async def plan(self, query: str) -> QueryPlan:
        prompt = f"""
        分析用户查询: "{query}"

        请决定：
        1. 是否需要分解为多个子查询？
        2. 需要调用哪些工具？（可选: vector_search, keyword_search, knowledge_graph_search, structured_query, calculator）
        3. 调用顺序是什么？

        输出JSON格式。
        """

        # 使用LLM生成计划
        response = await self.llm.ainvoke(prompt)
        # 解析为QueryPlan
        return parse_json_to_model(response.content, QueryPlan)
```

---

### 4.9 验证器 (agent/verifier.py)

```python
from typing import List
from core.output_schema import IndexEntry

class VerificationResult(BaseModel):
    """验证结果"""
    is_valid: bool
    issues: List[str] = []
    confidence: float

class Verifier:
    """
    验证器 - Self-Verification模式
    检查检索结果的一致性和完整性
    """

    def __init__(self, llm):
        self.llm = llm

    async def verify(
        self,
        query: str,
        indices: List[IndexEntry],
        answer: str
    ) -> VerificationResult:
        """
        验证流程：
        1. 检查答案是否与索引匹配
        2. 检查是否有幻觉
        3. 检查计算是否正确
        """

        prompt = f"""
        验证以下问答：

        问题: {query}
        答案: {answer}

        引用的索引:
        {json.dumps([i.dict() for i in indices], ensure_ascii=False)}

        请检查：
        1. 答案是否从索引内容推导而来？（无幻觉）
        2. 索引是否覆盖了问题的关键信息？
        3. 答案是否完整？

        输出JSON格式验证结果。
        """

        response = await self.llm.ainvoke(prompt)
        return parse_json_to_model(response.content, VerificationResult)

    async def verify_consistency(
        self,
        results_from_different_tools: dict
    ) -> bool:
        """
        验证多库结果一致性
        如果语义检索和结构化查询的结果chunk_id有交集，说明一致性高
        """
        chunk_id_sets = [
            set(r.get("chunk_id") for r in results)
            for results in results_from_different_tools.values()
        ]

        if not chunk_id_sets:
            return True

        intersection = chunk_id_sets[0]
        for s in chunk_id_sets[1:]:
            intersection = intersection.intersection(s)

        # 有交集说明一致
        return len(intersection) > 0
```

---

### 4.10 入口服务 (main.py)

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from agent.react_agent import run_agent
from core.output_schema import AgentResponse

app = FastAPI(title="RAG Agent Service")

class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None

@app.post("/api/agent/query")
async def query(request: QueryRequest) -> AgentResponse:
    """RAG查询接口"""
    try:
        result = await run_agent(request.query)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok"}
```

**需要安装**: `fastapi`, `uvicorn`

---

## 五、LLM使用策略

### 5.1 LLM选择

| 场景 | 推荐模型 | 理由 |
|-----|---------|------|
| **工具选择/规划** | DeepSeek V3 | 逻辑推理强，便宜 |
| **答案生成** | DeepSeek V3 | 性价比高 |
| **验证/反思** | DeepSeek V3 | 需要逻辑分析 |

> 注：不建议用o1/o3等昂贵模型做工具调用，V3足够

### 5.2 Prompt设计原则

```python
SYSTEM_PROMPT = """
你是一个专业的RAG助手，擅长利用四个检索工具回答问题。

你有以下工具可用：
1. vector_search - 语义检索，适合概念理解
2. keyword_search - 关键词检索，适合精确匹配
3. knowledge_graph_search - 关系检索，适合实体关联
4. structured_query - SQL查询，适合数值条件
5. calculator - 计算器，适合数值计算

重要规则：
1. 每个检索结果必须包含 chunk_id, doc_id, page_number, source_db
2. 计算必须有公式和步骤
3. 答案必须基于检索结果，禁止编造
4. 如果结果不一致，需要多次检索验证

工作流程：
1. 理解问题
2. 选择合适工具
3. 执行检索
4. 验证结果
5. 生成答案（含溯源）
"""
```

---

## 六、容错与重试机制

### 6.1 工具执行重试

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
async def execute_with_retry(tool, tool_input):
    result = await tool.execute(tool_input)
    if not result.success:
        raise ToolExecutionError(result.error)
    return result
```

### 6.2 Agent迭代限制

```python
MAX_ITERATIONS = 10  # 防止无限循环

# LangGraph配置
agent = create_react_agent(
    model=llm,
    tools=tools,
    max_iterations=MAX_ITERATIONS,
    # 错误处理
    handle_parsing_errors=True,  # 自动修复输出格式错误
)
```

### 6.3 降级策略

```python
async def fallback_search(query: str):
    """降级检索策略"""
    # 1. 优先Qdrant
    result = await vector_search(query)
    if result.success:
        return result

    # 2. 降级到ES
    result = await keyword_search(query)
    if result.success:
        return result

    # 3. 降级到PG全表
    result = await structured_query(chunk_ids=[])
    return result
```

---

## 七、依赖清单

### 7.1 Python包

```txt
# 核心框架
langchain>=0.3.0
langgraph>=0.2.0
langchain-openai>=0.2.0
langchain-deepseek>=0.1.0

# 数据库驱动
qdrant-client>=1.7.0
elasticsearch>=8.0.0
neo4j>=5.0.0
asyncpg>=0.29.0
psycopg2-binary>=2.9.0

# Web服务
fastapi>=0.110.0
uvicorn>=0.27.0

# 辅助
pydantic>=2.0.0
pydantic-settings>=2.0.0
tenacity>=8.0.0
sympy>=1.12.0
python-dotenv>=1.0.0
```

### 7.2 安装命令

```bash
pip install langchain langgraph langchain-openai langchain-deepseek \
    qdrant-client elasticsearch neo4j asyncpg psycopg2-binary \
    fastapi uvicorn pydantic pydantic-settings tenacity sympy python-dotenv
```

---

## 八、开发工作量估算

| 模块 | 文件数 | 复杂度 | 估计行数 |
|-----|-------|--------|---------|
| 配置 | 1 | 低 | ~50 |
| LLM核心 | 2 | 中 | ~100 |
| 输出Schema | 1 | 中 | ~100 |
| 工具定义 | 5 | 高 | ~400 |
| Agent核心 | 3 | 高 | ~300 |
| 入口服务 | 1 | 低 | ~50 |
| 工具函数 | 2 | 低 | ~100 |
| **总计** | **15** | - | **~1100** |

---

## 九、关键风险与应对

| 风险 | 概率 | 影响 | 应对 |
|-----|-----|-----|------|
| LLM选择错误工具 | 中 | 高 | 优化工具描述；增加few-shot示例 |
| 检索结果质量差 | 中 | 高 | 增加验证循环；多库交叉验证 |
| 无限循环 | 低 | 高 | max_iterations限制 |
| 数据库连接失败 | 中 | 中 | 降级策略；连接池 |
| 输出格式不稳定 | 中 | 中 | 使用structured_output强制约束 |

---

## 十、Agent 核心测试题与跑通标准

Agent 必须通过的 16 道核心测试题（详见 `docs/agent.md` §二）：

| 序号 | 问题类型 | 示例 |
|------|----------|------|
| 01-02 | 定额子目查询 | 安装工程消耗量标准、装饰工程人工费 |
| 03-05, 15-16 | 信息价查询/对比 | 电力电缆价格差异、中砂价格、环比变化 |
| 06-07, 09-12, 14 | 标准条文解读 | 安全文明施工费、利润率对比、计算基数 |
| 08, 13 | 费率计算/反推 | 赶工措施费系数、企业管理费率 |

### 跑通判定标准

1. **有索引引用**：回答必须标注参考来源（chunk_id / 文档名 / 页码）
2. **数值准确**：金额、系数、比例必须与原始文档一致
3. **工具调用痕迹**：至少一次四库工具调用记录
4. **质量审核通过**：`evaluation.passed === true`（confidence ≥ 0.7）
5. **无幻觉**：未编造原始文档中不存在的内容

**必须 16/16 全部通过，Agent 才算跑通。**

---

## 十一、下一步行动

### 阶段一：基础实现（1-2天）
1. [ ] 创建项目目录结构
2. [ ] 实现配置管理 (config.py)
3. [ ] 实现LLM初始化 (core/llm.py)
4. [ ] 实现结构化输出Schema (core/output_schema.py)
5. [ ] 实现五个工具 (tools/*.py)

### 阶段二：Agent核心（2-3天）
6. [ ] 实现ReAct Agent (agent/react_agent.py)
7. [ ] 实现查询规划器 (agent/query_planner.py)
8. [ ] 实现验证器 (agent/verifier.py)
9. [ ] 实现入口服务 (main.py)

### 阶段三：质量与迭代（2-3天）
10. [ ] 集成 XState v5 状态机（`machine.ts` 中的 evaluating → planning 回退逻辑）
11. [ ] 实现带索引回答生成（citations 提取与对齐）
12. [ ] 实现质量自审（7维评分 + passed 判定）
13. [ ] 实现递归迭代优化（未通过时自动调整策略并重试）

### 阶段四：跑通验证（1-2天）
14. [ ] 编写 16 道测试题的自动化测试脚本
15. [ ] 单条调试直至全部通过
16. [ ] 生成跑通报告（`logs/rag-evaluation-report.json`）

### 阶段五：观测与优化（持续）
17. [ ] 接入 LangFuse 追踪每条测试的工具调用链路
18. [ ] 接入 Ragas 评估语义质量
19. [ ] 接入 Promptfoo 做 Prompt A/B 测试
20. [ ] 针对未通过题目迭代优化 Prompt / 检索策略

---

## 附录：参考文档

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain Agents](https://python.langchain.com/docs/concepts/agents/)
- [Agentic RAG - BeyondScale](https://beyondscale.tech/blog/agentic-rag-enterprise-guide)
- [Self-RAG IBM Guide](https://ibm.github.io/ibmdotcom-tutorials/tutorials/generative-ai/self_rag/)

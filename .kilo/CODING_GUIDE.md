# Kilo Code 开发指导手册

## 一、技术栈规范

### 1.1 核心架构原则

**弱耦合架构 (Hexagonal/Ports-Adapters)**
- 契约优先 (Schema-First)
- 依赖注入 (Dependency Injection)
- 接口隔离 (Interface Segregation)
- 领域驱动 (Domain-Driven)

### 1.2 完整技术栈

```
┌─────────────────────────────────────────┐
│  Client (Web/App/Third-party)            │
└──────────────┬──────────────────────────┘
               │ HTTPS/OpenAPI Contract
┌──────────────▼──────────────────────────┐
│  API Layer (FastAPI)                     │ ◄── Pydantic 验证
│  - Routes (Adapters)                     │
│  - Dependency Injection                  │
└──────────────┬──────────────────────────┘
               │ 领域对象 (Pure Python)
┌──────────────▼──────────────────────────┐
│  Application Layer (Usecases)            │ ◄── 业务逻辑
│  - Domain Services                       │
│  - Result[Success, Failure]              │
└──────────────┬──────────────────────────┘
               │ 接口（Protocols）
┌──────────────▼──────────────────────────┐
│  Infrastructure Layer (Adapters)         │
│  - SQLAlchemy Repository                 │
│  - Redis Cache                           │
│  - HTTP Client (httpx)                   │
│  - Vector DB (Qdrant/Chroma)             │
└──────────────┬──────────────────────────┘
               │ 外部资源
┌──────────────▼──────────────────────────┐
│  PostgreSQL / Redis / Kafka / S3         │
└─────────────────────────────────────────┘
```

### 1.3 必用工具清单

| 层级 | 工具 | 用途 | 替代方案 |
|------|------|------|---------|
| **契约定义** | OpenAPI 3.1 | API 契约标准 | GraphQL Schema |
| | datamodel-code-generator | openapi.yaml → models.py | 手动维护 |
| | schemathesis | 自动fuzz测试 | 手写边界测试 |
| **Web框架** | FastAPI | 主框架 | Litestar |
| | uvicorn | ASGI服务器 | hypercorn |
| **验证层** | Pydantic v2 | 请求/响应验证 | Cerberus |
| | pydantic-settings | YAML/Env配置 | python-dotenv |
| | annotated-types | 轻量约束 | typing.Annotated |
| **ORM** | SQLAlchemy 2.0 | 数据库ORM | Prisma |
| | alembic | 数据库迁移 | 手动SQL |
| **领域层** | dependency-injector | DI容器 | injector |
| | returns | Result类型 | 原生try-except |
| **外部通信** | httpx | 异步HTTP | aiohttp |
| | tenacity | 重试策略 | 手动实现 |
| **可观测性** | structlog | 结构化日志 | 标准logging |
| | opentelemetry | 分布式追踪 | Jaeger |
| | prometheus-client | 指标监控 | statsd |
| **测试** | pytest | 测试框架 | unittest |
| | polyfactory | 假数据生成 | factory-boy |
| | testcontainers | 集成测试容器 | docker-compose |
| | hypothesis | 属性测试 | 边界值测试 |

### 1.4 数字型精确处理

```python
from decimal import Decimal
from pydantic import Field, BaseModel
from annotated_types import Ge, Le
from typing import Annotated

class Money(BaseModel):
    """金钱类型 - 三层保险"""
    # 1. Decimal 类型（非 float）
    # 2. 范围限制
    # 3. 精度控制（小数点后2位）
    amount: Annotated[Decimal, Ge(0), Le(1e9)] = Field(decimal_places=2)
    currency: Literal["CNY", "USD", "EUR"]
    
    @field_validator('amount')
    @classmethod
    def no_scientific_notation(cls, v: Decimal):
        """防止科学计数法导致精度丢失"""
        if 'E' in str(v).upper():
            raise ValueError('Scientific notation not allowed')
        return v
```

### 1.5 配置管理规范

```python
from pydantic import Field, field_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal, List
import yaml
from pathlib import Path

class DatabaseConfig(BaseSettings):
    """数据库配置"""
    host: str = "localhost"
    port: int = Field(default=5432, ge=1024, le=65535)
    username: str
    password: SecretStr  # 自动隐藏打印
    
    @field_validator('host')
    @classmethod
    def no_localhost_in_prod(cls, v: str, info) -> str:
        """生产环境强制校验"""
        if info.context and info.context.get('env') == 'production':
            if v == 'localhost':
                raise ValueError('生产环境 DB host 不能是 localhost')
        return v

class AppConfig(BaseSettings):
    """应用配置 - 防AI误伤核心"""
    model_config = SettingsConfigDict(
        yaml_file="config.yaml",
        yaml_file_encoding='utf-8',
        env_nested_delimiter='__',  # APP_DB__HOST=xxx
        extra='forbid'  # AI瞎写多余字段会报错！
    )
    
    env: Literal["dev", "staging", "production"] = "dev"
    debug: bool = False
    db: DatabaseConfig
    allowed_hosts: List[str] = ["*"]
    
    @classmethod
    def from_yaml(cls, path: Path = Path("config.yaml")):
        """显式加载YAML并验证"""
        if not path.exists():
            raise FileNotFoundError(f"配置文件 {path} 不存在")
        
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        return cls.model_validate(data, context={'env': data.get('env', 'dev')})

# 使用
config = AppConfig.from_yaml()
```

## 二、递归开发思想

### 2.1 核心原则

**递归是一种思维模式，不是代码结构**

```
问题分解 → 子问题解决 → 结果合并
    ↑___________________________↓
              (递归)
```

### 2.2 五层递进式开发协议

```
Layer 1: 骨架
  └─ 写类型定义和接口
  └─ [自检] TypeScript编译通过?
      ├─ 否 → 修正(最多3次) → 仍失败 → 回退
      └─ 是 → Layer 2

Layer 2: 实现
  └─ 写核心业务逻辑
  └─ [自检] 功能可用?
      ├─ 否 → 修正 → 仍失败 → 回退
      └─ 是 → Layer 3

Layer 3: 测试
  └─ 写单元测试
  └─ [自检] 核心路径通过?
      ├─ 否 → 修正 → 仍失败 → 回退
      └─ 是 → Layer 4

Layer 4: 边界
  └─ 处理异常和边界情况
  └─ [自检] 无明显crash?
      ├─ 否 → 修正 → 仍失败 → 回退
      └─ 是 → Layer 5

Layer 5: 优化
  └─ 清理和性能优化
  └─ [自检] 代码整洁?
      └─ 完成，提交
```

### 2.3 任务分解模式

**大任务 → 小任务 → 可执行单元**

```python
# 错误示范：一次性写完全部
class RAGPipeline:
    def query(self, q): 
        # 100行代码处理所有逻辑
        pass

# 正确示范：递归分解
class RAGPipeline:
    def query(self, q) -> RAGResponse:
        """主入口 - 只负责编排"""
        embedding = self.embed(q)
        candidates = self.retrieve(embedding)
        ranked = self.rerank(q, candidates)
        return self.build_response(ranked)
    
    def embed(self, text) -> Vector:
        """子任务1：嵌入"""
        pass
    
    def retrieve(self, vector) -> List[Document]:
        """子任务2：召回 - 可再分解"""
        vector_results = self.vector_search(vector)
        keyword_results = self.keyword_search(vector)
        return self.merge_results(vector_results, keyword_results)
    
    def rerank(self, query, docs) -> List[Document]:
        """子任务3：精排"""
        pass
```

## 三、举一反三思维

### 3.1 模式识别

**看到一个实现 → 抽象模式 → 应用到其他场景**

```python
# 例子：看到召回精排模式
# 抽象：多路召回 → 合并 → 精排 → 融合

# 举一反三1：推荐系统
# 多路召回(协同过滤 + 内容相似 + 热门) → 合并 → 精排模型 → 融合分数

# 举一反三2：搜索引擎
# 多路召回(BM25 + 向量 + 图谱) → 合并 → Cross-Encoder → 融合分数

# 举一反三3：异常检测
# 多路检测(统计 + 机器学习 + 规则) → 合并 → 集成模型 → 融合置信度
```

### 3.2 抽象层次

```
具体实现 → 设计模式 → 架构原则 → 数学本质

例子：召回精排
├── 具体：Qdrant + ES + Neo4j + BGE模型
├── 模式：多路召回 + 精排融合
├── 原则：分而治之 + 级联优化
└── 数学：候选集生成 + 排序学习(LTR)
```

## 四、阶段性完成策略

### 4.1 检查点模式

**每个阶段必须有可验证的输出**

```
阶段1: 骨架完成
  └─ 验证：类型检查通过
  └─ 输出：接口定义文件
  └─ 等待：用户确认方向正确

阶段2: 核心实现
  └─ 验证：单元测试通过
  └─ 输出：可运行的核心逻辑
  └─ 等待：用户确认逻辑正确

阶段3: 集成测试
  └─ 验证：端到端测试通过
  └─ 输出：完整功能
  └─ 等待：用户验收
```

### 4.2 用户审批流程

**禁止擅自进入下一阶段**

```python
class DevelopmentPhase:
    def execute(self):
        # 1. 完成当前阶段
        result = self.do_work()
        
        # 2. 自检
        if not self.self_check(result):
            return self.fix_and_retry()
        
        # 3. 提交用户审批
        self.submit_for_approval(result)
        
        # 4. 等待用户确认（必须等待！）
        # 禁止自动进入下一阶段
        return WAITING_FOR_APPROVAL
```

## 五、时间配置

### 5.1 等待时间

| 操作 | 默认超时 | 重试次数 | 重试间隔 |
|------|---------|---------|---------|
| 网络请求 | 120s | 3 | 5s |
| 模型加载 | 300s | 2 | 10s |
| Docker操作 | 300s | 3 | 10s |
| 数据库连接 | 60s | 5 | 5s |
| 文件下载 | 600s | 3 | 30s |

### 5.2 循环步骤

```python
# 重试模式
def retry_with_backoff(
    func, 
    max_retries=5,
    base_delay=1.0,
    max_delay=60.0,
    exponential_base=2.0
):
    """指数退避重试"""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            
            delay = min(
                base_delay * (exponential_base ** attempt),
                max_delay
            )
            time.sleep(delay)
```

## 六、开发流程规范

### 6.1 开始新任务

1. **阅读相关文件**
   - AGENTS.md
   - 计划文件 (plans/*.md)
   - 现有代码结构

2. **确认理解**
   - 复述任务目标
   - 列出关键约束
   - 提出澄清问题

3. **制定计划**
   - 分解为阶段
   - 每个阶段定义完成标准
   - 预估每个阶段时间

### 6.2 执行阶段

1. **单阶段工作**
   - 专注当前阶段
   - 不提前做下一阶段
   - 保持代码可运行

2. **频繁自检**
   - 类型检查
   - 单元测试
   - 代码风格

3. **阶段提交**
   - 总结完成内容
   - 明确下一步
   - 等待用户确认

### 6.3 禁止行为

- ✗ 擅自修改未授权的文件
- ✗ 自动进入下一阶段
- ✗ 跳过用户确认
- ✗ 一次性提交大量代码
- ✗ 不做测试直接提交
- ✗ 忽略错误继续执行

## 七、代码审查清单

### 7.1 提交前自检

```markdown
- [ ] 类型检查通过 (mypy/pyright)
- [ ] 单元测试通过 (pytest)
- [ ] 代码格式正确 (black/ruff)
- [ ] 无敏感信息泄露
- [ ] 文档字符串完整
- [ ] 异常处理完善
- [ ] 日志记录适当
```

### 7.2 架构审查

```markdown
- [ ] 符合弱耦合原则
- [ ] 依赖注入正确使用
- [ ] 领域逻辑独立
- [ ] 接口定义清晰
- [ ] 错误处理统一
- [ ] 配置外部化
```

## 八、示例：召回精排实现

### 8.1 契约定义 (OpenAPI)

```yaml
# openapi.yaml
components:
  schemas:
    SearchRequest:
      type: object
      properties:
        query:
          type: string
          minLength: 1
          maxLength: 1000
        top_k:
          type: integer
          minimum: 1
          maximum: 100
          default: 10
      required: [query]
    
    SearchResponse:
      type: object
      properties:
        documents:
          type: array
          items:
            $ref: '#/components/schemas/Document'
        total_time_ms:
          type: number
    
    Document:
      type: object
      properties:
        id:
          type: string
        content:
          type: string
        score:
          type: number
          minimum: 0
          maximum: 1
```

### 8.2 生成模型

```bash
datamodel-codegen --input openapi.yaml --output models.py
```

### 8.3 领域层实现

```python
# domain/ports.py
from typing import Protocol, List
from models import Document, Vector

class VectorStore(Protocol):
    async def search(self, vector: Vector, top_k: int) -> List[Document]: ...

class Reranker(Protocol):
    async def rerank(self, query: str, docs: List[Document]) -> List[Document]: ...

# application/usecases.py
class SearchUsecase:
    def __init__(
        self,
        vector_store: VectorStore,
        keyword_store: KeywordStore,
        reranker: Reranker
    ):
        self._vector_store = vector_store
        self._keyword_store = keyword_store
        self._reranker = reranker
    
    async def execute(self, query: str, top_k: int) -> SearchResult:
        # 多路召回
        vector_results = await self._vector_store.search(query.vector, top_k=30)
        keyword_results = await self._keyword_store.search(query.text, top_k=20)
        
        # 合并去重
        candidates = self._merge_and_deduplicate(vector_results, keyword_results)
        
        # 精排
        ranked = await self._reranker.rerank(query.text, candidates[:top_k*2])
        
        return SearchResult(documents=ranked[:top_k])
```

### 8.4 适配器实现

```python
# infrastructure/vector/qdrant_store.py
from qdrant_client import QdrantClient

class QdrantVectorStore:
    def __init__(self, client: QdrantClient, collection: str):
        self._client = client
        self._collection = collection
    
    async def search(self, vector: Vector, top_k: int) -> List[Document]:
        results = self._client.search(
            collection_name=self._collection,
            query_vector=vector.tolist(),
            limit=top_k
        )
        return [self._to_doc(r) for r in results]
```

### 8.5 依赖注入配置

```python
# container.py
from dependency_injector import containers, providers

class Container(containers.DeclarativeContainer):
    config = providers.Configuration()
    
    qdrant_client = providers.Singleton(
        QdrantClient,
        host=config.qdrant.host,
        port=config.qdrant.port
    )
    
    vector_store = providers.Singleton(
        QdrantVectorStore,
        client=qdrant_client,
        collection=config.qdrant.collection
    )
    
    search_usecase = providers.Singleton(
        SearchUsecase,
        vector_store=vector_store,
        keyword_store=keyword_store,
        reranker=reranker
    )
```

### 8.6 API层

```python
# api/routes.py
from fastapi import APIRouter, Depends
from dependency_injector.wiring import inject, Provide

router = APIRouter()

@router.post("/search", response_model=SearchResponse)
@inject
async def search(
    request: SearchRequest,
    usecase: SearchUsecase = Depends(Provide[Container.search_usecase])
):
    result = await usecase.execute(request.query, request.top_k)
    return SearchResponse(documents=result.documents)
```

## 九、总结

**核心原则**：
1. 契约优先 - OpenAPI定义即法律
2. 弱耦合 - 依赖接口而非实现
3. 递归开发 - 分阶段交付，层层递进
4. 用户确认 - 每个阶段等待审批
5. 类型安全 - Pydantic全链路验证

**禁止事项**：
- 不做测试直接提交
- 自动进入下一阶段
- 跳过用户确认
- 一次性大量代码

**时间配置**：
- 网络请求：120s超时，3次重试
- 模型加载：300s超时，2次重试
- Docker操作：300s超时，3次重试
- 文件下载：600s超时，3次重试

# KIMI_EMBEDDING_OPTIMIZE.md
> Copilot（智囊）→ Kimi Code（执行者）Embedding 性能优化指引  
> **规则**：按 Phase 顺序执行。每个 Phase 完成后填报告，等 Copilot 审查再继续。

---

## ⚠️ Kimi 行为准则（每次执行前必读）

### 🧠 举一反三原则

**你不是一台只会照搬指令的机器。** 本文档给出的是 Copilot 发现的问题和修复方向，但代码是活的——在执行过程中你可能会发现：

1. **同类问题**：修一个文件时，发现同目录/同模块的其他文件也有一模一样的 bug（比如看到 `recreate_collection`，其他 `_store_to_xxx` 方法可能也有类似的每次重建行为）
2. **上下游问题**：修了 A 函数，发现调用 A 的 B 函数也有问题（比如给 encode 加了 `run_in_executor`，但调用方没有 `await`）
3. **配置不一致**：代码改了但 config/env 没对齐（比如改了集合名但 `.env` 里还写着旧名字）
4. **修了一个问题暴露另一个**：很正常，继续修，记录到报告里

**遇到这些情况时：**
- ✅ **一起修了**（如果改动量小，<10 行）
- ✅ **记录到报告的"额外发现"栏**
- ❌ **不要视而不见**——"文档没说要改这个"不是理由
- ❌ **不要大规模重构**——超过 20 行的额外改动先记录，等 Copilot 评估

### 🔄 卡住时的自救策略

如果某个步骤执行报错或效果不对，**不要反复重试同一个方法**：

1. **读错误信息**（不是看第一行就放弃，把完整 traceback 从下往上读）
2. **换个角度诊断**：
   - 命令报错 → 先确认前置条件（服务是否启动、文件是否存在、import 路径对不对）
   - 改了代码不生效 → 服务可能没重启，或者改错文件了（这个项目有 5 个 EmbeddingService！确认你改的是被调用的那个）
   - 性能没改善 → 可能瓶颈不在你改的地方，用 `time` 或 `print` 加计时确认
3. **记录失败原因和尝试过的方法**，写到报告里，让 Copilot 给新方案
4. **绝对不要**：
   - 删文件重建来"解决"import 问题
   - 加 `try: except: pass` 来"解决"报错
   - 改测试用例来"解决"测试失败

---

## 📐 核心架构认知（改代码前必须理解）

### 两条独立的代码路径

```
                        ┌─────────────────────────────────────────┐
  用户查询 ──→ Gateway ──→│ retrieval-service (:8002)               │ ← 高频热路径（每次问答）
                        │   embedding_service.py → encode_query() │
                        │   unified_store.py → _multi_recall()    │
                        └─────────────────────────────────────────┘

                        ┌─────────────────────────────────────────┐
  数据导入 ──→           │ python-legacy (:8000)                    │ ← 低频冷路径（偶尔导入）
                        │   services/embedding_service.py         │
                        │   services/model_caller.py              │
                        │   tools/unified_four_db_import.py       │
                        └─────────────────────────────────────────┘
```

**关键区别：**
- `retrieval-service` 是查询时用的，每个用户问题都走这里 → **这里的性能问题影响最大**
- `python-legacy` 主要是数据导入时用 → **这里的 bug（如 recreate_collection）影响数据完整性**
- **它们有各自独立的 EmbeddingService！** 改一个不影响另一个

### 你要改的文件（按优先级）

| # | 文件 | 服务 | 改什么 | 为什么重要 |
|---|------|------|--------|-----------|
| 1 | `src/backend/retrieval-service/infrastructure/adapters/unified/unified_store.py` | 查询 | `requests.post()` → `qdrant_client` | 每次查询都多 10-50ms |
| 2 | `src/backend/retrieval-service/infrastructure/embedding_service.py` | 查询 | 加 LRU 缓存 | 相同查询不重复 encode |
| 3 | `src/backend/python-legacy/services/embedding_service.py` | 导入 | `recreate_collection` 杀数据 bug | 导入数据不再丢失 |
| 4 | `src/backend/python-legacy/services/embedding_service.py` | 导入 | `conn.close()` 破坏连接池 | 导入不再卡死 |
| 5 | `src/backend/python-legacy/services/embedding_service.py` | 导入 | `redis.Redis` → `redis.asyncio.Redis` | 导入时不阻塞事件循环 |

---

## ⏩ Phase 1：查询热路径优化（retrieval-service）

### 目标

优化每次用户查询都会走的代码路径，减少 embedding + 向量搜索延迟。

### 1.1 把 Qdrant 搜索从 REST API 改为 qdrant_client

文件：`src/backend/retrieval-service/infrastructure/adapters/unified/unified_store.py`

**当前问题**：`_multi_recall()` 方法中，向量搜索用 `requests.post()` 发 HTTP 请求到 Qdrant REST API。1024 维向量 JSON 序列化后约 8KB，加上 HTTP 开销，每次查询多 10-50ms。而且 `requests` 是同步库，会阻塞。

**找到这段代码**（大约在 370-400 行）：
```python
import requests
search_response = requests.post(
    f"http://{self.config.vector.host}:{self.config.vector.port}/collections/{self.config.vector.collection_name}/points/search",
    json={
        "vector": query_vector,
        "limit": config.vector_top_k,
        "with_payload": True,
    },
)
```

**替换为**（使用类已有的 `self.vector_client`，它是 `QdrantClient` 实例）：
```python
search_result_raw = self.vector_client.search(
    collection_name=self.config.vector.collection_name,
    query_vector=query_vector,
    limit=config.vector_top_k,
    with_payload=True,
)
```

然后把后面解析 `search_response.json()` 的逻辑改为解析 `search_result_raw`（它返回 `ScoredPoint` 对象列表）：
```python
# 旧：遍历 JSON dict
for point in search_result:
    payload = point.get("payload", {}) or {}
    ...

# 新：遍历 ScoredPoint 对象
for point in search_result_raw:
    payload = point.payload or {}
    chunk = DocumentChunk(
        chunk_id=point.id,
        doc_id=payload.get("doc_id", ""),
        content=payload.get("content", ""),
        chunk_type=ChunkType.TEXT,
        page_number=payload.get("page_number", 1),
        section=payload.get("section"),
        keywords=payload.get("keywords", []),
        confidence=payload.get("confidence", 1.0),
    )
    ...
```

**⚠️ 注意**：改完之后如果 `import requests` 不再被任何地方使用，删掉这个 import。但先 grep 确认文件里其他地方没有用到 `requests`。

**举一反三**：检查同文件中是否还有其他地方用 `requests.post/get` 调 Qdrant/ES。如果有，一并改掉。

### 1.2 给 encode_query 加 LRU 缓存

文件：`src/backend/retrieval-service/infrastructure/embedding_service.py`

**当前问题**：每次查询都调 `encode_query()` → `model.encode()`，CPU 上约 100-200ms。同一查询（evaluator 重复调用、用户重复提问）不需要重算。

在文件顶部添加：
```python
from functools import lru_cache
```

改造三个方法：
```python
@lru_cache(maxsize=256)
def _encode_cached(self, text: str) -> tuple:
    """内部缓存方法（lru_cache 要求返回值 hashable，用 tuple）"""
    results = self.encode([text])
    return tuple(results[0]) if results else tuple([0.0] * self.dimension)

def encode_single(self, text: str) -> List[float]:
    """编码单个文本（带缓存）"""
    return list(self._encode_cached(text))

def encode_query(self, text: str) -> List[float]:
    """编码查询文本（添加 BGE instruction prefix 提升检索精度）"""
    prefix = "Represent this sentence for searching relevant passages: "
    return list(self._encode_cached(prefix + text))
```

**⚠️ 注意**：`lru_cache` 装饰器作用在实例方法上时，会以 `self` 为 key 的一部分，所以只要全局只有一个 `EmbeddingService` 单例（当前代码确实如此），就没问题。

**举一反三**：看看 `encode()` 批量方法是否也有被频繁重复调用的场景。如果有，可在调用方去重。

### 1.3 验证

```bash
# 重启 retrieval-service
pkill -f "uvicorn.*8002" || true
sleep 3
cd /home/l/rag-dashboard/src/backend/retrieval-service
source /home/l/rag-dashboard/venv/bin/activate
nohup python -m uvicorn main:app --host 0.0.0.0 --port 8002 > /tmp/retrieval.log 2>&1 &
sleep 15

# health check
curl -s http://localhost:8002/health | python3 -m json.tool

# 功能验证：Q01
curl -s -X POST http://localhost:8002/api/v1/agent \
  -H "Content-Type: application/json" \
  -d '{"query": "安装工程消耗量定额中，电气设备安装的人工费单价标准是多少？", "max_iterations": 3}' \
  | python3 -c "
import sys, json
r = json.load(sys.stdin)
ev = r.get('evaluation', {})
print(f'passed={ev.get(\"passed\")} conf={ev.get(\"confidence\",0):.3f} chunks={len(r.get(\"chunks\",[]))}')
print(f'answer: {r.get(\"answer\",\"\")[:120]}...')
"

# 性能验证：同一查询跑两次，对比耗时（第二次应该快，因为缓存命中）
echo "=== 第一次（冷缓存）==="
time curl -s -X POST http://localhost:8002/api/v1/agent \
  -H "Content-Type: application/json" \
  -d '{"query": "2025版费率标准中，一般计税与简易计税的适用条件分别是什么？", "max_iterations": 3}' > /dev/null

echo "=== 第二次（热缓存）==="
time curl -s -X POST http://localhost:8002/api/v1/agent \
  -H "Content-Type: application/json" \
  -d '{"query": "2025版费率标准中，一般计税与简易计税的适用条件分别是什么？", "max_iterations": 3}' > /dev/null

# 如果启动失败，看日志
tail -30 /tmp/retrieval.log
```

---

### 📋 Phase 1 报告

#### 1.1 Qdrant client 改造

- [ ] `requests.post()` 已替换为 `self.vector_client.search()`
- [ ] 解析逻辑已适配 `ScoredPoint` 对象
- [ ] 已检查并清理废弃的 `import requests`

#### 1.2 LRU 缓存

- [ ] `_encode_cached` 方法已添加
- [ ] `encode_single` 和 `encode_query` 已改为走缓存

#### 1.3 验证结果

```
（粘贴 health check + Q01 测试结果）
```

- 第一次耗时：
- 第二次耗时：
- 缓存加速效果：

#### 额外发现（举一反三）

```
（在改代码过程中发现的其他问题：
  - 发现了什么
  - 是否顺手修了（<10行的一起改）
  - 如果没修，建议怎么处理）
```

---

## Phase 2：导入冷路径修复（python-legacy）

> ⚠️ **等 Phase 1 报告审查通过后再执行**

### 目标

修复数据导入路径的 3 个 bug，确保以后导入数据不丢失、不卡死。

### 2.1 修复 `recreate_collection`（数据毁灭级 bug）

文件：`src/backend/python-legacy/services/embedding_service.py`

**当前问题**：`_store_to_qdrant()` 每次插入一个 chunk 都调 `recreate_collection()`，把整个集合删了重建。最终集合里只有最后一个 chunk。

**找到**（约 280 行）的 `recreate_collection` 调用，**整块删除**。

**然后在 `initialize()` 末尾**（`logger.info("Embedding服务初始化完成")` 之前）添加一次性创建逻辑：
```python
# 确保 Qdrant 集合存在（只创建一次，不删已有数据）
try:
    collections = [c.name for c in self.qdrant_client.get_collections().collections]
    if "document_chunks" not in collections:
        self.qdrant_client.create_collection(
            collection_name="document_chunks",
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE)
        )
        logger.info("Created Qdrant collection: document_chunks")
    else:
        logger.info("Qdrant collection exists: document_chunks")
except Exception as e:
    logger.warning(f"Qdrant collection check failed: {e}")
```

**举一反三**：
```bash
grep -rn "recreate_collection" src/backend/
```
如果别的文件也有，记录下来。

### 2.2 修复 `conn.close()` 破坏连接池

同文件，找到 `_store_to_postgres()` 方法（约 360 行）：

**只需删除 `await conn.close()` 这一行。** `async with pool.acquire()` 会自动释放连接。

**举一反三**：
```bash
grep -rn "conn.close()" src/backend/python-legacy/
```

### 2.3 修复 Redis 同步客户端

同文件，`initialize()` 方法中（约 75 行）：

```python
# 旧
self.redis_client = redis.Redis(
    host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True
)

# 新
self.redis_client = redis.asyncio.Redis(
    host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True
)
```

**然后**检查所有用到 `self.redis_client` 的地方，加 `await`：
```python
# 旧：self.redis_client.setex(key, ttl, value)
# 新：await self.redis_client.setex(key, ttl, value)
```

**⚠️ 先查 redis 版本**：
```bash
pip show redis | grep Version
```
如果版本 < 4.2.0，不改 Redis，在报告里注明版本号。

**举一反三**：
```bash
grep -rn "redis.Redis(" src/backend/
```

### 2.4 验证

```bash
cd /home/l/rag-dashboard/src/backend/python-legacy
source /home/l/rag-dashboard/venv/bin/activate

# 语法检查
python -c "import services.embedding_service; print('import OK')"

# 确认三个修复
grep -n "recreate_collection" services/embedding_service.py && echo "⚠️ 还有残留！" || echo "✅ recreate_collection 已清除"
grep -n "conn.close()" services/embedding_service.py && echo "⚠️ 还有残留！" || echo "✅ conn.close 已清除"
grep -n "redis.asyncio\|redis.Redis" services/embedding_service.py
```

---

### 📋 Phase 2 报告

#### 2.1 recreate_collection 修复

- [ ] `initialize()` 中添加了集合存在性检查
- [ ] `_store_to_qdrant()` 中删除了 `recreate_collection` 调用

其他文件是否也有 `recreate_collection`？
```
（粘贴 grep 结果）
```

#### 2.2 conn.close() 修复

- [ ] 已删除 `await conn.close()`

其他文件是否也有连接池内 `conn.close()`？
```
（粘贴 grep 结果）
```

#### 2.3 Redis 异步化

- Redis 版本：
- [ ] 已改为 `redis.asyncio.Redis` / 版本不支持已跳过
- [ ] 所有调用点已加 `await`

#### 验证结果

```
（粘贴语法检查 + grep 确认结果）
```

#### 额外发现（举一反三）

```
（全项目 grep 扫出的同类问题）
```

---

## Phase 3：全量回测确认无退化

> ⚠️ **等 Phase 2 报告审查通过后再执行**

### 目标

确认 Phase 1+2 的改动没有破坏 14/16 基线。

### 执行

```bash
cd /home/l/rag-dashboard

# 重启 retrieval-service
pkill -f "uvicorn.*8002" || true
sleep 3
cd src/backend/retrieval-service
source /home/l/rag-dashboard/venv/bin/activate
nohup python -m uvicorn main:app --host 0.0.0.0 --port 8002 > /tmp/retrieval.log 2>&1 &
sleep 15

curl -s http://localhost:8002/health | python3 -m json.tool

# 16 题全量回测
questions=(
  "安装工程消耗量定额中，电气设备安装的人工费单价标准是多少？"
  "25版装饰工程消耗量定额与23版相比，新增了哪些工程项目？"
  "对比深圳市2025版建筑工程消耗量定额与2023版在混凝土工程中的主要变化"
  "根据深圳信息价2026年1月数据，普通硅酸盐水泥P.O 42.5的含税价格是多少？"
  "2025年深圳信息价中，商品混凝土C30的市场指导价范围是多少？"
  "详细说明深圳市建设工程计价费率2025版中安全文明施工费的计算方法"
  "工程项目中施工图预算审核的主要流程和关键节点有哪些？"
  "2025版费率标准中，一般计税与简易计税的适用条件分别是什么？"
  "一般计税方法下，建筑安装工程费的增值税税率和计算基数是什么？"
  "总包管理服务费的计算基数和费率范围是什么？"
  "模块化建筑工程施工工期定额与传统建筑相比有何差异？"
  "2023版与2025版定额在脚手架工程量计算规则上有何区别？"
  "某工程人工费为500万，材料费为1200万，按2025版费率计算企业管理费是多少？"
  "按2025版标准，规费中社会保险费包含哪几项？各自的计算基础是什么？"
  "2026年1月中砂（河砂，中）的信息指导价是多少？与去年同期相比变化趋势如何？"
  "2026年1月电线电缆（BV 2.5mm²铜芯）的信息指导价是多少？"
)

echo "===== 全量回测（Embedding优化后）====="
passed=0
failed_list=""
for i in "${!questions[@]}"; do
  n=$((i + 1))
  q="${questions[$i]}"
  printf "Q%02d: %s... " "$n" "${q:0:25}"
  result=$(curl -s --max-time 60 -X POST http://localhost:8002/api/v1/agent \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"$q\", \"max_iterations\": 3}")

  p=$(echo "$result" | python3 -c "
import sys,json
r=json.load(sys.stdin)
ev=r.get('evaluation',{})
print(f'{ev.get(\"passed\",False)} conf={ev.get(\"confidence\",0):.3f} chunks={len(r.get(\"chunks\",[]))}')
" 2>/dev/null)
  echo "$p"

  if echo "$p" | grep -q "^True"; then
    passed=$((passed + 1))
  else
    failed_list="$failed_list Q$(printf '%02d' $n)"
  fi
done

echo "===== 结果: ${passed}/16 ====="
echo "失败题目:${failed_list:-无}"
```

---

### 📋 Phase 3 报告

#### 回测结果

| # | passed | confidence | chunks |
|---|--------|------------|--------|
| 01 | | | |
| 02 | | | |
| 03 | | | |
| 04 | | | |
| 05 | | | |
| 06 | | | |
| 07 | | | |
| 08 | | | |
| 09 | | | |
| 10 | | | |
| 11 | | | |
| 12 | | | |
| 13 | | | |
| 14 | | | |
| 15 | | | |
| 16 | | | |

**汇总：** /16 passed

#### 与基线对比

| 指标 | Phase 12 基线 | 优化后 | 变化 |
|------|--------------|--------|------|
| Passed | 14/16 | /16 | |
| 失败题目 | Q02, Q11 | | |

#### 性能对比

| 指标 | 优化前 | 优化后 | 改善 |
|------|--------|--------|------|
| 平均响应时间 | ~8s | | |
| 重复查询耗时 | ~8s | | |

#### 结果判定

- [ ] ≥14/16 无退化 → ✅ 优化成功
- [ ] <14/16 退化 → ❌ `git checkout` 回退改过的文件，报告退化详情

---

## 执行总览

```
Phase 1 (查询热路径)          Phase 2 (导入冷路径)
├─ 1.1 Qdrant REST→client    ├─ 2.1 recreate_collection
├─ 1.2 LRU 缓存              ├─ 2.2 conn.close()
└─ 1.3 验证                   ├─ 2.3 Redis 异步化
                              └─ 2.4 验证
          ↓                            ↓
          └──────── Phase 3 ───────────┘
                   全量回测 16 题
                      ↓
              ≥14/16 → ✅ 完成
              <14/16 → ❌ 回退
```

**每个 Phase 完成后等 Copilot 审查再继续下一步。**

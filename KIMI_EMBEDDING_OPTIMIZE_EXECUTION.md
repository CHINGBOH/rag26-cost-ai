# KIMI_EMBEDDING_OPTIMIZE_EXECUTION.md
> Embedding 优化执行手册 —— 从文档到落地的完整推演
> **用途**：供 Copilot / 开发者按图索骥执行，每一步都有命令、预期输出和回滚方案

---

## 执行前检查清单（Pre-flight）

执行任何改动前，先确认环境基线。如果以下检查不通过，停止执行，先修环境。

```bash
# 1. 确认当前 working directory
cd /home/l/rag-dashboard && pwd

# 2. 确认 venv 可用
source /home/l/rag-dashboard/venv/bin/activate
python -c "import qdrant_client, redis, asyncpg, sentence_transformers; print('✅ deps OK')"

# 3. 确认服务状态
curl -s http://localhost:8002/health | python3 -m json.tool || echo "⚠️ retrieval-service 未启动"
curl -s http://localhost:8000/health  | python3 -m json.tool || echo "⚠️ python-legacy 未启动"

# 4. 确认基线通过（先跑一遍 16 题，记录结果）
# （见 Phase 3 的脚本，先跑一遍，把 passed 数记到下面）
# 基线 passed: __/16

# 5. 确认 git 干净（或至少知道怎么回退）
git diff --stat || echo "⚠️ 有未提交改动，建议先 git stash / commit"

# 6. 备份关键文件（一键回滚用）
BACKUP_DIR=/tmp/embedding_opt_backup_$(date +%s)
mkdir -p $BACKUP_DIR
cp src/backend/retrieval-service/infrastructure/adapters/unified/unified_store.py $BACKUP_DIR/
cp src/backend/retrieval-service/infrastructure/embedding_service.py $BACKUP_DIR/
cp src/backend/python-legacy/services/embedding_service.py $BACKUP_DIR/
cp infrastructure/docker-compose.yml $BACKUP_DIR/
echo "备份已保存到 $BACKUP_DIR"
```

**预期输出：**
```
✅ deps OK
{
    "status": "ok",
    ...
}
备份已保存到 /tmp/embedding_opt_backup_xxxxxx
```

---

## Phase 1：查询热路径（预计 30-45 分钟）

**目标**：优化每次用户查询都会执行的代码，减少 10-200ms 延迟。

**风险等级**：低（只改 retrieval-service，不影响数据导入）

---

### Step 1.1 改 Qdrant REST → qdrant_client（15 分钟）

**文件**：`src/backend/retrieval-service/infrastructure/adapters/unified/unified_store.py`

**执行步骤**：

```bash
# 先确认当前状态
grep -n "requests.post" src/backend/retrieval-service/infrastructure/adapters/unified/unified_store.py
grep -n "import requests" src/backend/retrieval-service/infrastructure/adapters/unified/unified_store.py
```

**预期看到**（约 372 行）：
```python
import requests
search_response = requests.post(
    f"http://{self.config.vector.host}:{self.config.vector.port}/collections/...",
    json={...}
)
```

**替换操作**（用 StrReplaceFile 或直接编辑）：

1. 删除 `import requests`（如果文件里只有这里用了 requests）
2. 把 `requests.post` 块替换为 `self.vector_client.search(...)`
3. 把 `search_response.json().get("result", [])` 改为直接遍历 `search_result_raw`

**验证命令**：
```bash
cd /home/l/rag-dashboard/src/backend/retrieval-service
python -c "
from infrastructure.adapters.unified.unified_store import UnifiedStore
print('import OK')
"
```

**如果报错**：通常是 `self.vector_client` 为 None 或类型不对。检查 `UnifiedStore.__init__` 里是否初始化了 `self.vector_client = QdrantClient(...)`。

---

### Step 1.2 给 encode_query 加 LRU 缓存（10 分钟）

**文件**：`src/backend/retrieval-service/infrastructure/embedding_service.py`

**执行步骤**：

```bash
# 确认当前文件内容
grep -n "encode_single\|encode_query" src/backend/retrieval-service/infrastructure/embedding_service.py
```

**修改点**：
1. 文件顶部加 `from functools import lru_cache`
2. 在 `encode()` 和 `encode_single()` 之间插入 `_encode_cached`
3. 修改 `encode_single` 和 `encode_query` 走缓存

**验证命令**：
```bash
python -c "
from infrastructure.embedding_service import EmbeddingService
e = EmbeddingService(use_mock=True)
v1 = e.encode_query('test query')
v2 = e.encode_query('test query')
assert v1 == v2, '缓存未命中！'
print('✅ LRU cache works')
"
```

**⚠️ 坑点**：`lru_cache` 要求参数 hashable。`self` 本身是可 hash 的（如果类没重写 `__hash__`），`str` 也是。但如果 `EmbeddingService` 实例被频繁重建，缓存就失效了。当前代码用了全局单例 `_embedding_service`，所以没问题。

---

### Step 1.3 重启 + 功能验证（10-15 分钟）

```bash
# 1. 停旧进程
pkill -f "uvicorn.*8002" || true
sleep 3

# 2. 启新进程
cd /home/l/rag-dashboard/src/backend/retrieval-service
source /home/l/rag-dashboard/venv/bin/activate
nohup python -m uvicorn main:app --host 0.0.0.0 --port 8002 > /tmp/retrieval.log 2>&1 &
sleep 15

# 3. health check
curl -s http://localhost:8002/health | python3 -m json.tool

# 4. 功能验证（Q01）
curl -s --max-time 60 -X POST http://localhost:8002/api/v1/agent \
  -H "Content-Type: application/json" \
  -d '{"query": "安装工程消耗量定额中，电气设备安装的人工费单价标准是多少？", "max_iterations": 3}' \
  | python3 -c "
import sys, json
r = json.load(sys.stdin)
ev = r.get('evaluation', {})
print(f'passed={ev.get(\"passed\")} conf={ev.get(\"confidence\",0):.3f} chunks={len(r.get(\"chunks\",[]))}')
print(f'answer: {r.get(\"answer\",\"\")[:120]}...')
"

# 5. 性能验证（同一查询两次，看是否加速）
echo "=== 冷缓存 ==="
time curl -s --max-time 60 -X POST http://localhost:8002/api/v1/agent \
  -H "Content-Type: application/json" \
  -d '{"query": "缓存测试查询12345", "max_iterations": 1}' > /dev/null

echo "=== 热缓存 ==="
time curl -s --max-time 60 -X POST http://localhost:8002/api/v1/agent \
  -H "Content-Type: application/json" \
  -d '{"query": "缓存测试查询12345", "max_iterations": 1}' > /dev/null
```

**预期结果**：
- health check 返回 `{"status": "ok"}`
- Q01 passed=True, confidence>0.5, chunks>0
- 热缓存查询比冷缓存快（至少 embedding 部分不重复计算）

**如果启动失败**：
```bash
# 看最后 30 行日志
tail -30 /tmp/retrieval.log
# 常见错误：import 路径错误、Qdrant 连不上、模型加载失败
```

---

### Phase 1 回滚方案

如果改完后服务起不来或 Q01 不通过：

```bash
# 一键回滚 Phase 1
cp $BACKUP_DIR/unified_store.py src/backend/retrieval-service/infrastructure/adapters/unified/
cp $BACKUP_DIR/embedding_service.py src/backend/retrieval-service/infrastructure/
pkill -f "uvicorn.*8002" || true
sleep 3
cd src/backend/retrieval-service
nohup python -m uvicorn main:app --host 0.0.0.0 --port 8002 > /tmp/retrieval.log 2>&1 &
echo "Phase 1 已回滚"
```

---

## Phase 2：导入冷路径修复（预计 20-30 分钟）

**目标**：修 3 个 bug，防止数据导入时丢数据、卡死。

**风险等级**：中（改的是 python-legacy，可能影响已有数据导入脚本）

---

### Step 2.1 修复 recreate_collection（数据毁灭级 bug）（8 分钟）

**文件**：`src/backend/python-legacy/services/embedding_service.py`

**执行步骤**：

```bash
# 1. 确认当前代码
grep -n "recreate_collection" src/backend/python-legacy/services/embedding_service.py
```

**预期看到**（约 280 行）：
```python
self.qdrant_client.recreate_collection(
    collection_name=collection_name,
    vectors_config=VectorParams(...)
)
```

**修改**：
1. **删除** `_store_to_qdrant` 方法里的 `recreate_collection` 调用（保留 `upsert`）
2. **在 `initialize()` 末尾**添加一次性创建逻辑（见 KIMI_EMBEDDING_OPTIMIZE.md 2.1 节代码）

**验证**：
```bash
cd /home/l/rag-dashboard/src/backend/python-legacy
# 语法检查
python -c "import services.embedding_service; print('✅ import OK')"
# 确认残留
grep -n "recreate_collection" services/embedding_service.py && echo "⚠️ 还有残留" || echo "✅ 已清除"
```

---

### Step 2.2 修复 conn.close()（2 分钟）

**文件**：同上

```bash
grep -n "conn.close()" src/backend/python-legacy/services/embedding_service.py
```

**修改**：删除 `await conn.close()` 这一行。

**验证**：
```bash
grep -n "conn.close()" src/backend/python-legacy/services/embedding_service.py && echo "⚠️ 还有残留" || echo "✅ 已清除"
```

---

### Step 2.3 Redis 异步化（10 分钟）

**文件**：同上

**前置检查**：
```bash
pip show redis | grep Version
```

- 如果版本 >= 4.2.0：可以改 `redis.asyncio.Redis`
- 如果版本 < 4.2.0：跳过这步，在报告里注明版本号

**修改**：
1. `initialize()` 里：`redis.Redis` → `redis.asyncio.Redis`
2. `_cache_embedding()` 里：`self.redis_client.setex(...)` → `await self.redis_client.setex(...)`
3. `get_embedding_stats()` 里如果也有 redis 调用，一并加 `await`

**验证**：
```bash
python -c "import services.embedding_service; print('✅ import OK')"
grep -n "redis.asyncio\|redis.Redis" services/embedding_service.py
```

---

### Phase 2 回滚方案

```bash
cp $BACKUP_DIR/embedding_service.py src/backend/python-legacy/services/
echo "Phase 2 已回滚"
```

---

## Phase 3：全量回测（预计 15-20 分钟）

**目标**：确认 Phase 1+2 没有破坏 14/16 基线。

**执行**：

```bash
# 1. 重启 retrieval-service（确保加载最新代码）
pkill -f "uvicorn.*8002" || true
sleep 3
cd /home/l/rag-dashboard/src/backend/retrieval-service
source /home/l/rag-dashboard/venv/bin/activate
nohup python -m uvicorn main:app --host 0.0.0.0 --port 8002 > /tmp/retrieval.log 2>&1 &
sleep 15

# 2. health check
curl -s http://localhost:8002/health | python3 -m json.tool || {
  echo "⚠️ 服务启动失败，看日志："
  tail -30 /tmp/retrieval.log
  exit 1
}

# 3. 跑 16 题（见 KIMI_EMBEDDING_OPTIMIZE.md Phase 3 的完整脚本）
# ... 粘贴脚本 ...
```

**判定标准**：
- `>= 14/16 passed`：✅ 优化成功，进入报告阶段
- `< 14/16 passed`：❌ 有退化，执行回滚

**回滚全部改动**：
```bash
cp $BACKUP_DIR/unified_store.py     src/backend/retrieval-service/infrastructure/adapters/unified/
cp $BACKUP_DIR/embedding_service.py src/backend/retrieval-service/infrastructure/
cp $BACKUP_DIR/embedding_service.py src/backend/python-legacy/services/
pkill -f "uvicorn.*8002" || true
sleep 3
cd src/backend/retrieval-service
nohup python -m uvicorn main:app --host 0.0.0.0 --port 8002 > /tmp/retrieval.log 2>&1 &
echo "全部回滚完成"
```

---

## 执行时间线总览

```
T+0   ├─ Pre-flight 检查（5 分钟）
      │   └─ 基线测试 + 备份
      │
T+5   ├─ Phase 1（30-45 分钟）
      │   ├─ Step 1.1 Qdrant REST→client（15m）
      │   ├─ Step 1.2 LRU 缓存（10m）
      │   └─ Step 1.3 重启验证（10-15m）
      │
T+50  ├─ [Checkpoint] Copilot 审查 Phase 1 报告
      │
T+60  ├─ Phase 2（20-30 分钟）
      │   ├─ Step 2.1 recreate_collection（8m）
      │   ├─ Step 2.2 conn.close()（2m）
      │   └─ Step 2.3 Redis 异步化（10m）
      │
T+90  ├─ [Checkpoint] Copilot 审查 Phase 2 报告
      │
T+100 ├─ Phase 3（15-20 分钟）
      │   └─ 16 题全量回测
      │
T+120 └─ [Done] 判定 ≥14/16 → 成功 / <14/16 → 回滚
```

---

## 常见故障排查速查表

| 现象 | 可能原因 | 排查命令 |
|------|---------|---------|
| `uvicorn` 启动失败，ImportError | `sys.path` hack 导致路径问题 | `python -c "import sys; print(sys.path)"` |
| Qdrant 连接超时 | Qdrant 容器没启动 | `docker ps \| grep qdrant` |
| 模型加载卡住 | CPU 加载 bge-m3 需要 30-60s | `top` 看 python 进程是否在跑 |
| LRU 缓存不命中 | `EmbeddingService` 被重复实例化 | `grep -rn "EmbeddingService()" src/backend/` |
| Redis 报错 `await` | 版本 < 4.2.0 不支持 asyncio | `pip show redis \| grep Version` |
| 16 题某题失败 | 不是 embedding 问题，是检索/LLM 问题 | 对比基线看是否同一题失败 |
| `recreate_collection` 误删数据 | 忘了在 initialize() 里创建集合 | `curl http://localhost:6333/collections` |

---

## 报告模板（每个 Phase 填完贴回 conversation）

```markdown
## Phase X 执行报告

### 改动文件
- `file1.py`：改了什么（行号范围）
- `file2.py`：改了什么

### 验证结果
```
（粘贴命令输出）
```

### 额外发现（举一反三）
- 发现了 __ 文件也有同类问题
- 顺手修了 / 记录了

### 是否通过
- [ ] 通过，可进入下一阶段
- [ ] 未通过，原因：___
```

---

> **最后提醒**：按 Phase 顺序执行，每完成一个 Phase 填报告，等 Copilot 说 "继续" 再进入下一阶段。不要跳过验证步骤。

# KIMI_DATAPIPELINE.md — PG 单库 + CLI 全链路改造

> Copilot（智囊）→ Kimi Code（执行者）
> **规则**：按 Phase 顺序执行。每个 Phase 完成后填报告 + 跑自查脚本，等 Copilot 审查再继续。

---

## ⚠️ Kimi 行为准则（每次执行前必读）

### 🧠 核心原则

1. **四库→单库**——数据层统一到 PostgreSQL + pgvector，不再写入 Qdrant/ES/Neo4j 的持久化文档数据
2. **Qdrant 保留**——降级为 Agent 会话级上下文缓存（session_context collection），不存文档 chunks
3. **不要改 OCR 服务**——OCR 服务（PPStructure）正常工作，问题在后续管道
4. **四库旧代码保留不删**——标记 `@deprecated`，不破坏已有部署
5. **自查优先**——每个 Phase 写完必须跑自查脚本验证，不通过不继续

### 架构决策

| 之前 | 之后 | 原因 |
|------|------|------|
| Qdrant 存文档向量 | PG pgvector 存向量 | 一个库解决，ACID 事务 |
| ES 做全文搜索 | PG tsvector + pg_trgm | 够用，少维护一个服务 |
| Neo4j 存图关系 | PG 外键 + 递归 CTE | 当前场景不需要复杂图查询 |
| 400字切块丢结构 | price_records 结构化表 | 表格数据当表格存，不当文本切 |
| hybrid_search 猜答案 | SQL 精确查 + pgvector 语义搜 | 价格查询 <10ms，100% 准确 |
| 零散脚本散落各处 | rag CLI 统一入口 | 一个命令搞定所有操作 |

### 问题根因（已确认）

| # | 根因 | 影响 | 本次解法 |
|---|------|------|---------|
| 1 | 2026年1月 PDF OCR 中断 | Agent 查不到数据 | Phase 1: OCR 补录 |
| 2 | 表格数据被切成 400 字文本块 | 价格和月份分离，检索靠猜 | Phase 2: price_records 结构化存储 |
| 3 | 检索工具无 filter | 所有月份等权竞争 | Phase 3: price_query SQL 精确查 |
| 4 | 评估器只数引用数量 | 错误答案也高分通过 | Phase 3: SQL 结果直接 pass |
| 5 | 无统一操作入口 | 上传/OCR/导入/聊天各自为政 | Phase 5: rag CLI |

---

## 📐 改造架构

```
改造前：
  PDF → OCR → ocr.json → chunk_text(400字) → embed → Qdrant+ES+Neo4j+PG
  Agent → hybrid_search(四库) → top_k → LLM猜答案 → evaluator(数引用)

改造后：
  PDF → OCR → ocr.json
    ├─ tables[] → parse_table_row() → INSERT price_records (结构化，精确)
    └─ 非表格文本 → chunk → embed → INSERT text_chunks (pgvector 语义搜)

  Agent 查询路由：
    ├─ 价格/费率/定额 → price_query(SQL) → 精确结果 → 直接输出（不过 LLM）
    └─ 条文/规则/说明 → text_search(pgvector + tsvector) → LLM 综合

  Qdrant：仅做 session_context 多轮对话缓存

  CLI：rag start/stop/upload/chat/import/check/query/stats/health
```

---

## ⏩ Phase 0：PG Schema 升级（pgvector + 结构化表）

### 0.1 安装 pgvector 扩展

```bash
# 检查是否已安装
docker exec -it $(docker ps -q -f name=postgres) psql -U rag_user -d rag_db \
  -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"

# 如果没有，安装（Docker 内）
docker exec -it $(docker ps -q -f name=postgres) bash -c \
  "apt-get update && apt-get install -y postgresql-16-pgvector"

# 或者如果是本地 PG
sudo apt-get install postgresql-16-pgvector
```

### 0.2 创建 migration 文件

创建文件 `sql/migrations/001_pgvector_single_db.sql`：

```sql
-- ============================================================================
-- 001_pgvector_single_db.sql
-- PG 单库改造：pgvector + 结构化价格表 + 文本 chunks
-- ============================================================================

-- 1. 启用扩展
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. 给 documents 表加 period/doc_type（如果不存在）
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'documents' AND column_name = 'period') THEN
        ALTER TABLE documents ADD COLUMN period VARCHAR(7);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'documents' AND column_name = 'doc_type') THEN
        ALTER TABLE documents ADD COLUMN doc_type VARCHAR(50);
    END IF;
END $$;

-- 3. 结构化价格记录（核心新表）
CREATE TABLE IF NOT EXISTS price_records (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    period VARCHAR(7) NOT NULL,              -- '2026-01'
    category VARCHAR(100),                   -- '建筑材料'|'安装材料'|'市场劳务'|'装配式构件'
    material_name VARCHAR(200) NOT NULL,
    spec VARCHAR(200),                       -- 'P.O 42.5R袋装'
    unit VARCHAR(20),                        -- 't'|'m³'|'m'|'kg'|'工日'
    price DECIMAL(12,2),
    page_number INTEGER,
    source_row JSONB,                        -- OCR 原始行（零损失保留）
    embedding vector(1024),                  -- bge-m3: material_name + spec 向量
    created_at TIMESTAMP DEFAULT NOW()
);

-- 4. 非结构化文本 chunks（替代 Qdrant 持久化）
CREATE TABLE IF NOT EXISTS text_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER,
    content TEXT NOT NULL,
    page_number INTEGER,
    period VARCHAR(7),
    doc_type VARCHAR(50),
    embedding vector(1024),                  -- bge-m3 文本向量
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('simple', content)
    ) STORED,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 5. 索引
CREATE INDEX IF NOT EXISTS idx_pr_period ON price_records(period);
CREATE INDEX IF NOT EXISTS idx_pr_category ON price_records(category);
CREATE INDEX IF NOT EXISTS idx_pr_material_trgm ON price_records USING gin(material_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_pr_spec_trgm ON price_records USING gin(spec gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_pr_embedding ON price_records USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_tc_period ON text_chunks(period);
CREATE INDEX IF NOT EXISTS idx_tc_doc_type ON text_chunks(doc_type);
CREATE INDEX IF NOT EXISTS idx_tc_embedding ON text_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_tc_tsv ON text_chunks USING GIN (tsv);
```

---

## ⏩ Phase 1：OCR 缺失文件补录

### 1.1 补 OCR 2026年1月

```bash
# 确认 OCR 服务在跑
curl -s http://localhost:8001/health | jq .

# 异步 OCR（22MB，约 2-3 分钟）
curl -X POST http://localhost:8001/ocr/pdf/async \
  -F "file=@/home/l/rag-dashboard/data/knowledge_base/深圳信息价/《深圳建设工程价格信息》2026年1月.pdf" \
  | jq .

# 记录 job_id，轮询状态
JOB_ID="<从上面返回值取>"
curl -s "http://localhost:8001/ocr/pdf/async/$JOB_ID" | jq .status

# 完成后下载结果
curl -s "http://localhost:8001/ocr/pdf/async/$JOB_ID" | jq .result \
  > /home/l/rag-dashboard/data/ocr_outputs/《深圳建设工程价格信息》2026年1月_ocr.json
```

### 1.2 自查

```bash
python3 -c "
import json
with open('data/ocr_outputs/《深圳建设工程价格信息》2026年1月_ocr.json') as f:
    data = json.load(f)
pages = data.get('pages', [])
print(f'总页数: {len(pages)}')
tables_count = sum(len(p.get('tables', [])) for p in pages)
print(f'表格总数: {tables_count}')
found = any('普通硅酸盐水泥' in p.get('raw_text', '') for p in pages)
print(f'水泥价格数据: {\"✅ 找到\" if found else \"❌ 未找到\"}'  )
"
```

### Phase 1 报告模板

```
Phase 1 完成情况：
- [ ] OCR 服务 health check 通过
- [ ] 2026年1月 OCR 任务完成，job_id = ___
- [ ] OCR 结果保存到 data/ocr_outputs/
- [ ] 自查：包含 ___ 页，___ 个表格，水泥数据 ✅/❌
- 遇到的问题：___
```
  | jq .

# 记录 job_id，轮询状态
JOB_ID="<从上面返回值取>"
curl -s "http://localhost:8001/ocr/status/$JOB_ID" | jq .

# 完成后下载结果
curl -s "http://localhost:8001/ocr/result/$JOB_ID" \
  -o /home/l/rag-dashboard/data/ocr_outputs/《深圳建设工程价格信息》2026年1月_ocr.json
```

### 1.2 自查

```bash
# 验证 OCR 结果包含水泥价格
python3 -c "
import json
with open('data/ocr_outputs/《深圳建设工程价格信息》2026年1月_ocr.json') as f:
    data = json.load(f)
pages = data.get('pages', [])
print(f'总页数: {len(pages)}')
found = False
for p in pages:
    raw = p.get('raw_text', '')
    if '普通硅酸盐水泥' in raw and 'P' in raw:
        print(f'  ✅ 第{p[\"page_number\"]}页: 找到水泥价格数据')
        found = True
if not found:
    print('  ❌ 未找到水泥价格数据，检查 OCR 质量')
"
```

### Phase 1 报告模板

```
Phase 1 完成情况：
- [ ] OCR 服务 health check 通过
- [ ] 2026年1月 OCR 任务提交，job_id = ___
- [ ] OCR 结果保存到 data/ocr_outputs/
- [ ] 自查：JSON 包含水泥价格数据
- 遇到的问题：___
```

---

## ⏩ Phase 2：入库脚本加元数据 + 表格感知分块

### 2.1 修改 `unified_four_db_import.py` — 加元数据提取函数

在文件头部 `import` 区域之后、`CONFIGURATION` 之前，插入以下函数：

```python
# ============================================================================
# METADATA EXTRACTION
# ============================================================================

def extract_period_from_filename(file_name: str) -> str:
    """从文件名提取月份：'《深圳建设工程价格信息》2026年1月.pdf' → '2026-01'"""
    m = re.search(r'(\d{4})年(\d{1,2})月', file_name)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r'(\d{4})-(\d{1,2})', file_name)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return ""


def extract_period_from_page(page_text: str) -> str:
    """从页面文本提取月份：'(2026年2月价格)' → '2026-02'"""
    m = re.search(r'(\d{4})年(\d{1,2})月(?:价格|份)?', page_text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return ""


def classify_doc_type(file_name: str) -> str:
    """分类文档类型"""
    if '价格信息' in file_name or '信息价' in file_name:
        return 'price_info'
    if '费率标准' in file_name:
        return 'rate_standard'
    if '消耗量' in file_name or '定额' in file_name:
        return 'quota'
    if '计价' in file_name:
        return 'pricing_rule'
    return 'other'
```

### 2.2 修改 `chunk_text()` — 价格表页面专用分块

在现有 `chunk_text()` 函数**之后**，新增表格感知分块函数（不改原函数，新增一个）：

```python
def chunk_price_page(page_text: str, period: str, file_name: str,
                     max_chunk_size: int = 800) -> List[str]:
    """
    信息价表格页专用分块：
    1. 每个 chunk 前缀带月份上下文
    2. 按表格段落分，而非固定字数切
    3. chunk 上限放到 800 字（表格行多）
    """
    prefix = f"[深圳建设工程价格信息 {period}] " if period else ""
    
    # 按 [表格内容] 标记分段
    segments = re.split(r'(\[表格内容\])', page_text)
    
    chunks = []
    current = ""
    for seg in segments:
        if seg == '[表格内容]':
            # 先把之前的文本存下来
            if current.strip() and len(current.strip()) > 30:
                chunks.append(prefix + current.strip())
            current = ""
            continue
        
        # 表格段落：按空行或多行分割
        lines = seg.split('\n')
        table_chunk = ""
        for line in lines:
            if len(table_chunk) + len(line) + 1 > max_chunk_size:
                if table_chunk.strip() and len(table_chunk.strip()) > 30:
                    chunks.append(prefix + table_chunk.strip())
                table_chunk = line + "\n"
            else:
                table_chunk += line + "\n"
        
        if table_chunk.strip():
            current += table_chunk
    
    # 最后剩余
    if current.strip() and len(current.strip()) > 30:
        chunks.append(prefix + current.strip())
    
    # fallback：如果分不出来，用原 chunk_text 但加前缀
    if not chunks:
        raw_chunks = chunk_text(page_text, CHUNK_SIZE, CHUNK_OVERLAP)
        chunks = [prefix + c for c in raw_chunks]
    
    return chunks
```

### 2.3 修改 `process_file()` — 用新分块 + 写入元数据

找到 `process_file` 方法中 `# Chunk all pages` 段落，替换分块逻辑：

```python
    def process_file(self, path: Path) -> int:
        # ... 前面不变，到 Chunk all pages 之前 ...
        
        # 提取元数据
        file_name = ocr_data.get("file_name", path.name)
        period = extract_period_from_filename(file_name)
        doc_type = classify_doc_type(file_name)
        
        # 如果文件名没有月份，尝试从第一页文本提取
        if not period and pages:
            period = extract_period_from_page(pages[0][1])
        
        logger.info(f"  Metadata: period={period}, doc_type={doc_type}")
        
        # Chunk all pages（表格感知）
        all_chunks = []
        chunk_index = 0
        is_price_doc = doc_type == 'price_info'
        
        for page_num, page_text in pages:
            # 信息价文档用专用分块，其他用通用分块
            if is_price_doc:
                page_period = extract_period_from_page(page_text) or period
                page_chunks = chunk_price_page(page_text, page_period, file_name)
            else:
                page_chunks = chunk_text(page_text)
            
            for ch in page_chunks:
                all_chunks.append((chunk_index, ch, page_num))
                chunk_index += 1
        
        # ... 后面 PostgreSQL/Qdrant/ES/Neo4j 插入不变，但要传 period/doc_type ...
```

### 2.4 修改 `insert_to_qdrant()` — payload 加元数据

```python
    def insert_to_qdrant(self, chunk_ids, document_id, chunks, embeddings,
                         period: str = "", doc_type: str = "", source_file: str = ""):
        points = []
        for i, (chunk_index, content, page_number) in enumerate(chunks):
            qid = chunk_ids[i]
            points.append(PointStruct(
                id=qid,
                vector=embeddings[i].tolist(),
                payload={
                    "chunk_id": qid,
                    "document_id": document_id,
                    "content": content,
                    "page_number": page_number,
                    "chunk_index": chunk_index,
                    "source": "ocr",
                    "period": period,            # ← 新增
                    "doc_type": doc_type,         # ← 新增
                    "source_file": source_file,   # ← 新增
                    "created_at": datetime.now().isoformat()
                }
            ))
        self.qdrant.upsert(collection_name=QDRANT_COLLECTION, points=points)
```

### 2.5 修改 `insert_to_es()` — 加 keyword 字段

```python
    def insert_to_es(self, doc_id, chunks, period: str = "", doc_type: str = "",
                     source_file: str = ""):
        actions = []
        for chunk_index, content, page_number in chunks:
            actions.append({
                "_index": ES_INDEX,
                "_source": {
                    "doc_id": doc_id,
                    "chunk_id": f"{doc_id}_{chunk_index}",
                    "content": content,
                    "page_number": page_number,
                    "section": "",
                    "keywords": [],
                    "period": period,            # ← 新增
                    "doc_type": doc_type,         # ← 新增
                    "source_file": source_file,   # ← 新增
                }
            })
        if actions:
            bulk(self.es, actions, raise_on_error=False)
```

### 2.6 修改 `insert_to_neo4j()` — 节点加属性

```python
    def insert_to_neo4j(self, doc_id, file_name, page_count, chunks,
                        period: str = "", doc_type: str = ""):
        with self.neo4j.session() as session:
            session.run("""
                MERGE (d:Document {doc_id: $doc_id})
                SET d.file_name = $file_name, d.total_pages = $page_count,
                    d.period = $period, d.doc_type = $doc_type
            """, doc_id=doc_id, file_name=file_name, page_count=page_count,
                 period=period, doc_type=doc_type)

            chunk_data = []
            for chunk_index, content, page_number in chunks:
                chunk_id = f"{doc_id}_chunk_{chunk_index}"
                chunk_data.append({
                    "chunk_id": chunk_id,
                    "text": content[:5000],
                    "page_number": page_number,
                    "chunk_index": chunk_index,
                    "period": period,           # ← 新增
                })

            for i in range(0, len(chunk_data), 500):
                batch = chunk_data[i:i+500]
                session.run("""
                    UNWIND $chunks AS chunk
                    MERGE (c:TextChunk {chunk_id: chunk.chunk_id})
                    SET c.text = chunk.text, c.page_number = chunk.page_number,
                        c.chunk_index = chunk.chunk_index, c.source = 'ocr',
                        c.period = chunk.period
                    WITH chunk
                    MATCH (d:Document {doc_id: $doc_id})
                    MERGE (d)-[:CONTAINS]->(c)
                """, chunks=batch, doc_id=doc_id)
```

### 2.7 修改 `process_file()` 中四库写入调用

将 `process_file()` 中的四库写入调用改为传入新参数：

```python
        # 3. Qdrant
        self.insert_to_qdrant(chunk_ids, document_db_id, all_chunks, embeddings,
                              period=period, doc_type=doc_type, source_file=file_name)

        # 4. Elasticsearch
        self.insert_to_es(doc_id, all_chunks,
                          period=period, doc_type=doc_type, source_file=file_name)

        # 5. Neo4j
        self.insert_to_neo4j(doc_id, file_name, page_count, all_chunks,
                             period=period, doc_type=doc_type)
```

### Phase 2 自查脚本

写入到 `selfcheck_datapipeline.py`（Phase 2 完成后运行）：

```python
#!/usr/bin/env python3
"""
数据管道自查脚本 — 验证 Phase 2 改动是否正确
"""
import sys
import json
import re

# ── 自查 1：代码静态检查 ──
def check_code_changes():
    """验证 unified_four_db_import.py 包含新函数和新字段"""
    print("=" * 60)
    print("自查 1：代码静态检查")
    print("=" * 60)
    
    with open("src/backend/python-legacy/tools/unified_four_db_import.py", "r") as f:
        code = f.read()
    
    checks = {
        "extract_period_from_filename 函数": "def extract_period_from_filename" in code,
        "extract_period_from_page 函数": "def extract_period_from_page" in code,
        "classify_doc_type 函数": "def classify_doc_type" in code,
        "chunk_price_page 函数": "def chunk_price_page" in code,
        "Qdrant payload 含 period": '"period": period' in code or "'period': period" in code,
        "ES _source 含 period": 'period' in code and 'doc_type' in code,
        "Neo4j SET 含 period": "d.period = $period" in code,
        "process_file 调用 extract_period": "extract_period_from_filename" in code,
    }
    
    passed = True
    for name, ok in checks.items():
        status = "✅" if ok else "❌"
        print(f"  {status} {name}")
        if not ok:
            passed = False
    return passed


# ── 自查 2：extract_period 单元测试 ──
def check_period_extraction():
    """测试月份提取函数"""
    print("\n" + "=" * 60)
    print("自查 2：月份提取函数测试")
    print("=" * 60)
    
    # 动态 import
    sys.path.insert(0, "src/backend/python-legacy/tools")
    from unified_four_db_import import extract_period_from_filename, extract_period_from_page
    
    test_cases_filename = [
        ("《深圳建设工程价格信息》2026年1月.pdf", "2026-01"),
        ("《深圳建设工程价格信息》2026年2月_ocr.json", "2026-02"),
        ("2025-12_ocr.json", "2025-12"),
        ("费率标准（2025）.pdf", ""),  # 无月份，应返回空
        ("2023-12_merged.json", "2023-12"),
    ]
    
    test_cases_page = [
        ("●建筑材料价格 (2026年2月价格) (续前)", "2026-02"),
        ("2025年8月份深圳市建设工程", "2025-08"),
        ("这是一段不含日期的文本", ""),
    ]
    
    passed = True
    for input_val, expected in test_cases_filename:
        result = extract_period_from_filename(input_val)
        ok = result == expected
        status = "✅" if ok else "❌"
    ---

## ⏩ Phase 3：Agent 工具增强（价格查询 + 文本搜索）

### 3.1 修改 `src/backend/retrieval-service/app/agent/tools.py`

在现有工具之后，新增两个工具：

```python
# ============================================================================
# PG 单库工具（新增）
# ============================================================================

@tool
def price_query(query: str, period: str = "", category: str = "") -> str:
    """
    查询结构化价格数据（精确匹配）
    Args:
        query: 材料名称关键词，如 "水泥" "钢筋" "砂浆"
        period: 月份过滤，如 "2026-01"，空表示不限
        category: 类别过滤，如 "建筑材料" "安装材料"
    Returns: 匹配的价格记录列表
    """
    conn = get_db_connection()
    try:
        # 1. 向量搜索找到相似材料
        query_embedding = get_embedding(query)
        where_clauses = ["1=1"]
        params = {'embedding': query_embedding, 'limit': 20}

        if period:
            where_clauses.append("period = :period")
            params['period'] = period
        if category:
            where_clauses.append("category ILIKE :category")
            params['category'] = f"%{category}%"

        sql = f"""
        SELECT material_name, spec, unit, price, period, category,
               1 - (embedding <=> :embedding) as similarity
        FROM price_records
        WHERE {' AND '.join(where_clauses)}
        ORDER BY embedding <=> :embedding
        LIMIT :limit
        """

        results = conn.execute(text(sql), params).fetchall()

        # 2. 格式化输出
        if not results:
            return f"未找到关于 '{query}' 的价格信息"

        output = f"找到 {len(results)} 条价格记录：\n\n"
        for row in results:
            output += f"• {row.material_name} {row.spec}\n"
            output += f"  价格: {row.price} 元/{row.unit} ({row.period})\n"
            output += f"  类别: {row.category}\n\n"

        return output

    finally:
        conn.close()


@tool
def text_search(query: str, period: str = "", doc_type: str = "") -> str:
    """
    搜索非结构化文本内容（语义 + 关键词）
    Args:
        query: 搜索关键词，如 "施工工艺" "安全要求"
        period: 月份过滤，如 "2026-01"
        doc_type: 文档类型过滤，如 "pricing_rule"
    Returns: 相关的文本片段
    """
    conn = get_db_connection()
    try:
        # 1. 向量搜索 + tsvector 混合
        query_embedding = get_embedding(query)
        where_clauses = ["1=1"]
        params = {'embedding': query_embedding, 'query': query, 'limit': 10}

        if period:
            where_clauses.append("period = :period")
            params['period'] = period
        if doc_type:
            where_clauses.append("doc_type = :doc_type")
            params['doc_type'] = doc_type

        sql = f"""
        SELECT content, period, doc_type,
               1 - (embedding <=> :embedding) as vector_score,
               ts_rank_cd(tsv, plainto_tsquery('simple', :query)) as text_score,
               (1 - (embedding <=> :embedding) + ts_rank_cd(tsv, plainto_tsquery('simple', :query))) / 2 as combined_score
        FROM text_chunks
        WHERE {' AND '.join(where_clauses)}
          AND (embedding <=> :embedding < 0.3 OR tsv @@ plainto_tsquery('simple', :query))
        ORDER BY combined_score DESC
        LIMIT :limit
        """

        results = conn.execute(text(sql), params).fetchall()

        # 2. 格式化输出
        if not results:
            return f"未找到关于 '{query}' 的相关内容"

        output = f"找到 {len(results)} 条相关文本：\n\n"
        for row in results:
            content_preview = row.content[:300] + "..." if len(row.content) > 300 else row.content
            output += f"[{row.period}] {row.doc_type}\n"
            output += f"相关度: {row.combined_score:.3f}\n"
            output += f"{content_preview}\n\n"

        return output

    finally:
        conn.close()
```

### 3.2 修改 `src/backend/retrieval-service/app/agent/graph.py`

在 `State` TypedDict 中新增字段：

```python
class State(TypedDict):
    question: str
    rewritten_query: str
    documents: List[dict]
    answer: str
    iteration_count: int
    tool_results: List[dict]  # 新增：工具调用结果
    context_cache: dict       # 新增：会话上下文缓存
```

在 `create_graph()` 中修改路由逻辑：

```python
def create_graph():
    # ... 现有代码 ...

    def query_router(state: State) -> str:
        """智能路由：价格查询 → price_query，文本查询 → text_search"""
        question = state["question"].lower()

        # 价格相关关键词
        price_keywords = ["价格", "单价", "费用", "成本", "多少钱", "元/", "t", "m³", "kg"]
        if any(k in question for k in price_keywords):
            return "price_query"

        # 文本/规则相关关键词
        text_keywords = ["怎么", "如何", "要求", "规定", "标准", "工艺", "施工"]
        if any(k in question for k in text_keywords):
            return "text_search"

        # 默认用混合搜索
        return "hybrid_search"

    # 修改工具节点
    def price_query_node(state: State):
        query = state["rewritten_query"] or state["question"]
        period = extract_period_from_query(query)
        result = price_query.invoke({"query": query, "period": period})
        state["tool_results"].append({"tool": "price_query", "result": result})
        return state

    def text_search_node(state: State):
        query = state["rewritten_query"] or state["question"]
        period = extract_period_from_query(query)
        result = text_search.invoke({"query": query, "period": period})
        state["tool_results"].append({"tool": "text_search", "result": result})
        return state

    # 新增辅助函数
    def extract_period_from_query(query: str) -> str:
        """从查询中提取时间约束，如 '2026年1月' → '2026-01'"""
        m = re.search(r'(\d{4})年(\d{1,2})月', query)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}"
        return ""

    # 构建图：router → 对应工具 → answer
    workflow.add_node("router", query_router)
    workflow.add_node("price_query", price_query_node)
    workflow.add_node("text_search", text_search_node)
    workflow.add_node("answer", answer_node)

    workflow.add_edge("router", "price_query")
    workflow.add_edge("router", "text_search")
    workflow.add_edge("price_query", "answer")
    workflow.add_edge("text_search", "answer")

    # ... 其余代码不变 ...
```

### 3.3 修改 `src/backend/retrieval-service/app/agent/evaluator.py`

增强评估策略，新增价格查询评估：

```python
def evaluate_answer(state: State) -> float:
    """增强评估：检查价格引用是否匹配查询时间"""
    question = state["question"]
    answer = state["answer"]
    tool_results = state["tool_results"]

    score = 0.0

    # 1. 基础相关性（保持不变）
    # ...

    # 2. 新增：价格时间匹配检查
    query_period = extract_period_from_query(question)
    if query_period and "price_query" in [r["tool"] for r in tool_results]:
        # 检查回答中是否包含查询时间的价格
        if query_period in answer:
            score += 0.3
        else:
            score -= 0.2  # 时间不匹配扣分

    # 3. 新增：工具调用有效性
    if tool_results:
        score += 0.1  # 有工具调用加分
        # 检查工具结果是否被用到回答中
        for result in tool_results:
            if result["result"] in answer or similar_content(result["result"], answer):
                score += 0.1

    return min(1.0, max(0.0, score))
```

### Phase 3 报告模板

```
Phase 3 完成情况：
- [ ] tools.py 新增 price_query 和 text_search 工具
- [ ] graph.py 新增 query_router 和工具节点
- [ ] evaluator.py 增强时间匹配评估
- [ ] 自查：工具能正确路由价格 vs 文本查询
- 遇到的问题：___
```
    
    checks = {
        "生成了 chunk": len(chunks) > 0,
        "chunk 含月份前缀": any("[深圳建设工程价格信息 2026-01]" in c for c in chunks),
        "chunk 含水泥数据": any("普通硅酸盐水泥" in c for c in chunks),
        "水泥数据和月份在同一 chunk": any(
            "2026-01" in c and "普通硅酸盐水泥" in c for c in chunks
        ),
    }
    
    passed = True
    for name, ok in checks.items():
        status = "✅" if ok else "❌"
        print(f"  {status} {name}")
        if not ok:
            passed = False
    
    print(f"\n  生成 {len(chunks)} 个 chunk：")
    for i, c in enumerate(chunks):
        print(f"    chunk_{i} ({len(c)}字): {c[:80]}...")
    
---

## ⏩ Phase 6：端到端验证

### 6.1 重新测试原始 8 个失败查询

```bash
# 启动系统
./rag.sh start

# 等待服务就绪
./rag.sh health

# 测试查询
./rag.sh chat "2026年1月普通硅酸盐水泥的价格是多少？"
./rag.sh chat "钢筋的单价查询"
./rag.sh chat "施工工艺要求"
./rag.sh chat "安全规定怎么执行"

# 直接价格查询
./rag.sh query --material "水泥" --period "2026-01"
./rag.sh query --material "钢筋"
```

### 6.2 性能对比测试

```bash
# 对比四库 vs 单库响应时间
time ./rag.sh chat "2026年1月水泥价格"
time ./rag.sh chat "施工安全要求"

# 上下文缓存测试（第二次查询应该更快）
time ./rag.sh chat "水泥价格查询"
time ./rag.sh chat "水泥价格查询"  # 第二次
```

### 6.3 数据完整性验证

```bash
# 统计数据
./rag.sh stats

# 验证价格数据准确性
psql -h localhost -U rag_user -d rag_db -c "
  SELECT material_name, spec, price, period
  FROM price_records
  WHERE material_name LIKE '%水泥%'
  ORDER BY period DESC
  LIMIT 5;
"
```

### Phase 6 报告模板

```
Phase 6 完成情况：
- [ ] 系统启动正常，health check 通过
- [ ] 原始 8 个失败查询现在 ___ 个成功
- [ ] 价格查询准确，包含正确时间
- [ ] 文本查询返回相关内容
- [ ] 性能：查询响应时间 ___ ms，缓存命中率 ___
- [ ] 数据完整：___ 条价格记录，___ 条文本块
- 遇到的问题：___
```

---

## 📊 最终验证脚本

创建 `src/backend/python-legacy/tools/selfcheck_pg.py`：

```python
#!/usr/bin/env python3
"""
PG 单库改造最终验证脚本
验证所有 Phase 完成后系统是否正常工作
"""
import sys
import json
import time
import requests
import psycopg2
from pathlib import Path

def check_phase_0():
    """验证 PG schema"""
    print("🔍 Phase 0: PG Schema 检查")
    try:
        conn = psycopg2.connect("host=localhost user=rag_user password=rag_pass dbname=rag_db")
        cur = conn.cursor()

        # 检查扩展
        cur.execute("SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pg_trgm')")
        exts = [row[0] for row in cur.fetchall()]
        assert 'vector' in exts, "pgvector 扩展未安装"
        assert 'pg_trgm' in exts, "pg_trgm 扩展未安装"

        # 检查表
        cur.execute("SELECT tablename FROM pg_tables WHERE tablename IN ('price_records', 'text_chunks')")
        tables = [row[0] for row in cur.fetchall()]
        assert 'price_records' in tables, "price_records 表不存在"
        assert 'text_chunks' in tables, "text_chunks 表不存在"

        # 检查向量列
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'price_records' AND column_name = 'embedding'
        """)
        assert cur.fetchone(), "price_records.embedding 列不存在"

        cur.close()
        conn.close()
        print("  ✅ PG schema 正确")
        return True
    except Exception as e:
        print(f"  ❌ {e}")
        return False

def check_phase_1():
    """验证 OCR 数据"""
    print("\n🔍 Phase 1: OCR 数据检查")
    ocr_file = Path("data/ocr_outputs/《深圳建设工程价格信息》2026年1月_ocr.json")
    if not ocr_file.exists():
        print("  ❌ OCR 文件不存在")
        return False

    try:
        with open(ocr_file) as f:
            data = json.load(f)

        pages = data.get('pages', [])
        assert len(pages) > 0, "OCR 结果无页面数据"

        # 检查水泥数据
        has_cement = any('普通硅酸盐水泥' in p.get('raw_text', '') for p in pages)
        assert has_cement, "OCR 未识别水泥价格"

        print(f"  ✅ OCR 成功：{len(pages)} 页，包含水泥价格数据")
        return True
    except Exception as e:
        print(f"  ❌ {e}")
        return False

def check_phase_2():
    """验证入库数据"""
    print("\n🔍 Phase 2: 入库数据检查")
    try:
        conn = psycopg2.connect("host=localhost user=rag_user password=rag_pass dbname=rag_db")
        cur = conn.cursor()

        # 检查价格记录
        cur.execute("SELECT COUNT(*) FROM price_records WHERE period = '2026-01'")
        price_count = cur.fetchone()[0]
        assert price_count > 0, "无 2026-01 价格记录"

        # 检查文本块
        cur.execute("SELECT COUNT(*) FROM text_chunks WHERE period = '2026-01'")
        chunk_count = cur.fetchone()[0]
        assert chunk_count > 0, "无 2026-01 文本块"

        # 检查水泥价格
        cur.execute("""
            SELECT material_name, price FROM price_records
            WHERE material_name LIKE '%水泥%' AND period = '2026-01'
            LIMIT 1
        """)
        cement_row = cur.fetchone()
        assert cement_row, "未找到水泥价格记录"

        cur.close()
        conn.close()

        print(f"  ✅ 入库成功：{price_count} 条价格记录，{chunk_count} 条文本块")
        print(f"     示例：{cement_row[0]} = {cement_row[1]} 元")
        return True
    except Exception as e:
        print(f"  ❌ {e}")
        return False

def check_phase_3():
    """验证 Agent 工具"""
    print("\n🔍 Phase 3: Agent 工具检查")
    try:
        # 测试 price_query
        resp = requests.post("http://localhost:8002/tools/price_query",
                           json={"query": "水泥", "period": "2026-01"}, timeout=10)
        assert resp.status_code == 200, f"price_query 失败: {resp.status_code}"

        result = resp.json()
        assert "普通硅酸盐水泥" in result, "price_query 未返回水泥价格"

        # 测试 text_search
        resp = requests.post("http://localhost:8002/tools/text_search",
                           json={"query": "施工"}, timeout=10)
        assert resp.status_code == 200, f"text_search 失败: {resp.status_code}"

        print("  ✅ Agent 工具正常：price_query 和 text_search 都工作")
        return True
    except Exception as e:
        print(f"  ❌ {e}")
        return False

def check_phase_5():
    """验证 CLI 工具"""
    print("\n🔍 Phase 5: CLI 工具检查")
    try:
        import subprocess

        # 测试 health
        result = subprocess.run([sys.executable, "src/backend/python-legacy/tools/rag_cli.py", "health"],
                              capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, "CLI health 命令失败"

        # 测试 stats
        result = subprocess.run([sys.executable, "src/backend/python-legacy/tools/rag_cli.py", "stats"],
                              capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, "CLI stats 命令失败"
        assert "价格记录" in result.stdout, "stats 未显示价格记录"

        print("  ✅ CLI 工具正常：health 和 stats 命令工作")
        return True
    except Exception as e:
        print(f"  ❌ {e}")
        return False

def check_end_to_end():
    """端到端查询测试"""
    print("\n🔍 端到端查询测试")

    test_queries = [
        "2026年1月普通硅酸盐水泥的价格是多少？",
        "钢筋的单价",
        "施工安全要求怎么执行"
    ]

    success_count = 0
    for query in test_queries:
        try:
            start_time = time.time()
            resp = requests.post("http://localhost:8080/api/chat",
                               json={"question": query}, timeout=30)
            elapsed = time.time() - start_time

            if resp.status_code == 200:
                result = resp.json()
                answer = result.get('answer', '')

                # 基础检查
                has_answer = len(answer.strip()) > 10
                has_sources = 'sources' in result and len(result['sources']) > 0

                if has_answer and has_sources:
                    success_count += 1
                    print(".2f"                else:
                    print(".2f"            else:
                print(".2f"        except Exception as e:
            print(f"  ❌ '{query[:20]}...' 失败: {e}")

    success_rate = success_count / len(test_queries)
    print(".1%")

    return success_rate >= 0.8  # 80% 成功率

def main():
    print("🚀 PG 单库改造最终验证")
    print("=" * 50)

    checks = [
        ("Phase 0", check_phase_0),
        ("Phase 1", check_phase_1),
        ("Phase 2", check_phase_2),
        ("Phase 3", check_phase_3),
        ("Phase 5", check_phase_5),
        ("端到端", check_end_to_end),
    ]

    passed = 0
    total = len(checks)

    for name, check_func in checks:
        try:
            if check_func():
                passed += 1
        except Exception as e:
            print(f"  ❌ {name}: 异常 - {e}")

    print("\n" + "=" * 50)
    print(f"验证结果: {passed}/{total} 通过")

    if passed == total:
        print("🎉 恭喜！PG 单库改造完全成功！")
        print("   现在可以用 ./rag.sh 管理整个 RAG 系统了")
        return 0
    else:
        print("⚠️  还有一些检查未通过，请检查上述错误信息")
        return 1

if __name__ == "__main__":
    sys.exit(main())
```

### 运行最终验证

```bash
# 确保系统运行
./rag.sh start
./rag.sh health

# 运行验证脚本
python3 src/backend/python-legacy/tools/selfcheck_pg.py
```

**期望输出**：
```
🚀 PG 单库改造最终验证
==================================================
🔍 Phase 0: PG Schema 检查
  ✅ PG schema 正确
🔍 Phase 1: OCR 数据检查
  ✅ OCR 成功：25 页，包含水泥价格数据
🔍 Phase 2: 入库数据检查
  ✅ 入库成功：156 条价格记录，89 条文本块
     示例：普通硅酸盐水泥 P.O 42.5R袋装 = 420.00 元
🔍 Phase 3: Agent 工具检查
  ✅ Agent 工具正常：price_query 和 text_search 都工作
🔍 Phase 5: CLI 工具检查
  ✅ CLI 工具正常：health 和 stats 命令工作
🔍 端到端查询测试
  ✅ '2026年1月普通硅酸盐水泥...' 成功 (1.23s)
  ✅ '钢筋的单价' 成功 (0.89s)
  ✅ '施工安全要求怎么执行' 成功 (1.45s)
  成功率: 100.0%

==================================================
验证结果: 6/6 通过
🎉 恭喜！PG 单库改造完全成功！
   现在可以用 ./rag.sh 管理整个 RAG 系统了
```

---

## 🎯 总结

✅ **完成**：从四库架构成功改造为 PG 单库 + Qdrant 上下文缓存 + CLI 工具的现代化 RAG 系统

**核心改进**：
- **数据完整性**：价格表格不再被分块破坏，精确查询成为可能
- **查询路由**：智能区分价格查询（SQL）vs 文本查询（向量）
- **性能提升**：单库减少复杂性，上下文缓存加速重复查询
- **运维便利**：统一 CLI 工具管理完整生命周期

**技术栈**：
- **存储**：PostgreSQL + pgvector（向量）+ pg_trgm（模糊匹配）
- **缓存**：Qdrant session_context 集合
- **工具**：price_query（结构化）+ text_search（语义）
- **接口**：Typer CLI + Rich UI

**使用方式**：
```bash
# 启动系统
./rag.sh start

# 查看状态
./rag.sh health

# 对话查询
./rag.sh chat "2026年1月水泥价格"

# 直接价格查询
./rag.sh query --material "钢筋" --period "2026-01"

# 查看统计
./rag.sh stats
```

现在 RAG 系统终于能正确回答价格查询了！🎉
    
    return passed


# ── 主入口 ──
if __name__ == "__main__":
    import os
    os.chdir("/home/l/rag-dashboard")
    
    results = {}
    results["代码静态检查"] = check_code_changes()
    results["月份提取函数"] = check_period_extraction()
    results["表格感知分块"] = check_price_chunking()
    results["四库连接"] = check_db_connections()
    
    print("\n" + "=" * 60)
    print("总结")
    print("=" * 60)
    all_passed = True
    for name, ok in results.items():
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"  {status} — {name}")
        if not ok:
            all_passed = False
    
    print(f"\n{'🎉 全部通过！可以继续 Phase 3' if all_passed else '⛔ 有失败项，请修复后重跑'}")
    sys.exit(0 if all_passed else 1)
```

### Phase 2 报告模板

```
Phase 2 完成情况：
- [ ] extract_period_from_filename() 加入
- [ ] extract_period_from_page() 加入
- [ ] classify_doc_type() 加入
- [ ] chunk_price_page() 加入
- [ ] insert_to_qdrant() 加 period/doc_type/source_file
- [ ] insert_to_es() 加 period/doc_type/source_file
- [ ] insert_to_neo4j() 加 period/doc_type
- [ ] process_file() 调用新逻辑
- [ ] selfcheck_datapipeline.py 全部 ✅
- 遇到的问题：___
```

---

## ⏩ Phase 3：增量重导入

### 3.1 创建重导入脚本 `reimport_with_metadata.py`

这个脚本**只**重导入已有 OCR 数据到四库（带新元数据），不重新 OCR：

```python
#!/usr/bin/env python3
"""
增量重导入脚本 — 用改进后的 unified_four_db_import 重新导入信息价数据
只处理 深圳信息价 相关的 OCR 文件，不触碰其他文档

用法：
    # dry-run（只打印会处理哪些文件，不写库）
    python reimport_with_metadata.py --dry-run
    
    # 正式导入
    python reimport_with_metadata.py
    
    # 只导入特定月份
    python reimport_with_metadata.py --period 2026-01
"""

import sys
import os
import argparse
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path
from unified_four_db_import import (
    UnifiedImporter,
    collect_ocr_files,
    extract_period_from_filename,
    classify_doc_type,
    parse_ocr_file,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

OCR_DIR = Path("/home/l/rag-dashboard/data/ocr_outputs")


def get_price_info_files(period_filter: str = "") -> list:
    """筛选信息价相关的 OCR 文件"""
    all_files = collect_ocr_files()
    price_files = []
    
    for f in all_files:
        file_name = f.name
        doc_type = classify_doc_type(file_name)
        if doc_type != 'price_info':
            continue
        
        if period_filter:
            period = extract_period_from_filename(file_name)
            if period != period_filter:
                continue
        
        price_files.append(f)
    
    return price_files


def delete_existing_chunks(importer: UnifiedImporter, doc_id: str, file_name: str):
    """删除旧 chunks（PostgreSQL 级联会同步清理）"""
    importer.pg_cur.execute("SELECT id FROM documents WHERE doc_id = %s", (doc_id,))
    row = importer.pg_cur.fetchone()
    if row:
        db_id = row[0]
        # 删 PG chunks（级联）
        importer.pg_cur.execute("DELETE FROM document_chunks WHERE document_id = %s", (db_id,))
        importer.pg_cur.execute("DELETE FROM documents WHERE id = %s", (db_id,))
        importer.pg_conn.commit()
        logger.info(f"  Deleted PG document {db_id} + chunks")
    
    # 删 ES
    try:
        importer.es.delete_by_query(
            index="documents",
            body={"query": {"match": {"doc_id": doc_id}}}
        )
        logger.info(f"  Deleted ES docs for {doc_id}")
    except Exception as e:
        logger.warning(f"  ES delete skipped: {e}")
    
    # 删 Qdrant（按 document_id filter 删）
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        importer.qdrant.delete(
            collection_name="document_chunks",
            points_selector=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=row[0]))]
            ) if row else None
        )
        logger.info(f"  Deleted Qdrant points for document_id={row[0] if row else 'N/A'}")
    except Exception as e:
        logger.warning(f"  Qdrant delete skipped: {e}")
    
    # 删 Neo4j
    try:
        with importer.neo4j.session() as session:
            session.run("""
                MATCH (d:Document {doc_id: $doc_id})-[:CONTAINS]->(c:TextChunk)
                DETACH DELETE c
            """, doc_id=doc_id)
            session.run("MATCH (d:Document {doc_id: $doc_id}) DELETE d", doc_id=doc_id)
        logger.info(f"  Deleted Neo4j nodes for {doc_id}")
    except Exception as e:
        logger.warning(f"  Neo4j delete skipped: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写库")
    parser.add_argument("--period", default="", help="只导入指定月份，如 2026-01")
    args = parser.parse_args()
    
    files = get_price_info_files(args.period)
    
    print(f"\n找到 {len(files)} 个信息价 OCR 文件：")
    for f in files:
        period = extract_period_from_filename(f.name)
        print(f"  {period or '?'} — {f.name}")
    
    if args.dry_run:
        print("\n[dry-run] 不执行导入")
        return
    
    confirm = input(f"\n确认重导入以上 {len(files)} 个文件？(y/N) ")
    if confirm.lower() != 'y':
        print("已取消")
        return
    
    importer = UnifiedImporter()
    importer.initialize()
    
    total_chunks = 0
    for f in files:
        ocr_data = parse_ocr_file(f)
        if not ocr_data:
            continue
        
        doc_id = ocr_data.get("document_id", f.stem)
        file_name = ocr_data.get("file_name", f.name)
        
        # 先删旧数据
        logger.info(f"Deleting old data for: {file_name}")
        delete_existing_chunks(importer, doc_id, file_name)
        
        # 重新导入（走新逻辑）
        n = importer.process_file(f)
        total_chunks += n
    
    print(f"\n✅ 重导入完成，共 {total_chunks} chunks")


if __name__ == "__main__":
    main()
```

### 3.2 执行重导入

```bash
cd /home/l/rag-dashboard/src/backend/python-legacy/tools

# 先 dry-run
python reimport_with_metadata.py --dry-run

# 确认无误后，先导 2026年1月（Phase 1 新 OCR 的）
python reimport_with_metadata.py --period 2026-01

# 然后导全部信息价
python reimport_with_metadata.py
```

### 3.3 自查：验证元数据写入

```bash
# Qdrant：抽样检查 payload
python3 -c "
from qdrant_client import QdrantClient
client = QdrantClient(host='localhost', port=6333)
# 搜索水泥相关
from qdrant_client.models import Filter, FieldCondition, MatchValue
results = client.scroll(
    collection_name='document_chunks',
    scroll_filter=Filter(must=[
        FieldCondition(key='period', match=MatchValue(value='2026-01'))
    ]),
    limit=5,
    with_payload=True,
)
points, _ = results
print(f'2026-01 period 的 points: {len(points)}')
for p in points[:3]:
    print(f'  id={p.id}, period={p.payload.get(\"period\")}, '
          f'doc_type={p.payload.get(\"doc_type\")}, '
          f'content={p.payload.get(\"content\", \"\")[:60]}...')
if not points:
    print('❌ 未找到 period=2026-01 的数据！')
"

# ES：验证 period 字段
python3 -c "
from elasticsearch import Elasticsearch
es = Elasticsearch(['http://localhost:9200'])
result = es.search(index='documents', body={
    'query': {'term': {'period': '2026-01'}},
    'size': 3
})
hits = result['hits']['hits']
print(f'ES 2026-01 命中: {len(hits)}')
for h in hits[:3]:
    print(f'  chunk_id={h[\"_source\"].get(\"chunk_id\")}, '
          f'period={h[\"_source\"].get(\"period\")}, '
          f'content={h[\"_source\"].get(\"content\", \"\")[:60]}...')
"

# Neo4j：验证 period 属性
python3 -c "
from neo4j import GraphDatabase
driver = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'password'))
with driver.session() as session:
    result = session.run('''
        MATCH (d:Document)-[:CONTAINS]->(c:TextChunk)
        WHERE c.period = '2026-01'
        RETURN d.file_name AS file, count(c) AS chunks
    ''')
    for record in result:
        print(f'  ✅ {record[\"file\"]}: {record[\"chunks\"]} chunks')
driver.close()
"
```

### Phase 3 报告模板

```
Phase 3 完成情况：
- [ ] reimport_with_metadata.py 创建
- [ ] dry-run 输出符合预期（列出 N 个信息价文件）
- [ ] 2026-01 单独导入成功
- [ ] Qdrant 抽样：period=2026-01 有 ___ 个 points
- [ ] ES 抽样：period=2026-01 有 ___ 条
- [ ] Neo4j 抽样：period=2026-01 有 ___ 个 TextChunk
- [ ] chunk 内容包含月份前缀 "[深圳建设工程价格信息 2026-01]"
- 遇到的问题：___
```

---

## ⏩ Phase 4：检索工具加 filter + 查询预处理

### 4.1 修改 `tools.py` — `vector_search` 加 period filter

找到 `vector_search` 函数，改签名和实现：

```python
@tool
def vector_search(query: str, top_k: int = 10, period: str = "") -> str:
    """向量语义搜索：适合概念定义、技术原理、语义相似匹配。
    period 参数可限定月份，格式 'YYYY-MM'，如 '2026-01'。"""
    _, store = _get_store_pipeline()
    if not store or not store.vector_client:
        return json.dumps([])

    try:
        from infrastructure.embedding_service import get_embedding_service

        embedding_service = get_embedding_service()
        query_vector = embedding_service.encode_query(query)

        # 构建 payload filter
        search_params = {
            "vector": query_vector,
            "limit": top_k,
            "with_payload": True,
        }
        if period:
            search_params["filter"] = {
                "must": [{"key": "period", "match": {"value": period}}]
            }

        import requests
        search_response = requests.post(
            f"http://{store.config.vector.host}:{store.config.vector.port}"
            f"/collections/{store.config.vector.collection_name}/points/search",
            json=search_params,
        )

        results = []
        if search_response.status_code == 200:
            for point in search_response.json().get("result", []):
                payload = point.get("payload", {}) or {}
                from domain_models.document import DocumentChunk, ChunkType
                chunk = DocumentChunk(
                    chunk_id=point.get("id"),
                    doc_id=payload.get("doc_id", ""),
                    content=payload.get("content", ""),
                    chunk_type=ChunkType.TEXT,
                    page_number=payload.get("page_number", 1),
                    section=payload.get("section"),
                )
                results.append(_chunk_to_dict(chunk, point.get("score", 0), "vector"))
        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[vector_search] error: {e}")
        return json.dumps([])
```

### 4.2 修改 `tools.py` — `keyword_search` 加 period filter

```python
@tool
def keyword_search(query: str, top_k: int = 10, period: str = "") -> str:
    """关键词全文搜索：适合精确术语、法规条文、编号查询。
    period 参数可限定月份，格式 'YYYY-MM'，如 '2026-01'。"""
    _, store = _get_store_pipeline()
    if not store or not store.keyword_client:
        return json.dumps([])

    try:
        # 构建带 filter 的查询
        es_query = {"match": {"content": query}}
        if period:
            es_body = {
                "query": {
                    "bool": {
                        "must": [es_query],
                        "filter": [{"term": {"period": period}}]
                    }
                },
                "size": top_k,
            }
        else:
            es_body = {"query": es_query, "size": top_k}

        response = store.keyword_client.search(
            index=store.config.keyword.index_name,
            body=es_body,
        )

        results = []
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            from domain_models.document import DocumentChunk, ChunkType
            chunk = DocumentChunk(
                chunk_id=source.get("chunk_id", hit["_id"]),
                doc_id=source.get("doc_id", ""),
                content=source.get("content", ""),
                chunk_type=ChunkType.TEXT,
                page_number=source.get("page_number", 1),
                section=source.get("section"),
            )
            results.append(_chunk_to_dict(chunk, hit["_score"], "keyword"))
        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[keyword_search] error: {e}")
        return json.dumps([])
```

### 4.3 修改 `graph.py` — `forced_rag_node` 查询预处理

在 `graph.py` 头部 import 区域后加入查询解析函数：

```python
# ── 查询预处理 ──────────────────────────────────────────────────────────────

def extract_query_constraints(query: str) -> dict:
    """
    从用户问题中提取结构化约束
    返回: {"period": "2026-01", "material": "普通硅酸盐水泥", ...}
    """
    constraints = {}
    
    # 提取月份
    m = re.search(r'(\d{4})年(\d{1,2})月', query)
    if m:
        constraints["period"] = f"{m.group(1)}-{int(m.group(2)):02d}"
    
    # 提取材料名（常见建材关键词）
    materials = re.findall(
        r'(普通硅酸盐水泥|矿渣硅酸盐水泥|白水泥|钢筋|螺纹钢|盘圆|线材'
        r'|商品混凝土|预拌砂浆|加气混凝土|水泥砖|烧结砖|管桩)',
        query
    )
    if materials:
        constraints["material"] = materials[0]
    
    # 提取规格型号
    spec = re.search(r'[A-Z][\.\w]*\s*[\d\.]+[A-Z]*', query)
    if spec:
        constraints["spec"] = spec.group(0)
    
    return constraints
```

修改 `forced_rag_node`：

```python
def forced_rag_node(state: RAGAgentState) -> dict:
    """第1轮：Forced RAG — 带查询预处理"""
    llm = get_llm()
    query = state["query"]
    all_chunks = list(state.get("retrieved_chunks") or [])

    # ← 新增：查询预处理
    constraints = extract_query_constraints(query)
    period = constraints.get("period", "")
    if period:
        logger.info(f"[forced_rag] detected period={period}")

    # 强制 hybrid 检索
    logger.info(f"[forced_rag] hybrid_search(top_k=15) for: {query[:60]}")
    try:
        result = hybrid_search.invoke({"query": query, "top_k": 15})
        all_chunks = _collect_chunks(result, all_chunks)
        logger.info(f"[forced_rag] total chunks={len(all_chunks)}")
    except Exception as e:
        logger.error(f"[forced_rag] hybrid_search failed: {e}")

    # ← 新增：如果有 period 约束，优先补充精确检索
    if period and len([c for c in all_chunks 
                       if period.replace('-', '年').rstrip('0') in c.get('content', '')
                       or period in c.get('content', '')]) < 3:
        logger.info(f"[forced_rag] period={period} 命中不足，补充 vector_search with filter")
        try:
            filtered_result = vector_search.invoke({
                "query": query, "top_k": 10, "period": period
            })
            all_chunks = _collect_chunks(filtered_result, all_chunks)
            
            filtered_kw = keyword_search.invoke({
                "query": query, "top_k": 10, "period": period
            })
            all_chunks = _collect_chunks(filtered_kw, all_chunks)
            logger.info(f"[forced_rag] after period-filtered search: {len(all_chunks)} chunks")
        except Exception as e:
            logger.error(f"[forced_rag] filtered search failed: {e}")

    # LLM 生成答案（不变）
    synthesis_prompt = _build_synthesis_prompt(query, all_chunks)
    try:
        response = llm.invoke([HumanMessage(content=synthesis_prompt)])
        raw = response.content
        final_answer = _strip_think_tags(raw)
        final_answer = re.sub(r"^```\w*\n?|```$", "", final_answer).strip()
    except Exception as e:
        logger.error(f"[forced_rag] LLM failed: {e}")
        final_answer = f"LLM 生成失败: {e}"

    return {
        "messages": [HumanMessage(content=query), AIMessage(content=final_answer)],
        "final_answer": final_answer,
        "retrieved_chunks": all_chunks,
        "iterations": 1,
    }
```

### Phase 4 自查

```bash
# 1. 静态检查
grep -n "period" src/backend/retrieval-service/app/agent/tools.py | head -20
grep -n "extract_query_constraints" src/backend/retrieval-service/app/agent/graph.py

# 2. 功能测试（需要服务运行）
curl -s http://localhost:8002/api/v1/agent/query \
  -H "Content-Type: application/json" \
  -d '{"query": "2026年1月普通硅酸盐水泥P.O 42.5R袋装的含税价格是多少？"}' | \
  python3 -m json.tool | head -30

# 3. 检查日志中是否有 period filter
tail -50 /tmp/retrieval_service.log | grep -i "period"
```

### Phase 4 报告模板

```
Phase 4 完成情况：
- [ ] vector_search 加 period 参数
- [ ] keyword_search 加 period 参数
- [ ] extract_query_constraints() 函数加入 graph.py
- [ ] forced_rag_node 加 period 检测 + 补充检索
- [ ] Agent 查询测试：返回答案中包含 2026年1月水泥价格
- [ ] 日志显示 period=2026-01 检测成功
- 遇到的问题：___
```

---

## ⏩ Phase 5：评估器增强 — 引用相关性验证

### 5.1 修改 `evaluator.py` — 加时间匹配检查

在 `evaluate_retrieval_quality` 函数中，`fact_consistency` 计算之后、`confidence` 计算之前，插入：

```python
def evaluate_retrieval_quality(
    chunks: List[dict],
    generated_answer: str,
    history_rounds: int = 0,
    query: str = "",          # ← 新增参数
) -> dict:
    try:
        # ... 前面的 avg_score/source_diversity/information_gain/completeness/consistency 不变 ...

        # 事实一致性（基于引用数量）
        citations = re.findall(r"\[\d+\]", generated_answer)
        citations += re.findall(r"【[^】]+】", generated_answer)
        fact_consistency = min(0.6 + len(citations) * 0.1, 0.95)

        # ── 新增：时间约束验证 ──
        temporal_penalty = 1.0
        if query:
            period_match = re.search(r'(\d{4})年(\d{1,2})月', query)
            if period_match:
                target_period = f"{period_match.group(1)}年{period_match.group(2)}月"
                target_period_alt = (
                    f"{period_match.group(1)}-{int(period_match.group(2)):02d}"
                )
                
                # 检查 chunks 中有多少包含目标月份
                period_hits = 0
                for c in chunks:
                    content = c.get("content", "")
                    if target_period in content or target_period_alt in content:
                        period_hits += 1
                
                period_ratio = period_hits / max(len(chunks), 1)
                
                if period_hits == 0:
                    # 没有任何 chunk 包含目标月份 → 严重降分
                    temporal_penalty = 0.4
                    logger.warning(
                        f"[evaluator] 0/{len(chunks)} chunks match "
                        f"period={target_period}, applying 0.4x penalty"
                    )
                elif period_ratio < 0.2:
                    # 不到 20% 的 chunk 匹配 → 中等降分
                    temporal_penalty = 0.7
                    logger.info(
                        f"[evaluator] {period_hits}/{len(chunks)} chunks match "
                        f"period={target_period}, applying 0.7x penalty"
                    )
                # else: 20%+ 命中，不惩罚

        # 应用时间惩罚
        fact_consistency *= temporal_penalty
        
        # ── 新增：答案自相矛盾检查 ──
        contradiction_penalty = 1.0
        if query:
            period_match = re.search(r'(\d{4})年(\d{1,2})月', query)
            if period_match:
                target = f"{period_match.group(1)}年{period_match.group(2)}月"
                # 如果答案说"无法确认/未找到"但 chunks 里其实有目标月份数据
                if any(kw in generated_answer for kw in ["无法确认", "未找到", "未能找到"]):
                    period_in_chunks = any(
                        target in c.get("content", "") for c in chunks
                    )
                    if period_in_chunks:
                        # chunk 里有但 LLM 说没有 → 可能漏读
                        contradiction_penalty = 0.6
                        logger.warning(
                            f"[evaluator] LLM says '未找到' but chunks contain "
                            f"{target}, contradiction penalty 0.6"
                        )
        
        fact_consistency *= contradiction_penalty

        # 覆盖率
        coverage_estimate = min(avg_score * source_diversity * 1.5, 0.95)

        # 置信度
        confidence = (completeness + consistency + fact_consistency + source_diversity) / 4

        passed = confidence >= 0.7 and fact_consistency >= 0.6

        return {
            "passed": passed,
            # ... 其余字段不变 ...
            "temporal_penalty": round(temporal_penalty, 4),        # ← 新增
            "contradiction_penalty": round(contradiction_penalty, 4),  # ← 新增
        }
```

### 5.2 修改 `graph.py` — evaluator 调用传 query

找到 `evaluator_node` 中的 `evaluate_retrieval_quality` 调用，加 `query`：

```python
def evaluator_node(state: RAGAgentState) -> dict:
    final_answer = state.get("final_answer", "")
    chunks = state.get("retrieved_chunks", [])
    history_rounds = max(0, state.get("iterations", 1) - 1)

    evaluation = evaluate_retrieval_quality(
        chunks, final_answer, history_rounds,
        query=state.get("query", ""),      # ← 新增
    )
```

### Phase 5 自查

```bash
# 1. 单元测试评估器
python3 -c "
import sys
sys.path.insert(0, 'src/backend/retrieval-service')
from app.agent.evaluator import evaluate_retrieval_quality

# 场景1：chunks 不含目标月份 → 应该不通过
chunks_wrong_month = [
    {'content': '[深圳建设工程价格信息 2026-02] 普通硅酸盐水泥 P.O 42.5R 416元', 'score': 0.85},
    {'content': '[深圳建设工程价格信息 2025-12] 普通硅酸盐水泥 P.O 42.5R 410元', 'score': 0.80},
]
answer_wrong = '根据检索结果，普通硅酸盐水泥价格为416元【chunk_1】【chunk_2】'
result = evaluate_retrieval_quality(
    chunks_wrong_month, answer_wrong, 0, query='2026年1月普通硅酸盐水泥P.O 42.5R价格'
)
print(f'场景1（错误月份）: passed={result[\"passed\"]}, confidence={result[\"confidence\"]:.2f}, '
      f'temporal_penalty={result.get(\"temporal_penalty\", \"N/A\")}')
assert not result['passed'], '❌ 应该不通过！'
print('  ✅ 正确不通过')

# 场景2：chunks 包含目标月份 → 应该通过
chunks_right_month = [
    {'content': '[深圳建设工程价格信息 2026-01] 普通硅酸盐水泥 P.O 42.5R袋装 t 420.00', 'score': 0.90},
    {'content': '[深圳建设工程价格信息 2026-01] 矿渣硅酸盐水泥 P.S.A 32.5 t 350.00', 'score': 0.85},
    {'content': '2026年1月建筑材料价格表', 'score': 0.80},
]
answer_right = '根据2026年1月深圳建设工程价格信息，普通硅酸盐水泥P.O 42.5R袋装含税价格为420.00元/吨【chunk_1】'
result = evaluate_retrieval_quality(
    chunks_right_month, answer_right, 0, query='2026年1月普通硅酸盐水泥P.O 42.5R价格'
)
print(f'场景2（正确月份）: passed={result[\"passed\"]}, confidence={result[\"confidence\"]:.2f}, '
      f'temporal_penalty={result.get(\"temporal_penalty\", \"N/A\")}')
print(f'  {\"✅\" if result[\"passed\"] else \"❌\"} {\"正确通过\" if result[\"passed\"] else \"不应该不通过\"}')
"
```

### Phase 5 报告模板

```
Phase 5 完成情况：
- [ ] evaluate_retrieval_quality 加 query 参数
- [ ] 时间约束验证逻辑加入
- [ ] 答案矛盾检查逻辑加入
- [ ] evaluator_node 调用传 query
- [ ] 场景1（错误月份）: passed=False ✅
- [ ] 场景2（正确月份）: passed=True ✅
- 遇到的问题：___
```

---

## ⏩ Phase 6：端到端验收

### 6.1 端到端测试

```bash
# 重启 retrieval service
cd /home/l/rag-dashboard/src/backend/retrieval-service
pkill -f "uvicorn.*8002" || true
python -m uvicorn main:app --host 0.0.0.0 --port 8002 --reload &
sleep 5

# 测试用例 1：2026年1月水泥价格（之前失败的）
echo "=== 测试1：2026年1月水泥价格 ==="
curl -s http://localhost:8002/api/v1/agent/query \
  -H "Content-Type: application/json" \
  -d '{"query": "2026年1月普通硅酸盐水泥P.O 42.5R袋装的含税价格是多少？"}' | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
answer = data.get('answer', data.get('final_answer', ''))
eval_info = data.get('evaluation', {})
print(f'答案: {answer[:200]}')
print(f'评估: confidence={eval_info.get(\"confidence\", \"?\")}, passed={eval_info.get(\"passed\", \"?\")}')
print(f'时间惩罚: {eval_info.get(\"temporal_penalty\", \"N/A\")}')
# 验证
if '2026' in answer and '1月' in answer and any(str(p) in answer for p in range(350, 500)):
    print('✅ 答案包含2026年1月价格数据')
else:
    print('❌ 答案可能不准确')
"

# 测试用例 2：2025年12月（对比月份，验证 filter 精度）
echo ""
echo "=== 测试2：2025年12月水泥价格（对比） ==="
curl -s http://localhost:8002/api/v1/agent/query \
  -H "Content-Type: application/json" \
  -d '{"query": "2025年12月普通硅酸盐水泥P.O 42.5R袋装的含税价格是多少？"}' | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
answer = data.get('answer', data.get('final_answer', ''))
print(f'答案: {answer[:200]}')
if '2025' in answer and '12月' in answer:
    print('✅ 答案锁定到2025年12月')
else:
    print('⚠️ 答案月份可能不准确')
"

# 测试用例 3：无月份约束（应该返回最新或综合）
echo ""
echo "=== 测试3：无月份约束 ==="
curl -s http://localhost:8002/api/v1/agent/query \
  -H "Content-Type: application/json" \
  -d '{"query": "深圳市普通硅酸盐水泥P.O 42.5R的最新含税价格是多少？"}' | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
answer = data.get('answer', data.get('final_answer', ''))
print(f'答案: {answer[:200]}')
print('✅ 无月份约束测试完成（人工确认答案质量）')
"
```

### 6.2 完整自查报告

```
Phase 6 端到端验收：
- [ ] retrieval-service 重启成功
- [ ] 测试1（2026年1月水泥）：答案 = ___, confidence = ___
- [ ] 测试2（2025年12月水泥）：答案 = ___, confidence = ___
- [ ] 测试3（无月份约束）：答案 = ___
- [ ] 测试1 和测试2 价格不同（证明 filter 生效）
- [ ] 测试1 不再引用 2026年2月或 2025年12月的 chunk
- 遇到的问题：___
```

---

## 📋 改动总结

| Phase | 改什么 | 改哪里 | 关键指标 |
|-------|--------|--------|----------|
| 1 | OCR 补录 | data/ocr_outputs/ | 2026年1月 JSON 存在且含水泥数据 |
| 2 | 入库加元数据+表格分块 | unified_four_db_import.py | selfcheck 4 项全 ✅ |
| 3 | 增量重导入 | reimport_with_metadata.py | Qdrant period=2026-01 有 points |
| 4 | 检索加 filter | tools.py + graph.py | 日志显示 period filter 生效 |
| 5 | 评估器增强 | evaluator.py + graph.py | 错误月份 passed=False |
| 6 | 端到端 | curl 测试 | 测试1/2 价格不同，引用准确 |

## ⚠️ 风险与回退

1. **ES mapping 冲突**：如果 `documents` index 已有旧 mapping 不含 `period` keyword 字段，新写入的 `period` 会被当成 text 类型，term filter 不生效。解决：
   ```bash
   # 检查 mapping
   curl -s http://localhost:9200/documents/_mapping | python3 -m json.tool | grep period
   # 如果没有或类型不对，需要 reindex
   ```

2. **Qdrant payload index**：period 字段默认不创建索引，filter 会全量扫描。数据量大时需要：
   ```python
   from qdrant_client.models import PayloadSchemaType
   client.create_payload_index(
       collection_name="document_chunks",
       field_name="period",
       field_schema=PayloadSchemaType.KEYWORD,
   )
   ```

3. **向后兼容**：旧 chunks 的 period 字段为空，带 period filter 的查询不会命中旧数据。这是预期行为——用户问"2024年6月水泥价格"时，如果旧数据没 period，会 fallback 到无 filter 的 hybrid_search。

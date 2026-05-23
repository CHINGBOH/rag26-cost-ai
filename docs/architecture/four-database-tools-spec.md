"""
四库工具说明书 (Four Database Tools Specification)
=========================================

版本: 1.1
日期: 2026-04-18
适用: LangChain / LlamaIndex Agent

---

## 0. 强制规范 - 必须遵守

所有工具返回的结果中，**每个条目必须包含以下索引字段**，缺一不可：

| 字段名 | 类型 | 说明 | 示例 |
|-------|------|------|------|
| `chunk_id` | string | 文档块唯一ID | "doc_001_chunk_012" |
| `doc_id` | string | 文档ID | "doc_001" |
| `page_number` | int | 页码 | 12 |
| `source_db` | string | 来源库 | "qdrant" / "elasticsearch" / "neo4j" / "postgresql" |

---

## 1. 工具概览

| 工具名称 | 适用场景 | 数据来源 | 特点 |
|---------|---------|---------|------|
| vector_search | 语义查询、概念理解 | Qdrant | 理解同义词、近义词 |
| keyword_search | 关键词、精确匹配 | Elasticsearch | BM25打分，模糊匹配 |
| knowledge_graph_search | 实体关系、关联查询 | Neo4j | 多跳推理 |
| structured_query | 数值、条件精确查询 | PostgreSQL | SQL查询 |
| calculator | 数学计算、公式 | Node.js | 计算结果+公式展示 |

---

## 2. 工具详细说明

### 2.1 vector_search - 语义检索

**工具描述**：
通过向量相似度检索，适合模糊语义查询。

**适用问题**：
- "赶工措施费是什么意思？"
- "费率标准有哪些？"
- "深圳建设工程相关规定"

**输入参数**：
- query: str - 查询文本
- top_k: int, optional (默认10) - 返回结果数量

**返回格式**：
```json
{
  "success": true,
  "results": [
    {
      "chunk_id": "doc_001_chunk_005",
      "doc_id": "doc_001",
      "page_number": 12,
      "source_db": "qdrant",
      "content": "赶工措施费是指...",
      "score": 0.92
    }
  ],
  "count": 10,
  "source": "qdrant"
}
```

---

### 2.2 keyword_search - 关键词检索

**工具描述**：
通过关键词精确匹配，适合查找具体术语、数字。

**适用问题**：
- "2024年费率标准"
- "赶工措施费系数0.8"
- "深圳市建设工程计价办法"

**输入参数**：
- query: str - 关键词查询
- top_k: int, optional (默认10) - 返回结果数量

**返回格式**：
同vector_search

---

### 2.3 knowledge_graph_search - 知识图谱检索

**工具描述**：
通过实体和关系查询，适合查找关联信息。

**适用问题**：
- "赶工措施费属于哪个标准？"
- "深圳费率和广东费率的关系"
- "哪些文档提到了赶工措施费？"

**输入参数**：
- entities: List[str] - 实体名称列表，如["赶工措施费", "费率标准"]
- top_k: int, optional (默认10) - 返回结果数量

**返回格式**：
```json
{
  "success": true,
  "results": [
    {
      "chunk_id": "doc_001_chunk_005",
      "content": "赶工措施费是指...",
      "entities": ["赶工措施费", "费率标准"],
      "relation_count": 3
    }
  ],
  "source": "neo4j"
}
```

---

### 2.4 structured_query - 结构化查询

**工具描述**：
通过SQL条件精确查询，适合数值、分类等条件。

**适用问题**：
- "费率大于0.5的记录"
- "深圳市房建工程的费率"
- "doc_001的所有chunk"

**输入参数**（二选一）：
- chunk_ids: List[str], optional - 指定chunk_id查询
- conditions: List[Dict], optional - SQL条件数组

**conditions格式**：
```json
[
  {"field": "region", "operator": "=", "value": "深圳"},
  {"field": "project_type", "operator": "=", "value": "房建工程"},
  {"field": "fee_rate", "operator": ">", "value": 0.5}
]
```

**返回格式**：
```json
{
  "success": true,
  "results": [
    {
      "chunk_id": "doc_001_chunk_005",
      "doc_id": "doc_001",
      "content": "...",
      "metadata": {
        "region": "深圳",
        "project_type": "房建工程",
        "fee_rate": 0.8
      }
    }
  ],
  "source": "postgresql"
}
```

---

### 2.5 calculator - 计算器

**工具描述**：
执行数学计算，适用于费率计算、汇总等。

**适用问题**：
- "0.8 * 10000"
- "费率0.8乘以工程量5000"
- "赶工措施费计算"

**输入参数**：
- expression: str - 数学表达式，如 "0.8 * 10000"

**返回格式**：
```json
{
  "success": true,
  "result": 8000,
  "expression": "0.8 * 10000",
  "steps": [
    "解析表达式: 0.8 * 10000",
    "执行乘法运算",
    "结果: 8000"
  ]
}
```

---

## 3. 工具选择指南

### 3.1 根据问题类型选择

| 问题特征 | 推荐工具 |
|---------|---------|
| 含"什么是"、"意思是" | vector_search |
| 含具体数字、术语 | keyword_search |
| 含"属于"、"相关"、"关系" | knowledge_graph_search |
| 含"大于"、"小于"、"等于" | structured_query |
| 需要计算数值 | calculator |

### 3.2 工具组合建议

复杂问题可以多个工具组合使用：

1. 先用 vector_search 找语义相关
2. 再用 structured_query 找精确条件
3. 最后用 calculator 计算

---

## 4. 错误处理

所有工具返回统一格式：

**成功**：
```json
{ "success": true, ... }
```

**失败**：
```json
{
  "success": false,
  "error": "错误信息",
  "content": "失败描述"
}
```

---

## 5. 示例工作流

### 示例1：深圳赶工措施费

问题："深圳市房建工程赶工措施费是多少？"

步骤：
1. vector_search: "深圳赶工措施费" → 找到相关chunk
2. structured_query: 条件[region="深圳", project_type="房建工程"] → 精确匹配
3. calculator: 计算结果

### 示例2：多跳推理

问题："赶工措施费属于哪个标准？该标准中还有哪些费用？"

步骤：
1. knowledge_graph_search: entities=["赶工措施费"] → 找到所属标准
2. vector_search: 标准名称 → 找到该标准文档
3. keyword_search: 标准文档中的费用术语

---

## 6. Agent决策提示

作为Agent，你应该：

1. **先理解问题**：判断问题类型
2. **选择合适工具**：根据工具选择指南
3. **观察结果**：分析返回的chunk_id、score等信息
4. **判断是否需要更多工具**：如果信息不足，继续调用
5. **验证一致性**：多个工具结果是否一致
6. **完成回答**：汇总所有信息，标注来源和计算过程

记住：**每个结果必须有明确的来源（chunk_id），每个计算必须有公式和步骤！**
"""

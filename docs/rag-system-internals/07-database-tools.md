# 数据库直接查询工具

## list_tables — 列出数据表

list_tables 返回 PostgreSQL 中所有可查询的表名列表，帮助 Agent 了解当前数据库有哪些数据。这是 Agent 在进行结构化查询之前的"探索"步骤。返回的表通常包括：documents（文档元数据）、chunks（文本块）、price_records（价格数据）、sessions（会话记录）、agent_runs（Agent 运行日志）等。无参数，直接调用即可。

## describe_table — 查看表结构

describe_table 返回指定表的详细结构信息，包括每列的列名、数据类型和约束（主键、外键、非空等）。Agent 在写 SQL 查询之前需要先用这个工具了解表结构，确保列名正确。参数：table（表名）。返回格式为列定义列表，例如 price_records 表包含 id、doc_id、material_name、specification、year_month、price_tax_included（含税价）、price（不含税价）等字段。

## sql_query — 执行 SELECT 查询

sql_query 允许 Agent 直接执行 SQL SELECT 语句查询数据库。参数：sql（必须是 SELECT 语句）、max_rows（最多返回行数，默认 50，防止结果集过大）。系统有严格的只读权限控制，任何 INSERT、UPDATE、DELETE、DROP 语句都会被拒绝并返回错误。所有查询在只读事务中执行，超时自动回滚。返回 JSON 格式的查询结果集，Agent 再据此生成答案。

## aggregate_query — 聚合统计查询

aggregate_query 专门优化了 GROUP BY、COUNT、SUM、AVG、MAX、MIN 等聚合操作。与 sql_query 相比，aggregate_query 针对大数据量做了性能优化，适合统计类分析，如"统计各月份水泥价格均价"、"查询已索引文档总数"等。同样只允许 SELECT，有行数和超时限制。

## 数据库查询工具的适用场景

数据库查询工具（list_tables、describe_table、sql_query、aggregate_query）主要用于：需要精确数字和结构化数据时（如查询特定月份某材料的精确价格）、需要做数据统计和汇总时、语义检索找不到足够信息时的兜底查询。这些工具绕过了文本检索，直接从数据库获取原始数据，准确性最高，但需要问题有明确的结构化查询意图。

## list_documents 和 fetch_chunk — 文档级别工具

list_documents 列出知识库中所有已索引的文档信息，包括文档名、上传时间、状态、文本块数量等，帮助 Agent 了解知识库内容覆盖范围。fetch_chunk 通过 chunk_id 获取特定文本块的完整内容及其前后邻居块（with_neighbors=True 时），用于当 Agent 需要查看某段文本的完整上下文时。similar_chunks 则根据一个已有 chunk_id 找到语义上最相似的其他文本块（top_k 默认 5），用于发现相关内容。

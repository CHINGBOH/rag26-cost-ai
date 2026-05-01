# 检索类工具详解

## hybrid_search — 混合检索主力工具

hybrid_search 是 Agent 最常用的检索工具，也是大多数问题的第一选择。它同时向 Qdrant 向量库、PostgreSQL pgvector 和 Elasticsearch 三路发起并行查询，用 RRF 算法融合排名后返回最相关的 top-K 段落。参数说明：query 是检索问题（支持中文），top_k 默认 10（可调高获取更多候选），path_constraint 是路径约束（限定在特定文档路径下检索，用于多知识库隔离场景）。混合检索既能处理语义模糊表达，又能匹配精确术语，综合效果最佳。

## vector_search — 纯向量语义检索

vector_search 只使用 Qdrant 向量相似度，不依赖关键词。适合用户表达模糊、用词不专业或需要"找意思相近"的情况。例如用户问"造价里的管理成本都包含什么"，即使文档里用的是"企业管理费"这个专业术语，向量检索也能正确匹配。参数：query（问题），top_k（默认 10）。纯向量检索召回率高但精度相对低，通常作为 hybrid_search 的组成部分而非单独使用。

## keyword_search — 关键词精确检索

keyword_search 只使用 Elasticsearch 分词索引，要求查询词在文档中实际出现。适合精确术语匹配，如特定规范编号、标准名称、材料型号等。参数：query（关键词，支持中文分词），top_k（默认 10）。当 hybrid_search 没有找到满意结果时，Agent 可能单独调用 keyword_search 用更精确的术语重试。

## text_search — PostgreSQL 全文检索

text_search 使用 PostgreSQL 的 tsquery 语法和 zhparser 中文分词，在数据库文本块中做全文检索。与 Elasticsearch 相比，text_search 的优势是数据一致性（从主数据库直接查），适合需要同时获取结构化元数据的场景。参数：query（搜索词），top_k（默认 8），path_constraint（路径约束）。支持 zhparser 的中文词向量匹配，比简单字符串匹配准确。

## pdf_page_search — PDF 原页检索

pdf_page_search 专门检索保留了 PDF 原始页码信息的文本块。当用户问"在第几页"或"能不能给我看原文"时，Agent 会用这个工具。它的检索结果包含页码、页面布局信息和文档名，让用户可以定位到原始 PDF 的具体页面。参数：query（问题），top_k（默认 8）。

## rule_clause_search — 规范条文专项检索

rule_clause_search 是专门针对工程规范、标准文本的条款结构化检索工具。建设工程领域的规范（如建设工程造价标准、费率标准等）有严格的章节条款编号体系，这个工具能识别和匹配"第X章第X条"这类结构。它返回结果包含条款编号、层级结构、所属章节，适合精确查找某一条款的具体规定。参数：query，top_k（默认 8）。

## get_catalog_map — 目录映射检索

get_catalog_map 获取文档目录结构，帮助 Agent 了解知识库中文档的组织方式。当 Agent 需要了解"某主题在哪个章节"或"文档的整体结构"时使用。参数：query（主题关键词），top_k（默认 12）。返回文档目录层级和对应的段落位置，帮助 Agent 做更精准的路径约束检索。

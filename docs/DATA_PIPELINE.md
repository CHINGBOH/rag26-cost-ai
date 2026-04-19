# 文档处理数据管道设计

## 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        输入层 (Input)                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ 扫描PDF  │  │ 图片PDF  │  │ 混合PDF  │  │ 图片文件 │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘        │
└───────┼─────────────┼─────────────┼─────────────┼──────────────┘
        │             │             │             │
        └─────────────┴──────┬──────┴─────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     OCR 层 (OCR Pipeline)                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  PaddleOCR                                               │   │
│  │  ├─ 文本识别 (PP-OCRv4)                                  │   │
│  │  ├─ 表格识别 (PP-Structure)                              │   │
│  │  ├─ 版面分析 (Layout Analysis)                           │   │
│  │  └─ 公式识别 (LaTeX OCR)                                 │   │
│  └─────────────────────────────────────────────────────────┘   │
│                             │                                   │
│                             ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  输出: Markdown (带置信度标记)                            │   │
│  │  ├─ 文本块 + 位置信息                                    │   │
│  │  ├─ 表格 HTML/Markdown                                   │   │
│  │  └─ 版面类型 (标题/段落/列表/公式)                        │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                  文档处理层 (Document Processor)                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  1. 文档解析 (Parser)                                     │   │
│  │     ├─ 提取标题、章节、页码                               │   │
│  │     ├─ 识别文档结构 (层级关系)                            │   │
│  │     └─ 过滤噪声 (页眉/页脚/页码)                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                             │                                   │
│                             ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  2. 智能分段 (Chunking)                                   │   │
│  │     ├─ 语义分段 (Semantic Chunking)                      │   │
│  │     │   └─ 按主题/段落边界分割                            │   │
│  │     ├─ 固定长度分段 (Fixed Size)                          │   │
│  │     │   └─ 重叠窗口 (Overlap: 20%)                        │   │
│  │     └─ 混合策略 (Hybrid)                                  │   │
│  │         └─ 优先语义边界，控制最大长度                      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                             │                                   │
│                             ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  3. 内容增强 (Enrichment)                                 │   │
│  │     ├─ 提取关键词 (TF-IDF/TextRank)                      │   │
│  │     ├─ 生成摘要 (Extractive/Abstractive)                 │   │
│  │     ├─ 实体识别 (NER: 人名/地名/法规/标准)                │   │
│  │     └─ 添加上下文 (前后段落)                              │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                  向量化层 (Embedding)                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  文本嵌入模型                                            │   │
│  │  ├─ 通用: text2vec/bge-m3                                │   │
│  │  ├─ 中文: m3e-base/bge-large-zh                          │   │
│  │  └─ 领域: 工程造价专用模型 (微调)                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                             │                                   │
│                             ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  多向量表示 (Multi-Vector)                                │   │
│  │  ├─ 稠密向量 (Dense): 768/1024/1536 维                   │   │
│  │  ├─ 稀疏向量 (Sparse): BM25/TF-IDF                       │   │
│  │  └─ 二进制向量 (Binary): 用于快速过滤                     │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                  存储层 (Storage)                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  向量数据库   │  │  文档数据库   │  │  图数据库     │          │
│  │  (Qdrant)    │  │  (MongoDB)   │  │  (Neo4j)     │          │
│  │              │  │              │  │              │          │
│  │  ├─ 向量索引  │  │  ├─ 原始文档  │  │  ├─ 实体关系  │          │
│  │  ├─ 元数据   │  │  ├─ 分块内容  │  │  ├─ 章节层级  │          │
│  │  └─ 过滤器   │  │  └─ 检索历史  │  │  └─ 引用关系  │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                  检索层 (Retrieval)                              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  混合检索 (Hybrid Search)                                 │   │
│  │  ├─ 向量相似度 (Vector Similarity)                       │   │
│  │  │   └─ HNSW/IVF 索引                                    │   │
│  │  ├─ 关键词匹配 (Keyword Matching)                        │   │
│  │  │   └─ BM25 + 倒排索引                                  │   │
│  │  └─ 重排序 (Rerank)                                      │   │
│  │      └─ Cross-Encoder / LLM Reranker                     │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## 数据流

### 1. 文档输入
```yaml
input:
  formats: [pdf, png, jpg, tiff]
  types:
    - scanned_pdf:    # 纯图片 PDF
        ocr_required: true
        quality_check: true
    
    - text_pdf:       # 可选中文字 PDF
        ocr_required: false
        extract_method: pymupdf
    
    - mixed_pdf:      # 图文混合 PDF
        ocr_required: partial
        text_extraction: pymupdf
        image_extraction: paddleocr
```

### 2. OCR 处理
```yaml
ocr_pipeline:
  engine: PaddleOCR
  models:
    detection: ch_PP-OCRv4_det_infer
    recognition: ch_PP-OCRv4_rec_infer
    classification: ch_ppocr_mobile_v2.0_cls_infer
    structure: ch_ppstructure_mobile_v2.0_SLANet_infer
    layout: picodet_lcnet_x1_0_fgd_layout_cdla_infer
  
  preprocessing:
    - deskew: true          # 纠偏
    - denoise: true         # 去噪
    - binarize: adaptive    # 自适应二值化
    - dpi: 300              # 分辨率
  
  output_format:
    - text_blocks:          # 文本块
        - text
        - bbox
        - confidence
        - page
    
    - tables:               # 表格
        - html
        - markdown
        - cells
    
    - layout:               # 版面
        - type: [title, paragraph, list, table, figure]
        - bbox
```

### 3. 文档解析
```yaml
parser:
  steps:
    - extract_metadata:     # 提取元数据
        - title
        - author
        - date
        - page_count
    
    - structure_analysis:   # 结构分析
        - heading_levels: [h1, h2, h3, h4]
        - section_boundaries
        - table_of_contents
    
    - noise_removal:        # 去噪
        - headers: 页眉
        - footers: 页脚
        - page_numbers: 页码
        - watermarks: 水印
    
    - content_classification:  # 内容分类
        - type: [title, paragraph, list, table, formula, figure]
        - confidence_threshold: 0.8
```

### 4. 智能分段
```yaml
chunking:
  strategy: hybrid          # 混合策略
  
  semantic_chunking:
    method: texttiling      # 文本瓦片算法
    parameters:
      window_size: 20       # 窗口大小
      threshold: 0.3        # 边界阈值
  
  fixed_size:
    chunk_size: 512         # 每块最大 token 数
    overlap: 100            # 重叠 token 数
  
  constraints:
    min_chunk_size: 50      # 最小块大小
    max_chunk_size: 1000    # 最大块大小
    preserve_sentences: true  # 保持句子完整
    preserve_paragraphs: true # 保持段落完整
```

### 5. 内容增强
```yaml
enrichment:
  keyword_extraction:
    method: tfidf + textrank
    top_k: 10
  
  summarization:
    method: extractive     # 抽取式摘要
    ratio: 0.1             # 原文 10%
  
  named_entity_recognition:
    entities:
      - ORG: 机构
      - PER: 人名
      - LOC: 地点
      - LAW: 法规
      - STD: 标准
      - RATE: 费率
  
  context_augmentation:
    prev_chunks: 1         # 前1块
    next_chunks: 1         # 后1块
```

### 6. 向量化
```yaml
embedding:
  models:
    default:
      name: BAAI/bge-m3
      dimension: 1024
      max_length: 8192
    
    chinese:
      name: moka-ai/m3e-base
      dimension: 768
      max_length: 512
    
    domain:
      name: construction-cost-model
      dimension: 768
      fine_tuned: true
  
  multi_vector:
    dense:
      enabled: true
      quantization: int8    # 量化
    
    sparse:
      enabled: true
      method: bm25
    
    binary:
      enabled: true
      for_filtering: true
```

### 7. 存储
```yaml
storage:
  vector_db:
    engine: Qdrant
    collections:
      documents:
        vector_size: 1024
        distance: Cosine
        indexing: HNSW
      
      chunks:
        vector_size: 1024
        distance: Cosine
        indexing: HNSW
    
    metadata:
      - doc_id
      - chunk_id
      - page_number
      - section
      - chunk_type
      - keywords
      - confidence
  
  document_db:
    engine: MongoDB
    collections:
      raw_documents:
        - full_text
        - metadata
        - processing_history
      
      processed_chunks:
        - content
        - embedding_id
        - context
        - entities
  
  graph_db:
    engine: Neo4j
    entities:
      - Document
      - Section
      - Chunk
      - Entity
      - Keyword
    relationships:
      - BELONGS_TO
      - REFERENCES
      - SIMILAR_TO
      - CONTAINS
```

### 8. 检索
```yaml
retrieval:
  hybrid_search:
    vector_weight: 0.7
    keyword_weight: 0.3
  
  filters:
    - doc_type
    - date_range
    - section
    - confidence_threshold
  
  reranking:
    method: cross_encoder
    model: BAAI/bge-reranker-large
    top_k: 10
  
  result_enhancement:
    - highlight_matches
    - add_context
    - show_confidence
```

## 输出格式

### 结构化文档
```json
{
  "doc_id": "sz_flbz_2023",
  "title": "深圳市建设工程计价费率标准（2023）",
  "source": "深圳市住房和建设局",
  "total_pages": 15,
  "metadata": {
    "publish_date": "2023-12-06",
    "effective_date": "2024-02-15",
    "avg_confidence": 0.989
  },
  "structure": {
    "sections": [
      {
        "id": "sec_1",
        "title": "一、总则",
        "level": 1,
        "page": 2,
        "subsections": [...]
      }
    ]
  },
  "chunks": [
    {
      "id": "chunk_001",
      "content": "企业管理费计算公式...",
      "type": "formula",
      "section": "二、分部分项工程费",
      "page": 2,
      "embedding_id": "vec_001",
      "keywords": ["企业管理费", "计算公式"],
      "entities": [
        {"type": "RATE", "value": "16.2%"}
      ]
    }
  ]
}
```

### 检索块
```json
{
  "chunk_id": "chunk_001",
  "content": "企业管理费：E=（人工费A+机械费C×0.1）×企业管理费费率a",
  "doc_id": "sz_flbz_2023",
  "doc_title": "深圳市建设工程计价费率标准（2023）",
  "section": "二、分部分项工程费",
  "page": 2,
  "type": "formula",
  "context": {
    "before": "综合单价构成中的企业管理费计算公式如下：",
    "after": "根据目前本市建筑施工企业管理水平的实际情况..."
  },
  "metadata": {
    "keywords": ["企业管理费", "计算公式"],
    "confidence": 0.99,
    "entities": [
      {"type": "FORMULA", "text": "E=（人工费A+机械费C×0.1）×企业管理费费率a"},
      {"type": "RATE", "value": "16.2%"}
    ]
  }
}
```

## 性能指标

| 指标 | 目标值 |
|------|--------|
| OCR 准确率 | > 95% |
| 文档处理速度 | > 10页/秒 |
| 分块质量 | 语义连贯性 > 90% |
| 检索准确率 (Top-5) | > 85% |
| 检索延迟 (P95) | < 100ms |
| 存储压缩比 | > 5:1 |

## 错误处理

```yaml
error_handling:
  ocr_failure:
    - retry_with_different_dpi
    - fallback_to_manual_review
    - mark_as_low_confidence
  
  parsing_failure:
    - use_rule_based_fallback
    - preserve_raw_text
    - alert_admin
  
  embedding_failure:
    - use_backup_model
    - cache_similar_chunks
    - queue_for_retry
```

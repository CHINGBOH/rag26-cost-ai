# 数据管道修复 PR 说明

## 背景

- OCR 重跑后 `document_id` 不稳定，导致 `text_chunks` 和 `price_records` 遗留旧数据。
- OCR 源目录存在重复 JSON，导入脚本会重复扫描或选错候选文件。
- `chunk_vector_views` embedding 回填在 CUDA OOM 后会反复回到过大的 encode batch。
- 图表页价格回填依赖精确材料名，`柴油0号` 在真实 OCR 页面中存在别名和噪声写法，导致月度价格页漏回填。

## 变更清单

- 统一 OCR 文档身份到规范化 `file_name`，在 `src/backend/python-legacy/tools/ocr_text_to_pg.py` 和 `src/backend/python-legacy/tools/ocr_json_to_pg.py` 中按 `doc_id + normalized file_name` 刷新旧数据，避免 OCR 重跑后脏数据残留。
- 为 OCR 源扫描引入候选评分和去重，只导入结构有效的 JSON，并补充 `document_registry` 注册与计数更新。
- 增强结构化价格解析，修复塌缩单元格、错误表头命中和完全重复行重复写入问题。
- 在 `src/database/scripts/run_full_ocr_embedding_pipeline.py` 中拆分官方入口的 text import 与 price import，保留一条权威全链路命令。
- 在 `src/database/scripts/build_chunk_vector_views.py` 中保留可复用 embedding；在 `src/database/scripts/backfill_embeddings.py` 中对 `chunk_vector_views` 按文本分组更新，并让 OOM 后缩小的 encode batch 持续生效。
- 在 `src/database/scripts/backfill_chart_page_summaries.py` 中为 `柴油0号` 增加别名匹配，修复 2026-01 / 2026-02 月度图表页价格回填缺口。
- 在 `src/database/scripts/verify.py` 中新增 OCR source coverage audit，校验 OCR 源文档是否完整落到 `document_registry`、`text_chunks` 和 `price_records`。
- 更新 `KIMI_DATAPIPELINE.md` 与 `tools/ocr_ingest_pipeline.py` 的 OCR 文件命名和入口说明，和现行导入路径保持一致。

## 验证

- `./venv/bin/python src/database/scripts/backfill_chart_page_summaries.py`
  - `chart_pages_total = 2`
  - `chart_pages_fully_covered = 2`
  - `missing_materials_total = 0`
- `./venv/bin/python src/database/scripts/backfill_embeddings.py --table chunk_vector_views --backend sentence_transformers --batch 1024 --limit 2048`
  - OOM 自动降批后完成回填，覆盖率达到 `100%`
- `./venv/bin/python src/database/scripts/run_full_ocr_embedding_pipeline.py --batch 1024 --skip-metrics`
  - `text_chunks = 19,186`
  - `price_records = 14,362`
  - `fee_rates = 41`
  - `canonical_concepts = 15,955`
  - `concept_relations = 2,808,856`
  - `concept_evidence_links = 516,037`
  - `chunk_vector_views = 51,199`
  - 五张 embedding 表覆盖率均为 `100.0%`
  - `All checks passed`

## 影响范围

- 影响 OCR 文本入库、结构化价格入库、图表页回填、向量视图构建、embedding 回填和最终验收脚本。
- 不包含 `package-lock.json` 等与本次数据管道修复无关的工作区改动。

## 后续建议

- 现有 OCR 语料中仍有部分可疑材料名和脏表头样本，建议单开后续清洗任务，不和本次全链路修复混在一起。
- 后续若继续补历史月份，优先复用官方入口脚本做增量验证，避免再回到分散脚本人工串联。
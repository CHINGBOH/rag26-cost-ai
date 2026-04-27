# Issue: 优化 OCR 混合策略

## 背景

- 当前 `src/backend/ocr-service/ocr_service.py` 对 PDF 每一页都先栅格化，再统一走 PaddleOCR + PPStructure。
- 这种策略对扫描版规范和复杂表格页有效，但对可直接提取文本的 born-digital PDF 成本过高。
- 全页 OCR 还会把原生文本页降级成 OCR 噪声，增加目录页、规则页和正文页的清洗负担。

## 问题

1. 可直接提取文本的页面没有走快速路径，吞吐低。
2. 原生文本页被重复 OCR，文本质量反而下降。
3. 表格页和图表页又不能简单关闭 OCR，否则会损失 `tables` / `figures` 结构化产物。

## 目标

实现分层混合策略，而不是单一全页 OCR：

1. 原生文本优先：页面存在足够稳定的 embedded text 时，优先使用 `page.get_text()` 结果。
2. 结构页保留 OCR：目录页、表格页、图表页继续走 PaddleOCR/PPStructure。
3. 混合覆盖：需要 OCR 的页面仍保留 `tables` / `figures`，但正文文本优先采用原生提取结果。
4. 后续增强：为低质量扫描页增加二次 OCR/重试策略，而不是一开始就把所有页都推到重路径。

## 本次已实现的 MVP

- 在 `src/backend/ocr-service/ocr_service.py` 增加 native text 抽取与页级判定。
- 对“原生文本充足、且不是结构化页、且无嵌入图片”的页面直接跳过 OCR。
- 对仍需 OCR 的页面，保留 OCR 的 `tables` / `figures`，但优先用原生文本覆盖 `raw_text` / `text_blocks`。
- 同步和异步 PDF 处理路径都接入同一套混合分流逻辑。

## 验收标准

1. born-digital 正文页不再强制进入全页 OCR。
2. 表格页和图表页仍能输出 `tables` / `figures`。
3. 现有 OCR JSON 输出结构保持兼容，不改调用方协议。
4. 为以下行为补回归测试：
   - 原生文本页直接跳过 OCR
   - 结构页继续 OCR
   - OCR 页面保留结构化结果，同时覆盖正文文本

## 后续阶段

1. 为低置信扫描页增加 second-pass OCR，例如更高 DPI 或局部增强重试。
2. 在响应或日志中暴露页级 route metrics，统计 native / OCR / hybrid 三类命中比例。
3. 将 `batch_scan.py` 报表扩展为输出 route strategy 分布，方便评估收益。
# OCR 批量扫描工具

基于 PaddleOCR PP-OCRv4 + PPStructure（GPU: NVIDIA RTX 4070）的 PDF 批量 OCR 工具。

## 目录结构

```
ocr_tools/
├── batch_scan.py          # 主工具：批量扫描 PDF → JSON
├── README.md              # 本文档
├── generate_report.py     # 从 OCR 结果生成汇总报告
├── merge_results.py       # 合并多个 JSON 结果
└── validate_results.py    # 校验 OCR 结果完整性

data/ocr_outputs/
├── _scan_state.json       # 扫描进度（跳过已完成的文件）
├── processing_summary.json # 批处理汇总，含 native / ocr / hybrid 路由统计
├── 深圳信息价/             # 镜像 knowledge_base 目录结构
└── 深圳市建设工程地方标准/
```

## 快速开始

```bash
# 查看当前扫描进度
python3 ocr_tools/batch_scan.py --status

# 扫描所有未处理的 PDF（断点续扫）
python3 ocr_tools/batch_scan.py

# 强制重新扫描（覆盖已完成）
python3 ocr_tools/batch_scan.py --force

# 扫描单个文件
python3 ocr_tools/batch_scan.py --pdf "data/knowledge_base/深圳信息价/2025-01.pdf"
```

## OCR 服务信息

| 项目 | 说明 |
|------|------|
| 地址 | http://localhost:8001 |
| 容器 | `docker ps` → `ocr-gpu` |
| 引擎 | PaddleOCR PP-OCRv4（中英文） |
| GPU | NVIDIA RTX 4070 / CUDA 12.6 |
| 框架 | PaddlePaddle 3.2.0 |
| 表格 | PPStructure layout+table |

健康检查：`curl http://localhost:8001/health`

## JSON 输出格式

```json
{
  "document_id": "doc_pdf_xxx",
  "file_name": "2025-01.pdf",
  "total_pages": 41,
  "pages": [
    {
      "page_number": 1,
      "confidence": 0.972,
      "raw_text": "...",
      "route_info": {
        "strategy": "hybrid",
        "reason": "structured_native_page",
        "native_text_chars": 893,
        "native_text_blocks": 24,
        "has_embedded_images": false,
        "ocr_attempts": 1,
        "used_second_pass": false
      },
      "text_blocks": [{"text": "...", "confidence": 0.99, "bbox": {"x":0,"y":0,"width":100,"height":20}}],
      "tables": [{"html": "<table>...", "markdown": "| 列1 | 列2 |...", "cells": [...]}],
      "figures": [
        {
          "region_type": "figure",
          "bbox": {"x": 127, "y": 991, "width": 942, "height": 386},
          "text_in_region": "230\n225\n多层住宅\n220\n高层住宅\n...",
          "confidence": 0.979
        }
      ]
    }
  ],
  "route_metrics": {
    "native_pages": 12,
    "ocr_pages": 18,
    "hybrid_pages": 11,
    "second_pass_pages": 3,
    "total_ocr_attempts": 32,
    "total_pages": 41
  }
}
```

### route_info / route_metrics 说明

- `route_info.strategy`: 页级路由结果，取值为 `native`、`ocr`、`hybrid`
- `route_info.reason`: 进入该路由的主因，例如 `strong_native_text`、`structured_native_page`、`embedded_images`
- `route_info.ocr_attempts`: 该页实际 OCR 次数；弱结果页触发 second-pass 时会变为 `2`
- `route_metrics`: 文档级汇总，用于 batch_scan 直接统计真实语料的 native / ocr / hybrid 命中比例

### Batch 扫描报表

- `batch_scan.py` 现在会把每个文件的 `route_metrics` 写入 `data/ocr_outputs/_scan_state.json`
- 同时生成 `data/ocr_outputs/processing_summary.json`，汇总已处理文件的页级路由分布、second-pass 命中数和总 OCR 尝试次数
- `python3 ocr_tools/batch_scan.py --status` 会直接打印当前已知页的 native / ocr / hybrid 比例

### figures.text_in_region 说明
走势图/坐标图内的所有文字（Y轴刻度、X轴标签、图例名称、单位标注）。
实现方式：PPStructure 检测 figure 区域 → 裁剪子图 → 单独再次 OCR。

## 性能参考（RTX 4070）

| 文件类型 | 页数 | 大小 | 估计耗时 |
|---------|------|------|---------|
| 小型标准文件 | 12页 | 0.2MB | ~30s |
| 信息价月刊 | 75页 | 22MB | ~8min |
| 大型规范手册 | 558页 | 124MB | ~60min |
| 超大扫描版 | 47页 | 538MB | ~10min |

## 注意事项

1. 必须先启动 OCR 容器：脚本会自动检查，若服务不在线会报错退出
2. 断点续扫：`_scan_state.json` 记录每个文件状态，`--force` 才会覆盖
3. 大文件上传（>100MB）需等待，上传超时设为 120s
4. 若 OCR 结果中包含 `route_info` / `route_metrics`，`batch_scan.py --status` 会自动回填并汇总路由统计

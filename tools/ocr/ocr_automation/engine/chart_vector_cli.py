#!/usr/bin/env python3
"""
Chart Vector Extractor CLI

命令行工具，支持配置文件驱动的方式批量提取 PDF 趋势图数据。

用法：
    # 1. 先用自动检测获取子图配置
    python -m ocr_automation.engine.chart_vector_cli detect \
        --pdf input.pdf --page 15 --output config.json

    # 2. 手动编辑 config.json，补充系列名和价格范围

    # 3. 用配置文件执行提取
    python -m ocr_automation.engine.chart_vector_cli extract \
        --pdf input.pdf --page 15 --config config.json --output result.json

    # 4. 直接指定配置（不经过配置文件）
    python -m ocr_automation.engine.chart_vector_cli extract \
        --pdf input.pdf --page 15 \
        --subchart '{"y1":130,"y2":292,"name":"钢筋","series":["光圆","带肋"],"price_range":[3000,5500]}' \
        --output result.json
"""

import argparse
import json
import sys
from pathlib import Path

from chart_vector_extractor import ChartVectorExtractor


def cmd_detect(args):
    """自动检测子图区域"""
    extractor = ChartVectorExtractor()
    result = extractor.extract_auto_detect(args.pdf, args.page)

    output = {
        "pdf": args.pdf,
        "page": args.page,
        "subcharts": result["subcharts"],
        "marker_count": result["marker_count"],
        "note": "请手动补充 series 名称和 price_range，然后用于 extract 命令",
    }

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"Detected config saved to {args.output}")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


def cmd_extract(args):
    """执行数据提取"""
    extractor = ChartVectorExtractor()

    # 加载配置
    if args.config:
        with open(args.config, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        subcharts = cfg.get("subcharts", [])
        month_start = tuple(cfg.get("month_start", [2023, 1]))
    elif args.subchart:
        subcharts = [json.loads(args.subchart)]
        month_start = (2023, 1)
    else:
        print("Error: --config or --subchart required", file=sys.stderr)
        sys.exit(1)

    # 补充必需的字段（如果配置文件里缺少）
    for sc in subcharts:
        if "price_range" in sc and isinstance(sc["price_range"], list):
            sc["price_range"] = tuple(sc["price_range"])

    print(f"Extracting from {args.pdf} page {args.page}...")
    print(f"  Subcharts: {len(subcharts)}")
    for sc in subcharts:
        print(f"    - {sc['name']}: {len(sc['series'])} series, y=[{sc['y1']}, {sc['y2']}], price={sc['price_range']}")

    results = extractor.extract_from_pdf(
        pdf_path=args.pdf,
        page_num=args.page,
        subcharts=subcharts,
        month_start=month_start,
    )

    print(f"\nExtracted {len(results)} series:")
    for r in results:
        pts = r.points
        print(f"  {r.chart_name}/{r.series_name}: {len(pts)} pts, "
              f"price=[{min(p.price for p in pts):.0f}, {max(p.price for p in pts):.0f}] {r.unit}")

    # 保存结果
    if args.output:
        extractor.save_results(results, args.output)

    return results


def main():
    parser = argparse.ArgumentParser(description="PDF Chart Vector Data Extractor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # detect 子命令
    p_detect = subparsers.add_parser("detect", help="Auto-detect subchart regions")
    p_detect.add_argument("--pdf", required=True, help="PDF file path")
    p_detect.add_argument("--page", type=int, required=True, help="Page number (1-based)")
    p_detect.add_argument("--output", "-o", help="Output config JSON file")

    # extract 子命令
    p_extract = subparsers.add_parser("extract", help="Extract data points")
    p_extract.add_argument("--pdf", required=True, help="PDF file path")
    p_extract.add_argument("--page", type=int, required=True, help="Page number (1-based)")
    p_extract.add_argument("--config", "-c", help="Subchart config JSON file")
    p_extract.add_argument("--subchart", help="Single subchart config as JSON string")
    p_extract.add_argument("--output", "-o", help="Output result JSON file")

    args = parser.parse_args()

    if args.command == "detect":
        cmd_detect(args)
    elif args.command == "extract":
        cmd_extract(args)


if __name__ == "__main__":
    main()

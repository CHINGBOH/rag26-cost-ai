#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
OCR 精度测试脚本
处理 PDF 并应用改进的 OCR 工具，输出精度报告
"""

import sys
from pathlib import Path
import json
import time

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.ocr_automation.parser.price_normalizer import (
    SymbolCorrector,
    PriceValidator,
    clean_price,
    clean_unit
)
from tools.ocr_automation.parser.table_rebuilder import (
    detect_table_bounds,
    cluster_rows_adaptive,
    rebuild_table_adaptive
)
from tools.ocr_automation.engine.rapidocr_gpu import RapidOCR


def process_pdf_with_improvements(pdf_path: str, max_pages: int = 10):
    """
    处理 PDF 并应用 OCR 改进

    Args:
        pdf_path: PDF 文件路径
        max_pages: 处理的最大页数

    Returns:
        精度报告
    """
    print("=" * 70)
    print("🚀 OCR 精度测试开始")
    print("=" * 70)
    print(f"\n📄 文件: {Path(pdf_path).name}")
    print(f"📊 处理页数: {max_pages}\n")

    try:
        # 1. 初始化 OCR 引擎
        print("[1/6] 初始化 OCR 引擎...")
        ocr_engine = RapidOCR()
        corrector = SymbolCorrector()
        validator = PriceValidator()
        print("✓ 初始化完成\n")

        # 2. 处理 PDF
        print("[2/6] 处理 PDF...")
        import fitz  # PyMuPDF

        start_time = time.time()
        doc = fitz.open(pdf_path)
        total_pages = min(len(doc), max_pages)

        all_text_blocks = []
        all_records = []
        processing_stats = {
            'total_pages': total_pages,
            'processed_pages': 0,
            'ocr_blocks': 0,
            'extracted_records': 0,
            'corrected_items': 0,
            'validated_items': 0
        }

        for page_idx in range(total_pages):
            page = doc[page_idx]
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)

            # OCR 处理
            ocr_result = ocr_engine.ocr_page_from_pix(pix)
            cells = ocr_result['cells'] if ocr_result else []

            if cells:
                all_text_blocks.extend(cells)
                processing_stats['ocr_blocks'] += len(cells)

                # 尝试提取表格
                try:
                    page_height = pix.height
                    page_width = pix.width

                    rows = cluster_rows_adaptive(cells, page_height, page_width)
                    if rows:
                        table = rebuild_table_adaptive(rows, page_height, page_width)

                        # 简单的记录提取（演示）
                        for row_dict in table:
                            if len(row_dict) >= 4:
                                record = {
                                    'material_name': str(list(row_dict.values())[0])[:100],
                                    'spec': str(list(row_dict.values())[1])[:100] if len(row_dict) > 1 else '',
                                    'unit': str(list(row_dict.values())[2])[:20] if len(row_dict) > 2 else '',
                                    'price_str': str(list(row_dict.values())[3])[:20] if len(row_dict) > 3 else '',
                                    'page': page_idx + 1
                                }

                                # 清洁和纠正
                                record['price'] = clean_price(record.get('price_str'))
                                record['unit'] = clean_unit(record.get('unit'))

                                # 应用符号纠正
                                corrected = corrector.correct_record(record)
                                if '_corrections' in corrected and corrected['_corrections']:
                                    processing_stats['corrected_items'] += len(corrected['_corrections'])

                                all_records.append(corrected)
                                processing_stats['extracted_records'] += 1
                except Exception as e:
                    pass  # 表格提取失败，继续

            processing_stats['processed_pages'] += 1

            # 进度显示
            if (page_idx + 1) % 3 == 0:
                print(f"  页 {page_idx + 1}/{total_pages} ✓")

        processing_time = time.time() - start_time
        print(f"✓ PDF 处理完成 ({processing_time:.2f}s)\n")

        # 3. 应用数据验证
        print("[3/6] 应用多层验证...")
        if all_records:
            passed, flagged = validator.batch_validate_with_anomaly_detection(
                all_records,
                confidence_threshold=0.7
            )
            processing_stats['validated_items'] = len(passed)
        else:
            passed, flagged = [], []
        print(f"✓ 验证完成\n")

        # 4. 收集异常分类
        print("[4/6] 分析异常...")
        anomaly_types = {}
        for rec in flagged:
            for issue in rec.get('_issues', []):
                atype = issue.split(':')[0]
                anomaly_types[atype] = anomaly_types.get(atype, 0) + 1

        correction_types = {}
        for rec in passed:
            if '_corrections' in rec:
                for field, info in rec['_corrections'].items():
                    ctype = corrector._classify_correction(field, info['original'], info['corrected'])
                    correction_types[ctype] = correction_types.get(ctype, 0) + 1
        print(f"✓ 异常分析完成\n")

        # 5. 生成报告
        print("[5/6] 生成精度报告...")
        accuracy = len(passed) / (len(passed) + len(flagged)) if (len(passed) + len(flagged)) > 0 else 0

        report = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'file': str(Path(pdf_path).name),
            'processing': processing_stats,
            'results': {
                'total_records': len(passed) + len(flagged),
                'passed_records': len(passed),
                'flagged_records': len(flagged),
                'accuracy': f"{accuracy*100:.1f}%",
                'processing_time_seconds': processing_time,
                'average_time_per_page': processing_time / total_pages if total_pages > 0 else 0
            },
            'anomalies': anomaly_types,
            'corrections': correction_types
        }

        print("✓ 报告生成完成\n")

        # 6. 输出结果
        print("[6/6] 输出结果...\n")

        print("=" * 70)
        print("📊 精度测试报告")
        print("=" * 70)

        print(f"\n📈 处理统计:")
        print(f"  总页数: {processing_stats['total_pages']}")
        print(f"  已处理: {processing_stats['processed_pages']}")
        print(f"  OCR 文字块: {processing_stats['ocr_blocks']}")
        print(f"  提取记录: {processing_stats['extracted_records']}")
        print(f"  纠正项: {processing_stats['corrected_items']}")

        print(f"\n✅ 精度评估:")
        print(f"  总记录数: {report['results']['total_records']}")
        print(f"  通过验证: {report['results']['passed_records']} ✓")
        print(f"  标记异常: {report['results']['flagged_records']} ⚠️")
        print(f"  精度: {report['results']['accuracy']} 🎯")
        print(f"  处理时间: {report['results']['processing_time_seconds']:.2f}s")
        print(f"  每页平均: {report['results']['average_time_per_page']:.3f}s")

        if anomaly_types:
            print(f"\n⚠️  异常分布:")
            for atype, count in sorted(anomaly_types.items(), key=lambda x: -x[1]):
                print(f"  {atype}: {count}")

        if correction_types:
            print(f"\n🔧 纠正分布:")
            for ctype, count in sorted(correction_types.items(), key=lambda x: -x[1]):
                print(f"  {ctype}: {count}")

        # 样本输出
        if passed:
            print(f"\n✅ 通过验证的样本记录 (前 5 条):")
            for i, rec in enumerate(passed[:5], 1):
                print(f"\n  [{i}] {rec.get('material_name', 'N/A')}")
                print(f"      规格: {rec.get('spec', 'N/A')}")
                print(f"      单位: {rec.get('unit', 'N/A')}")
                print(f"      价格: {rec.get('price', 'N/A')}")
                if rec.get('_inferred_category'):
                    print(f"      分类: {rec['_inferred_category']}")

        if flagged:
            print(f"\n⚠️  标记异常的样本记录 (前 5 条):")
            for i, rec in enumerate(flagged[:5], 1):
                print(f"\n  [{i}] {rec.get('material_name', 'N/A')}")
                print(f"      问题: {', '.join(rec.get('_issues', []))}")

        print("\n" + "=" * 70)
        print("✨ 测试完成!")
        print("=" * 70 + "\n")

        return report

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == '__main__':
    pdf_path = "/home/l/rag-dashboard/data/knowledge_base/深圳信息价/《深圳建设工程价格信息》2026年1月.pdf"

    # 运行测试 (前 10 页)
    report = process_pdf_with_improvements(pdf_path, max_pages=10)

    # 保存报告
    if report:
        output_file = "/tmp/ocr_test_report.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"📄 报告已保存到: {output_file}")

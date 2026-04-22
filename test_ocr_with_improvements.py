#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
OCR 精度测试 - 使用已有的 OCR 结果文件
"""

import sys
import json
from pathlib import Path
from collections import defaultdict

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from tools.ocr_automation.parser.price_normalizer import (
    SymbolCorrector,
    PriceValidator
)
from tools.ocr_automation.parser.table_rebuilder import detect_table_bounds


def analyze_ocr_results(ocr_json_path: str):
    """
    分析 OCR 结果的精度
    """
    print("=" * 80)
    print("🔍 OCR 精度分析")
    print("=" * 80)

    # 1. 加载 OCR 结果
    print("\n[1/4] 加载 OCR 结果...")
    with open(ocr_json_path, 'r', encoding='utf-8') as f:
        ocr_data = json.load(f)

    print(f"✓ 加载完成")
    print(f"  文件: {ocr_data.get('document', {}).get('file_name', 'N/A')}")
    print(f"  页数: {ocr_data.get('document', {}).get('total_pages', 'N/A')}")

    # 2. 初始化工具
    print("\n[2/4] 初始化改进工具...")
    corrector = SymbolCorrector()
    validator = PriceValidator()
    print("✓ 初始化完成")

    # 3. 分析价格记录
    print("\n[3/4] 分析价格记录...")
    price_records = ocr_data.get('price_records_sample', [])
    print(f"样本记录数: {ocr_data.get('price_records_count', 'N/A')}")
    print(f"样本数: {len(price_records)}")

    # 应用改进
    corrected_records = []
    correction_stats = defaultdict(int)

    for rec in price_records:
        # 保留原始数据
        orig_rec = rec.copy()

        # 符号纠正
        if rec.get('spec'):
            corrected_spec = corrector.correct_spec(str(rec['spec']))
            if corrected_spec != rec['spec']:
                correction_stats[f"spec_corrected"] += 1
                rec['spec'] = corrected_spec
                rec['spec_original'] = orig_rec['spec']

        if rec.get('unit'):
            corrected_unit = corrector.correct_spec(str(rec['unit']))
            if corrected_unit != rec['unit']:
                correction_stats[f"unit_corrected"] += 1
                rec['unit'] = corrected_unit
                rec['unit_original'] = orig_rec['unit']

        corrected_records.append(rec)

    # 多层验证
    passed, flagged = validator.batch_validate_with_anomaly_detection(
        corrected_records,
        confidence_threshold=0.7
    )

    print(f"✓ 分析完成")
    print(f"  总记录: {len(corrected_records)}")
    print(f"  通过验证: {len(passed)} ({len(passed)*100/len(corrected_records):.1f}%)")
    print(f"  标记异常: {len(flagged)} ({len(flagged)*100/len(corrected_records):.1f}%)")

    # 4. 生成报告
    print("\n[4/4] 生成精度报告...")

    # 统计异常类型
    anomaly_types = defaultdict(int)
    for rec in flagged:
        for issue in rec.get('_issues', []):
            atype = issue.split(':')[0]
            anomaly_types[atype] += 1

    # 统计纠正类型
    correction_by_type = defaultdict(int)
    for rec in corrected_records:
        if '_corrections' in rec:
            for field, info in rec['_corrections'].items():
                ctype = corrector._classify_correction(field, info['original'], info['corrected'])
                correction_by_type[ctype] += 1

    print("✓ 报告生成完成\n")

    # 5. 输出详细报告
    print("=" * 80)
    print("📊 详细精度报告")
    print("=" * 80)

    # 基本指标
    accuracy = len(passed) / len(corrected_records) if corrected_records else 0
    print(f"\n📈 基本指标:")
    print(f"  总记录数: {len(corrected_records)}")
    print(f"  通过验证: {len(passed)}")
    print(f"  标记异常: {len(flagged)}")
    print(f"  精度: {accuracy*100:.1f}%")

    # 纠正统计
    total_corrections = sum(correction_stats.values())
    print(f"\n🔧 符号纠正统计:")
    print(f"  总纠正项: {total_corrections}")
    print(f"  纠正率: {total_corrections*100/len(corrected_records):.1f}%")
    if correction_stats:
        for ctype, count in sorted(correction_stats.items(), key=lambda x: -x[1]):
            print(f"    • {ctype}: {count}")

    # 异常分析
    print(f"\n⚠️  异常分析 ({len(flagged)} 条):")
    if anomaly_types:
        for atype, count in sorted(anomaly_types.items(), key=lambda x: -x[1]):
            print(f"  • {atype}: {count}")
    else:
        print("  无异常")

    # 分类推断准确度
    category_inferred = sum(1 for r in corrected_records if r.get('_inferred_category'))
    print(f"\n📋 分类推断:")
    print(f"  推断成功: {category_inferred}/{len(corrected_records)} ({category_inferred*100/len(corrected_records):.1f}%)")

    # 样本展示
    print(f"\n✅ 通过验证的样本记录 (前 5 条):")
    for i, rec in enumerate(passed[:5], 1):
        print(f"\n  [{i}] {rec.get('material_name', 'N/A')[:30]}")
        if rec.get('spec_original'):
            print(f"      规格: {rec['spec_original']} → {rec.get('spec', 'N/A')}")
        else:
            print(f"      规格: {rec.get('spec', 'N/A')}")
        print(f"      单位: {rec.get('unit', 'N/A')}")
        print(f"      价格: {rec.get('price', 'N/A')}")
        if rec.get('_inferred_category'):
            print(f"      分类: {rec['_inferred_category']}")

    # 异常样本展示
    if flagged:
        print(f"\n⚠️  标记异常的样本记录 (前 5 条):")
        for i, rec in enumerate(flagged[:5], 1):
            print(f"\n  [{i}] {rec.get('material_name', 'N/A')[:30]}")
            print(f"      规格: {rec.get('spec', 'N/A')}")
            print(f"      单位: {rec.get('unit', 'N/A')}")
            print(f"      价格: {rec.get('price', 'N/A')}")
            if rec.get('_issues'):
                print(f"      问题:")
                for issue in rec['_issues']:
                    print(f"        • {issue}")

    # 图表数据质量
    chart_data = ocr_data.get('chart_series', [])
    print(f"\n📊 图表数据:")
    print(f"  图表数量: {len(chart_data)}")
    for chart in chart_data:
        points = chart.get('points', [])
        print(f"  • {chart.get('series_name', 'N/A')}: {len(points)} 个数据点")

    # 文本内容
    text_chunks = ocr_data.get('text_chunks_sample', [])
    print(f"\n📝 文本内容:")
    print(f"  文本块数: {len(text_chunks)}")

    # 总体评分
    print("\n" + "=" * 80)
    print("🎯 总体评分")
    print("=" * 80)

    score = accuracy * 0.5  # 精度占 50%
    score += (1 - len(anomaly_types)/max(len(flagged), 1)) * 0.25  # 异常类型多样性占 25%
    score += (correction_by_type != {} and 1 or 0) * 0.25  # 纠正能力占 25%

    print(f"\n总体精度评分: {accuracy*100:.1f}%")

    if accuracy >= 0.90:
        print("📊 评级: ⭐⭐⭐⭐⭐ 优秀")
    elif accuracy >= 0.80:
        print("📊 评级: ⭐⭐⭐⭐ 很好")
    elif accuracy >= 0.70:
        print("📊 评级: ⭐⭐⭐ 良好")
    elif accuracy >= 0.60:
        print("📊 评级: ⭐⭐ 一般")
    else:
        print("📊 评级: ⭐ 需要改进")

    # 改进建议
    print("\n💡 改进建议:")
    if len(anomaly_types) > 3:
        print(f"  1. 异常类型较多 ({len(anomaly_types)} 种)，需要优化验证规则")
    if len(flagged) > len(passed) * 0.2:
        print(f"  2. 异常率较高 ({len(flagged)*100/len(corrected_records):.1f}%)，建议使用 LLM 增强验证")
    if total_corrections == 0:
        print(f"  3. 无符号纠正，符号库可能需要扩展")

    print("\n" + "=" * 80)
    print("✨ 精度分析完成!")
    print("=" * 80 + "\n")

    return {
        'accuracy': accuracy,
        'total_records': len(corrected_records),
        'passed': len(passed),
        'flagged': len(flagged),
        'anomalies': dict(anomaly_types),
        'corrections': dict(correction_by_type)
    }


if __name__ == '__main__':
    # 使用现有的 OCR 结果文件
    ocr_json_path = "/tmp/2026-02_ocr_result.json"

    # 检查文件是否存在
    if not Path(ocr_json_path).exists():
        print(f"❌ 文件不存在: {ocr_json_path}")
        print("使用之前分析的数据文件...")
        # 尝试使用本地文件
        sys.exit(1)

    # 运行分析
    result = analyze_ocr_results(ocr_json_path)

    # 保存结果
    output_file = "/tmp/ocr_accuracy_analysis.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"📄 分析结果已保存到: {output_file}")

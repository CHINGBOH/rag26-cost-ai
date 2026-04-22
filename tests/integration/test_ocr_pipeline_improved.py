"""
OCR 改进管道集成测试
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
from tools.ocr_automation.parser.price_normalizer import (
    SymbolCorrector,
    PriceValidator,
    batch_validate
)


def test_ocr_improvement_pipeline():
    """测试完整的 OCR 改进管道"""

    print("\n" + "="*60)
    print("🚀 OCR 改进管道集成测试")
    print("="*60 + "\n")

    # 1. 初始化工具
    print("[1/4] 初始化工具...")
    corrector = SymbolCorrector()
    validator = PriceValidator()
    print("✓ SymbolCorrector 和 PriceValidator 初始化成功\n")

    # 2. 模拟 OCR 结果数据
    print("[2/4] 准备测试数据...")
    raw_records = [
        {
            'material_name': '热轧光圆钢筋HPB300',
            'spec': '8中',
            'unit': 'm3',
            'price': 3725.0,
            'category': '定额人工费',
            'confidence': 0.92
        },
        {
            'material_name': '热轧带肋钢筋HRB400E',
            'spec': '16中',
            'unit': 't',
            'price': 3689.34,
            'category': None,
            'confidence': 0.88
        },
        {
            'material_name': '无缝钢管',
            'spec': '',
            'unit': None,
            'price': 4033.83,
            'category': '十、管材',
            'confidence': 0.85
        },
        {
            'material_name': '普通硅酸盐水泥',
            'spec': 'P.O 42.5R散装',
            'unit': 't',
            'price': 381.56,
            'category': None,
            'confidence': 0.95
        },
        {
            'material_name': '中砂',
            'spec': '',
            'unit': 't',
            'price': 188.1,
            'category': None,
            'confidence': 0.91
        }
    ]
    print(f"✓ 准备了 {len(raw_records)} 条测试记录\n")

    # 3. 执行符号纠正
    print("[3/4] 执行符号纠正...")
    corrected_records = corrector.batch_correct(raw_records)
    corrections_stats = corrector.get_statistics(raw_records)

    print(f"✓ 纠正统计:")
    print(f"  - 总记录数: {corrections_stats['total_records']}")
    print(f"  - 被纠正记录: {corrections_stats['corrected_records']}")
    print(f"  - 总纠正次数: {corrections_stats['total_corrections']}")
    print(f"  - 纠正率: {corrections_stats['correction_rate']*100:.1f}%")

    if corrections_stats['corrections_by_field']:
        print(f"  - 按字段分布:")
        for field, count in corrections_stats['corrections_by_field'].items():
            print(f"    • {field}: {count} 次")
    print()

    # 4. 执行多层验证
    print("[4/4] 执行多层验证...")
    passed, flagged = validator.batch_validate_with_anomaly_detection(
        corrected_records,
        confidence_threshold=0.7
    )

    print(f"✓ 验证完成:")
    print(f"  - 通过验证: {len(passed)} 条 ({len(passed)/len(corrected_records)*100:.1f}%)")
    print(f"  - 标记异常: {len(flagged)} 条 ({len(flagged)/len(corrected_records)*100:.1f}%)")
    print(f"  - 平均置信度: {sum(r['_confidence_final'] for r in corrected_records)/len(corrected_records):.2f}")

    # 异常分析
    print(f"\n✓ 异常分析:")
    anomaly_types = {}
    for rec in flagged:
        for issue in rec.get('_issues', []):
            atype = issue.split(':')[0]
            anomaly_types[atype] = anomaly_types.get(atype, 0) + 1

    if anomaly_types:
        for atype, count in sorted(anomaly_types.items(), key=lambda x: -x[1]):
            print(f"  - {atype}: {count} 次")
    else:
        print("  (无异常)")

    # 通过记录详情
    print(f"\n✓ 通过验证的记录 ({len(passed)} 条):")
    for i, rec in enumerate(passed, 1):
        print(f"\n  [{i}] {rec['material_name']}")
        print(f"      规格: {rec['spec']} | 单位: {rec['unit']}")
        print(f"      价格: {rec['price']:.2f}元 | 置信度: {rec['_confidence_final']:.2f}")
        if rec.get('_inferred_category'):
            print(f"      分类: {rec['_inferred_category']}")

    # 异常记录详情
    if flagged:
        print(f"\n✓ 标记异常的记录 ({len(flagged)} 条):")
        for i, rec in enumerate(flagged, 1):
            print(f"\n  [{i}] {rec['material_name']}")
            print(f"      规格: {rec['spec']} | 单位: {rec['unit']}")
            print(f"      价格: {rec['price']:.2f}元 | 置信度: {rec['_confidence_final']:.2f}")
            if rec.get('_issues'):
                print(f"      问题: {', '.join(rec['_issues'])}")

    # 成功指标检查
    print("\n" + "="*60)
    print("📊 成功指标评估")
    print("="*60)

    accuracy = len(passed) / len(corrected_records) if corrected_records else 0
    print(f"✓ 精度达成: {accuracy*100:.1f}% (目标: ≥ 90%)")

    if accuracy >= 0.90:
        print("✅ 第一阶段目标达成！")
    else:
        print("⚠️  精度未达目标，需进一步优化")

    return {
        'total_records': len(corrected_records),
        'passed': len(passed),
        'flagged': len(flagged),
        'accuracy': accuracy,
        'corrections': corrections_stats,
        'anomalies': anomaly_types
    }


if __name__ == '__main__':
    result = test_ocr_improvement_pipeline()
    print("\n" + "="*60)
    print("✨ 测试完成!")
    print("="*60 + "\n")

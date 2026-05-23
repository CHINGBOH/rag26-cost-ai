"""
OCR 改进功能单元测试
"""

import pytest
from pathlib import Path
from tools.ocr_automation.parser.price_normalizer import (
    SymbolCorrector,
    clean_price,
    clean_unit,
    validate_record,
    batch_validate
)


class TestSymbolCorrector:
    """特殊字符纠正器测试"""

    @pytest.fixture
    def corrector(self):
        """创建 SymbolCorrector 实例"""
        return SymbolCorrector()

    def test_direct_mapping(self, corrector):
        """测试直接映射纠正"""
        assert corrector.correct_spec("8中") == "Φ8"
        assert corrector.correct_spec("6中") == "Φ6"
        assert corrector.correct_spec("10中") == "Φ10"
        assert corrector.correct_spec("m3") == "m³"
        assert corrector.correct_spec("m2") == "m²"

    def test_pattern_based_correction(self, corrector):
        """测试正则模式纠正"""
        # Φ10盤卷 -> Φ10盘卷
        result = corrector.correct_spec("Φ10盤卷")
        assert "盘卷" in result or result == "Φ10盘卷"

    def test_no_correction_needed(self, corrector):
        """测试无需纠正的字符串"""
        assert corrector.correct_spec("Φ8") == "Φ8"
        assert corrector.correct_spec("HPB300") == "HPB300"
        assert corrector.correct_spec("m³") == "m³"

    def test_empty_string(self, corrector):
        """测试空字符串"""
        assert corrector.correct_spec("") == ""
        assert corrector.correct_spec(None) == None

    def test_correct_record(self, corrector):
        """测试纠正单条记录"""
        record = {
            'spec': '8中',
            'unit': 'm3',
            'material_name': '钢筋'
        }
        corrected = corrector.correct_record(record)

        assert corrected['spec'] == 'Φ8'
        assert corrected['unit'] == 'm³'
        assert corrected['material_name'] == '钢筋'

        # 检查审计信息
        assert '_corrections' in corrected
        assert 'spec' in corrected['_corrections']
        assert 'unit' in corrected['_corrections']

    def test_batch_correct(self, corrector):
        """测试批量纠正"""
        records = [
            {'spec': '8中', 'unit': 'm3'},
            {'spec': '10中', 'unit': 'm2'},
            {'spec': 'Φ12', 'unit': 't'}
        ]
        corrected_records = corrector.batch_correct(records)

        assert len(corrected_records) == 3
        assert corrected_records[0]['spec'] == 'Φ8'
        assert corrected_records[1]['spec'] == 'Φ10'
        assert corrected_records[2]['spec'] == 'Φ12'

    def test_get_statistics(self, corrector):
        """测试纠正统计"""
        records = [
            {'spec': '8中', 'unit': 'm3'},
            {'spec': '10中', 'unit': 't'},
            {'spec': 'Φ12', 'unit': 'm2'}
        ]
        stats = corrector.get_statistics(records)

        assert stats['total_records'] == 3
        assert stats['corrected_records'] == 3  # 都进行了纠正
        assert stats['total_corrections'] == 5  # 5 个字段被纠正
        assert 'spec' in stats['corrections_by_field']
        assert 'unit' in stats['corrections_by_field']

    def test_batch_operations_preserve_data(self, corrector):
        """测试批量操作保留数据"""
        record = {
            'spec': '8中',
            'price': 5000,
            'category': '钢材'
        }
        corrected = corrector.correct_record(record)

        # 检查未修改的字段
        assert corrected['price'] == 5000
        assert corrected['category'] == '钢材'


class TestCleanPrice:
    """价格清洁函数测试"""

    def test_numeric_price(self):
        """测试数字价格"""
        assert clean_price(100.5) == 100.5
        assert clean_price(100) == 100.0

    def test_string_price(self):
        """测试字符串价格"""
        assert clean_price("100.5") == 100.5
        assert clean_price("100") == 100.0
        assert clean_price("100.5元") == 100.5
        assert clean_price("¥100.5") == 100.5

    def test_price_with_comma(self):
        """测试包含逗号的价格"""
        assert clean_price("1,234.56") == 1234.56
        assert clean_price("1,234.56元") == 1234.56

    def test_invalid_price(self):
        """测试无效价格"""
        assert clean_price("abc") is None
        assert clean_price("") is None
        assert clean_price(None) is None


class TestCleanUnit:
    """单位清洁函数测试"""

    def test_valid_units(self):
        """测试有效单位"""
        assert clean_unit("t") == "t"
        assert clean_unit("kg") == "kg"
        assert clean_unit("m³") == "m³"
        assert clean_unit("m²") == "m²"

    def test_unit_with_extra_text(self):
        """测试包含多余文本的单位"""
        assert clean_unit("单位：t") == "t"
        assert clean_unit("200 kg") == "kg"

    def test_invalid_unit(self):
        """测试无效单位"""
        assert clean_unit("invalid_unit_12345_very_long") is None
        assert clean_unit("") is None
        assert clean_unit(None) is None


class TestValidateRecord:
    """记录验证函数测试"""

    def test_valid_record(self):
        """测试有效记录"""
        record = {
            'price': 1000,
            'material_name': '钢筋',
            'confidence': 0.95
        }
        validated = validate_record(record)
        assert validated['_status'] == 'ok'

    def test_price_out_of_range(self):
        """测试价格超出范围"""
        record = {
            'price': 20_000_000,  # 超过 10_000_000
            'material_name': '钢筋'
        }
        validated = validate_record(record)
        assert validated['_status'] == 'quarantine_price'

    def test_missing_price(self):
        """测试缺少价格"""
        record = {
            'material_name': '钢筋',
            'confidence': 0.95
        }
        validated = validate_record(record)
        assert validated['_status'] == 'quarantine_missing'

    def test_missing_name(self):
        """测试缺少材料名称"""
        record = {
            'price': 1000,
            'confidence': 0.95
        }
        validated = validate_record(record)
        assert validated['_status'] == 'quarantine_missing'

    def test_low_confidence(self):
        """测试低置信度"""
        record = {
            'price': 1000,
            'material_name': '钢筋',
            'confidence': 0.5  # 低于 0.6 阈值
        }
        validated = validate_record(record, quarantine_threshold=0.6)
        assert validated['_status'] == 'quarantine_low_conf'


class TestBatchValidate:
    """批量验证函数测试"""

    def test_batch_validation(self):
        """测试批量验证"""
        records = [
            {'price': 1000, 'material_name': '钢筋', 'confidence': 0.95},  # 有效
            {'price': 20_000_000, 'material_name': '钢板'},  # 价格异常
            {'price': 500, 'material_name': '', 'confidence': 0.8}  # 缺少名称
        ]

        ok, quarantine = batch_validate(records)

        assert len(ok) == 1
        assert len(quarantine) == 2
        assert ok[0]['_status'] == 'ok'
        assert quarantine[0]['_status'] == 'quarantine_price'
        assert quarantine[1]['_status'] == 'quarantine_missing'

    def test_batch_empty_list(self):
        """测试空列表"""
        ok, quarantine = batch_validate([])
        assert len(ok) == 0
        assert len(quarantine) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

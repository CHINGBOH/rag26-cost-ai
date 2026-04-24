"""
价格数据清洗与验证
"""

import re
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple


def clean_price(val: Any) -> Optional[float]:
    """清洗价格字符串为float"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(',', '').replace('，', '').replace(' ', '')
    s = re.sub(r'[元\s￥$]+$', '', s)
    # 处理"34230.00"格式
    try:
        return float(s)
    except Exception:
        return None


def clean_unit(val: Any) -> Optional[str]:
    """提取单位"""
    if val is None:
        return None
    s = str(val).strip()
    units = ['t', 'kg', 'm³', 'm2', '㎡', 'm', '块', '套', '根', '只', '台', '件', '张',
             '个', '卷', '组', '条', '桶', '包', '袋', '吨', '升', 'L', '工日', '台·月',
             '延长米', '延米', '套·月', '组·月', '根·月', '个·月', 't·月']
    for u in units:
        if u in s:
            return u
    if re.match(r'^[a-zA-Z·²³]+$', s):
        return s
    return s if len(s) <= 10 else None


def validate_record(record: Dict, price_max: float = 10_000_000, 
                    price_min: float = 0.0, quarantine_threshold: float = 0.6) -> Dict:
    """
    验证单条记录，返回带有_status字段的记录
    
    _status: 'ok' | 'quarantine_price' | 'quarantine_missing' | 'quarantine_low_conf'
    """
    status = 'ok'
    issues = []
    
    # 价格验证
    price = record.get('price')
    if price is not None:
        if price < price_min or price > price_max:
            status = 'quarantine_price'
            issues.append(f'price_out_of_range:{price}')
    elif not record.get('price_formula'):
        status = 'quarantine_missing'
        issues.append('missing_price_and_formula')
    
    # 名称验证
    name = record.get('material_name', '')
    if not name or len(name) < 2:
        status = 'quarantine_missing'
        issues.append('missing_name')
    
    # 置信度验证（OCR引擎提供）
    conf = record.get('confidence', 1.0)
    if conf < quarantine_threshold:
        status = 'quarantine_low_conf'
        issues.append(f'low_confidence:{conf}')
    
    record['_status'] = status
    record['_issues'] = issues
    return record


def batch_validate(records: List[Dict], **kwargs) -> tuple:
    """
    批量验证，返回 (ok_records, quarantine_records)
    """
    ok = []
    quarantine = []
    for rec in records:
        validated = validate_record(rec, **kwargs)
        if validated['_status'] == 'ok':
            ok.append(validated)
        else:
            quarantine.append(validated)
    return ok, quarantine


class SymbolCorrector:
    """
    OCR 特殊字符纠正器
    处理建筑工程文档中的常见字符识别错误

    Example:
        >>> corrector = SymbolCorrector()
        >>> corrector.correct_spec("8中")
        'Φ8'
        >>> corrector.correct_spec("m3")
        'm³'
    """

    def __init__(self, config_path: Optional[Path] = None):
        """
        初始化纠正器

        Args:
            config_path: symbol_corrections.json 配置文件路径
                       如果为 None，使用默认位置
        """
        if config_path is None:
            config_path = Path(__file__).parent.parent / 'data' / 'symbol_corrections.json'

        if not config_path.exists():
            raise FileNotFoundError(f"Symbol corrections config not found: {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

        # 预编译正则模式以提高性能
        self.compiled_patterns = []
        for pattern_rule in self.config.get('ocr_error_patterns', []):
            try:
                compiled = re.compile(pattern_rule['pattern'])
                self.compiled_patterns.append((compiled, pattern_rule))
            except re.error as e:
                print(f"Warning: Invalid regex pattern {pattern_rule['pattern']}: {e}")

    def correct_spec(self, spec: str) -> str:
        """
        纠正规格字段中的特殊字符

        Args:
            spec: 原始规格字符串

        Returns:
            纠正后的字符串
        """
        if not spec:
            return spec

        spec = str(spec).strip()

        # 1. 直接映射（优先级最高）
        if spec in self.config['symbol_mappings']:
            return self.config['symbol_mappings'][spec]

        # 2. 正则模式匹配
        corrected = spec
        for compiled_pattern, pattern_rule in self.compiled_patterns:
            match = compiled_pattern.search(corrected)
            if match:
                try:
                    # 使用 expandvars 风格的替换（使用 {1}, {2} 等表示捕获组）
                    replacement = pattern_rule['replacement']

                    # 手动替换 {1}, {2} 等
                    for i, group in enumerate(match.groups(), 1):
                        if group is not None:
                            replacement = replacement.replace(f'{{{i}}}', group)

                    corrected = corrected[:match.start()] + replacement + corrected[match.end():]

                    # 如果修正成功，可选择继续或返回
                    # 这里选择继续以支持多层纠正
                except Exception as e:
                    print(f"Warning: Error applying pattern {pattern_rule['pattern']}: {e}")
                    pass

        return corrected

    def correct_record(self, record: Dict) -> Dict:
        """
        纠正记录中的所有字段

        Args:
            record: 原始记录字典

        Returns:
            纠正后的记录，包含原始值用于审计
        """
        corrected = record.copy()

        # 纠正主要字段
        for field in ['spec', 'unit', 'material_name']:
            if field in record:
                original = record.get(field)
                if original:
                    corrected_value = self.correct_spec(str(original))
                    if corrected_value != original:
                        corrected[field] = corrected_value
                        # 记录纠正审计信息
                        if '_corrections' not in corrected:
                            corrected['_corrections'] = {}
                        corrected['_corrections'][field] = {
                            'original': original,
                            'corrected': corrected_value
                        }

        return corrected

    def batch_correct(self, records: List[Dict]) -> List[Dict]:
        """
        批量纠正记录

        Args:
            records: 记录列表

        Returns:
            纠正后的记录列表
        """
        return [self.correct_record(rec) for rec in records]

    def get_statistics(self, records: List[Dict]) -> Dict:
        """
        获取纠正统计信息

        Args:
            records: 原始记录列表

        Returns:
            统计信息字典
        """
        corrected_records = self.batch_correct(records)

        corrections_count = 0
        corrections_by_field = {}
        corrections_by_type = {}

        for rec in corrected_records:
            if '_corrections' in rec:
                for field, info in rec['_corrections'].items():
                    corrections_count += 1
                    corrections_by_field[field] = corrections_by_field.get(field, 0) + 1

                    # 分类纠正类型
                    corr_type = self._classify_correction(field, info['original'], info['corrected'])
                    corrections_by_type[corr_type] = corrections_by_type.get(corr_type, 0) + 1

        return {
            'total_records': len(records),
            'corrected_records': sum(1 for r in corrected_records if '_corrections' in r),
            'total_corrections': corrections_count,
            'corrections_by_field': corrections_by_field,
            'corrections_by_type': corrections_by_type,
            'correction_rate': corrections_count / len(records) if records else 0
        }

    @staticmethod
    def _classify_correction(field: str, original: str, corrected: str) -> str:
        """对纠正类型进行分类"""
        if field == 'spec':
            if 'Φ' in corrected and 'Φ' not in original:
                return 'symbol_addition'
            elif '³' in corrected or '²' in corrected:
                return 'superscript_correction'
            else:
                return 'spec_general'
        elif field == 'unit':
            return 'unit_normalization'
        else:
            return 'other'


class PriceValidator:
    """
    高级价格数据验证器

    支持多层验证：
    - 单位检查
    - 分类推断
    - 价格一致性检查
    - 异常检测

    Example:
        >>> validator = PriceValidator()
        >>> passed, flagged = validator.batch_validate_with_anomaly_detection(records)
    """

    # 建筑行业常见单位
    VALID_UNITS = {
        '计量单位': ['t', 'kg', 'm³', 'm²', 'm', '块', '根', '个', '台', '套', '工日',
                    '升', 'L', '延米', '延长米', '㎡', '张', '卷', '条', '桶', '只',
                    '件', '组', '包', '袋', '吨', '件', '延米', '根/延米', '㎡/工日']
    }

    # 建筑材料分类关键词
    CATEGORY_PATTERNS = {
        '钢材': ['钢筋', '钢板', '角钢', '槽钢', '工字钢', '焊管', '冷弯', '光圆', '带肋'],
        '水泥': ['水泥', 'P.O', 'P·O', '42.5'],
        '砂浆': ['砂浆', '砂浆膏', '胶粘剂', '粘合剂'],
        '混凝土': ['混凝土', '预制', '试块', 'C30', 'C25'],
        '砂石': ['砂', '碎石', '砾石', '石子', '中砂', '细砂'],
        '管材': ['管道', '管', '钢管', '铸铁管', 'PVC', 'PE', '无缝', '焊接'],
        '木材': ['木方', '木板', '胶合板', '细木工板', '苦楝木'],
        '涂料': ['涂料', '油漆', '乳胶漆', '防水漆'],
        '保温': ['保温', '岩棉', '玻璃棉', '聚苯'],
        '电气': ['电线', '电缆', '开关', '插座', '配电', '灯具'],
    }

    # 价格范围（单位：元/最小单位）
    PRICE_RANGES = {
        '钢材': (1000, 100000),       # 元/吨
        '水泥': (200, 1000),          # 元/吨
        '砂': (100, 400),              # 元/吨
        '混凝土': (100, 800),          # 元/m³
        '砖': (0.2, 2.0),              # 元/块
        '水': (0.5, 20),               # 元/m³
        '劳动力': (50, 500),           # 元/工日
        '燃油': (5, 15),               # 元/升
        '金属': (1000, 150000),        # 元/吨
        '化学品': (100, 50000),        # 元/吨
    }

    def infer_category(self, material_name: str, spec: str = '') -> Optional[str]:
        """
        推断材料分类

        Args:
            material_name: 材料名称
            spec: 规格（可选）

        Returns:
            分类名称或 None
        """
        combined = f"{material_name} {spec}".lower()

        for category, keywords in self.CATEGORY_PATTERNS.items():
            for kw in keywords:
                if kw.lower() in combined:
                    return category
        return None

    def get_expected_price_range(self, category: str, unit: str = 't') -> Tuple[float, float]:
        """
        获取预期价格范围

        Args:
            category: 材料分类
            unit: 计量单位

        Returns:
            (最小价格, 最大价格)
        """
        return self.PRICE_RANGES.get(category, (0, 10_000_000))

    def validate_unit_field(self, unit: str, material_name: str = '') -> Tuple[bool, str]:
        """
        验证单位字段

        Args:
            unit: 单位字符串
            material_name: 材料名称（可选，用于推断）

        Returns:
            (是否有效, 消息)
        """
        if not unit:
            # 尝试从材料名称推断单位
            if any(kw in material_name for kw in ['钢', '金属', '管', '板', '筋']):
                return True, "inferred_unit_t"  # 钢铁通常按吨
            return False, "missing_unit"

        unit = str(unit).strip()

        # 检查是否在已知单位列表中
        if unit in self.VALID_UNITS['计量单位']:
            return True, "valid_unit"

        # 模糊匹配（例如 m2 vs m²）
        normalized = unit.replace('m2', 'm²').replace('m3', 'm³')
        if normalized in self.VALID_UNITS['计量单位']:
            return True, "normalized_unit"

        # 如果包含已知单位关键词
        for valid_unit in self.VALID_UNITS['计量单位']:
            if valid_unit in unit:
                return True, "unit_recognized"

        return False, f"unknown_unit:{unit}"

    def validate_price_consistency(self, record: Dict, similar_records: List[Dict]) -> Tuple[bool, str]:
        """
        检验价格与同类产品的一致性

        Args:
            record: 当前记录
            similar_records: 同材料的其他记录

        Returns:
            (是否一致, 异常类型)
        """
        material = record.get('material_name', '')
        price = record.get('price')
        unit = record.get('unit')

        if not similar_records or price is None:
            return True, "no_comparison_data"

        # 筛选同单位的记录
        same_unit_prices = [r['price'] for r in similar_records
                           if r.get('unit') == unit and r.get('price') and r.get('price') > 0]

        if not same_unit_prices:
            return True, "no_same_unit_data"

        avg_price = sum(same_unit_prices) / len(same_unit_prices)
        variance = sum((p - avg_price) ** 2 for p in same_unit_prices) / len(same_unit_prices)
        std_dev = variance ** 0.5

        # 价格偏离平均值超过 3 倍标准差，标记为异常
        if std_dev > 0:
            z_score = abs(price - avg_price) / std_dev
            if z_score > 3:
                return False, f"price_outlier_z_{z_score:.1f}"
        else:
            # 标准差为 0，所有记录价格相同
            if price != avg_price:
                deviation = abs(price - avg_price) / avg_price * 100 if avg_price > 0 else 0
                if deviation > 10:  # 偏离 10% 以上
                    return False, f"price_outlier_deviation_{deviation:.1f}%"

        return True, "within_range"

    def batch_validate_with_anomaly_detection(
        self,
        records: List[Dict],
        confidence_threshold: float = 0.7
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        批量验证，支持异常检测

        Args:
            records: 原始记录列表
            confidence_threshold: 置信度阈值

        Returns:
            (通过的记录, 需要审查的记录)
        """
        passed = []
        flagged = []

        # 按材料名称分组，便于一致性检查
        materials_map = {}
        for rec in records:
            mat = rec.get('material_name', 'unknown')
            if mat not in materials_map:
                materials_map[mat] = []
            materials_map[mat].append(rec)

        for rec in records:
            issues = []
            confidence = 1.0

            # 1. 单位检查
            unit_ok, unit_msg = self.validate_unit_field(rec.get('unit'), rec.get('material_name', ''))
            if not unit_ok:
                issues.append(f"unit:{unit_msg}")
                confidence -= 0.2
            else:
                # 单位验证成功时加分
                confidence += 0.05

            # 2. 分类推断
            inferred_cat = self.infer_category(rec.get('material_name', ''), rec.get('spec', ''))
            actual_cat = rec.get('category')

            if inferred_cat:
                if actual_cat and actual_cat != inferred_cat:
                    issues.append(f"category_mismatch:{actual_cat}!={inferred_cat}")
                    confidence -= 0.1
                else:
                    confidence += 0.05  # 分类一致时加分

            # 3. 价格一致性检查
            if rec.get('price'):
                material = rec.get('material_name', '')
                similar = materials_map.get(material, [])
                price_ok, price_msg = self.validate_price_consistency(rec, similar)
                if not price_ok:
                    issues.append(f"price:{price_msg}")
                    confidence -= 0.3
                else:
                    confidence += 0.05

            # 4. OCR 置信度
            ocr_conf = rec.get('confidence', 1.0)
            if ocr_conf < 0.8:
                issues.append(f"low_ocr_confidence:{ocr_conf:.2f}")
                confidence -= 0.2
            else:
                confidence += 0.05

            # 5. 基本字段检查
            if not rec.get('material_name') or len(str(rec.get('material_name', ''))) < 2:
                issues.append("invalid_name")
                confidence -= 0.2

            # 综合决策
            rec['_confidence_final'] = max(0, min(1, confidence))
            rec['_issues'] = issues
            rec['_inferred_category'] = inferred_cat

            if confidence >= confidence_threshold and len(issues) == 0:
                passed.append(rec)
            else:
                flagged.append(rec)

        return passed, flagged

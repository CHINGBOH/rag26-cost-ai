"""
Query Analyzer — 意图分类 + 实体抽取 + 子查询分解
纯规则实现，零 LLM 调用，<1ms 延迟
"""

import re
import logging
from typing import TypedDict

logger = logging.getLogger(__name__)

PRICE_KEYWORDS = [
    "价格", "多少钱", "元/", "含税", "除税", "信息价", "造价", "单价", "费率",
    "材料费", "人工费", "机械费", "设备费", "租赁费", "一吨", "一方", "一平米",
    "每吨", "每方", "每平米", "每立方", "每米", "一个", "每公斤",
]

CALC_KEYWORDS = [
    "计算", "求", "等于", "是多少", "百分比", "费率", "总价", "合计", "汇总",
    "乘以", "除", "加", "减", "平方", "立方",
]

COMPARISON_KEYWORDS = [
    "对比", "比较", "和", "与", "相差", "哪个", "更贵", "更便宜",
    "变化幅度", "差异", "差价",
]

TREND_KEYWORDS = [
    "走势", "趋势", "变化", "涨", "跌", "波动", "历史", "分析", "从.*至今", "历年",
]

STANDARD_REF_KEYWORDS = [
    "规则", "规定", "要求", "标准", "规范", "计算规则", "定额", "消耗量",
    "费率", "组成", "内容", "如何填写", "应填写", "适用于", "按什么", "推荐系数",
    "推荐费率", "计取", "是否包含",
    # Q07 类：填写要求
    "填写", "怎么填", "填报",
    # Q09 类：增值税/计税方法政策解读
    "计税", "进项税", "增值税", "税前", "含税", "税额", "计税方法",
    # Q10 类：计算基数
    "计算基数", "基数", "总包管理", "发包人", "分包",
]

# 常见材料列表（按长度降序匹配，优先长词）
MATERIAL_LIST = [
    '加气混凝土砌块', '普通混凝土多排孔空心砌块', '普通混凝土空心砌块', '普通混凝土实心砖',
    '普通混凝土门套砖', '普通混凝土实心配套砖', '机制混凝土人行道路面砖', '机制混凝土路面环保砖',
    '机制混凝土路面透水砖', '覆膜建筑模板', '脚手架钢管', '松杂木脚手板', '阻燃型A级密目式安全立网',
    '热轧光圆钢筋', '热轧带肋钢筋', '普通硅酸盐水泥', '普通预拌混凝土', '泵送预拌混凝土',
    '湿拌抹灰砂浆', '湿拌砌筑砂浆', '普通沥青混凝土', '改性沥青混凝土', '乳化沥青',
    '种植屋面用耐根穿刺防水卷材', '混凝土路缘石', '沥青', '防水卷材', '防水涂料',
    '水泥', '钢筋', '混凝土', '中砂', '碎石', '块石', '毛石', '片石', '石粉渣',
    '白水泥', '砖', '涂料', '油漆', '防水', '保温', '管材', '电线', '电缆', '阀门',
    '门窗', '模板', '脚手架', '玻璃地板', '玻璃', '钢材', '石膏', '铝材', '木材', '砂浆', '砌块',
    '卷材', '焊条', '钢板', '钢管', '角钢', '槽钢', '螺纹钢', '盘螺', '线材', '型材',
    '板材', '线管', '给水管', '排水管', '燃气管', '配电箱', '开关', '插座', '灯具',
    '风机', '水泵', '空调', '散热器', '石材', '瓷砖', '地板', '吊顶', '防火门',
    '防盗', '栏杆', '扶手', '雨棚', '招牌', '护栏', '路缘石', '井盖', '检查井',
    '化粪池', '消防水池', '水箱', '烟囱', '避雷针', '接地极', '火灾报警', '喷淋',
    '消火栓', '灭火器', '防排烟', '防火阀', '排烟阀', '防火卷帘', '应急照明',
    '疏散指示', '气体灭火', '水喷雾', '细水雾', 'UPS', '柴油发电机', '光伏发电',
    '充电桩', '变电站', '配电室', '箱变', '电能表', '水表', '气表', '流量计',
    '压力表', '温度表', '液位计', 'PH计', '电导率', '溶解氧', '浊度', '余氯',
    'COD', 'BOD', '氨氮', '总磷', '总氮', 'PM2.5', 'PM10', 'CO2', '甲醛',
    '苯', '甲苯', '二甲苯', 'TVOC', '新风', '净化', '除湿', '加湿',
    '实验室', '手术室', 'ICU', 'CT', 'MRI', 'DR', '超声', '心电图',
    '血压', '体温', '脉搏', '血氧', '血糖', '尿酸', '血脂', '药房',
    '手术', '麻醉', '急诊', '门诊', '住院', '体检', '口腔', '眼科',
    '骨科', '神经', '心血管', '呼吸', '消化', '内分泌', '肿瘤',
    '普外', '肝胆', '胃肠', '血管', '烧伤', '整形', '移植', '微创',
    '机器人', '导航', '3D打印', '生物', '细胞', '基因', '支架', '假体',
    '植入', '消融', '粒子', '质子', '重离子', '伽马刀', '达芬奇',
    '硅酸盐', '普通', '矿渣', '粉煤灰', '复合', '早强', '缓凝',
    '抗渗', '抗冻', '抗裂', '膨胀', '自密实', '高性能', '轻骨料',
    '纤维', '钢纤维', '碳纤维', '玻璃纤维', '聚合物', '树脂',
    '橡胶', '塑料', '玻璃钢', '纳米', '石墨烯', '碳纳米管',
    '富勒烯', '金刚石', '碳化硅', '氧化铝', '氧化锆', '钛合金',
    '镍合金', '铝合金', '镁合金', '铜合金', '锌合金', '银合金',
]

# 规格模式
SPEC_PATTERNS = [
    r"([A-Z]?\.?[A-Z]?\s*\d+[\.\d]*[A-Z]?\s*(?:袋装|散装|级|型|号)?)",
    r"(C\d+[\.\d]*)",
    r"(φ\d+[\.\d]*)",
    r"(Φ\d+[\.\d]*)",
    r"(HPB\d+[A-Z]?)",
    r"(HRB\d+[A-Z]?)",
    r"(AC-\d+[\.\d]*)",
    r"(M\d+[\.\d]*)",
    r"(P\d+[\.\d]*)",
]

# 单位模式
UNIT_PATTERNS = [
    r"元\s*/\s*(t|m³|m²|㎡|m|kg|个|套|组|台|块|片|工日|支|根|卷|桶|箱|套|组|件|㎡|立方米|平方米|吨|千克|公斤|克|升|毫升|mm|cm|dm)",
    r"(?:每吨|每方|每平米|每立方|每米|每个|每公斤|每套|每组|每台|每块|每片|每工日|每支|每根|每卷|每桶|每箱|每件)",
]

_QUOTA_PREFIX_PATTERNS = [
    r"^\s*\d+\s*版",
    r"(?:安装工程|装饰工程|市政工程|建筑工程)?消耗量标准中[，,\s]*",
    r"(?:安装工程|装饰工程|市政工程|建筑工程)?工程消耗量标准中[，,\s]*",
]
_QUOTA_SUFFIX_PATTERN = re.compile(
    r"(?:的)?(?:计算规则|人工费|材料费|机械费|工料机|参考价格|全费用参考综合单价|参考综合单价)"
    r"(?:是|为)?(?:多少|什么)?[？?]?$"
)
_QUOTA_NOISE_PATTERN = re.compile(
    r"[，,。；;：:“”\"'‘’（）()【】\[\]\s]|请问|根据|按照|按|标准|消耗量|工程|版"
)
_QUOTA_LOCATION_PATTERN = re.compile(
    r"楼梯|墙面|柱面|台阶|天棚|楼地面|地面|顶面|踢脚|外墙|内墙|屋面|坡屋面|吊顶|地坪|面层"
)


class QueryAnalysis(TypedDict):
    intent: str          # 'price' | 'semantic' | 'calculation' | 'comparison' | 'trend_chart' | 'standard_ref'
    entities: dict       # {year_month, material_name, spec, unit}
    sub_queries: list    # 分解后的子查询列表


def _classify_intent(query: str) -> str:
    q = query.lower()
    # trend_chart: 走势分析（含时间序列）
    if any(re.search(kw, q) is not None if '.' in kw else kw in q for kw in TREND_KEYWORDS):
        return "trend_chart"
    # calculation: 明确有公式或数值计算
    if any(kw in q for kw in CALC_KEYWORDS) and any(kw in q for kw in PRICE_KEYWORDS):
        return "calculation"
    # comparison: 两个对象对比
    if any(kw in q for kw in COMPARISON_KEYWORDS):
        return "comparison"
    # standard_ref: 规则规范查询
    if any(kw in q for kw in STANDARD_REF_KEYWORDS):
        return "standard_ref"
    # price: 纯价格查询
    if any(kw in q for kw in PRICE_KEYWORDS):
        return "price"
    if any(kw in q for kw in CALC_KEYWORDS):
        return "calculation"
    return "semantic"


def _extract_year_month(query: str) -> str:
    # 20XX年X月
    m = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", query)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}"
    # 20XX-X 或 20XX-XX
    m = re.search(r"(20\d{2})-(\d{1,2})", query)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}"
    return ""


def _extract_material(query: str) -> str:
    # 先去掉时间词和干扰词
    cleaned = re.sub(r"20\d{2}\s*年\s*\d{1,2}\s*月", "", query)
    cleaned = re.sub(r"20\d{2}-\d{1,2}", "", cleaned)
    cleaned = re.sub(r"[年月日最新当前本个吨方平米立米套组台块片工日支根卷桶箱件价格含税除税信息价造价单价费率材料费人工费机械费设备费租赁费多少钱多钱怎样怎么什么]", "", cleaned)
    # 按长度降序匹配，优先匹配长词
    for mat in sorted(MATERIAL_LIST, key=len, reverse=True):
        if mat in cleaned:
            return mat
    return ""


def _extract_specification(query: str) -> str:
    # 先去掉年份，避免 "2024" 被误识别为规格
    cleaned = re.sub(r"20\d{2}\s*年\s*\d{1,2}\s*月", "", query)
    cleaned = re.sub(r"20\d{2}-\d{1,2}", "", cleaned)
    for pat in SPEC_PATTERNS:
        m = re.search(pat, cleaned)
        if m:
            spec = m.group(1).strip()
            # 排除纯数字（可能是年份或价格）
            if not re.match(r"^\d+$", spec):
                return spec
    return ""


def _extract_unit(query: str) -> str:
    for pat in UNIT_PATTERNS:
        m = re.search(pat, query)
        if m:
            return m.group(1).strip() if m.lastindex else ""
    return ""


def extract_quota_search_term(query: str) -> str:
    material = _extract_material(query)
    if material:
        return material

    cleaned = query.strip()
    cleaned = re.sub(r"20\d{2}\s*年\s*\d{1,2}\s*月", "", cleaned)
    cleaned = re.sub(r"20\d{2}-\d{1,2}", "", cleaned)
    for pattern in _QUOTA_PREFIX_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned)
    cleaned = _QUOTA_LOCATION_PATTERN.sub("", cleaned)
    cleaned = _QUOTA_SUFFIX_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"(是什么|是多少|怎么计算|如何计算|如何规定|如何取值)[？?]?$", "", cleaned)
    cleaned = _QUOTA_NOISE_PATTERN.sub("", cleaned).strip()
    return cleaned or query.strip()


def _decompose(query: str, intent: str) -> list[str]:
    """
    复杂查询分解为子查询。
    仅处理 comparison 和 price 的多时间/多材料情况。
    """
    sub_queries = []

    if intent == "comparison":
        # 检测比较型：提取所有年月和材料
        year_months = re.findall(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", query)
        if not year_months:
            year_months = re.findall(r"(20\d{2})-(\d{1,2})", query)
        # 处理省略年份的情况：如 "2024年1月和2月"
        if len(year_months) == 1:
            year = year_months[0][0]
            extra_months = re.findall(r"(?:和|与|至|到|～|~|-)\s*(\d{1,2})\s*月", query)
            for m in extra_months:
                year_months.append((year, m))
        year_months = [f"{y}-{m.zfill(2)}" for y, m in year_months]

        material = _extract_material(query)

        if len(year_months) >= 2 and material:
            for ym in year_months:
                sub_queries.append(f"{ym} {material} 价格")
            sub_queries.append(f"计算 {material} {' 与 '.join(year_months)} 价格差异")
        elif len(year_months) >= 2:
            for ym in year_months:
                sub_queries.append(f"{ym} 建材价格行情")
        else:
            sub_queries.append(query)

    elif intent == "price":
        # 检测是否有隐含对比（如 "现在多少钱" 暗示与历史对比）
        if re.search(r"现在|最近|最新|当前|本月", query):
            material = _extract_material(query)
            if material:
                sub_queries.append(query)
                sub_queries.append(f"最近3个月 {material} 价格趋势")
            else:
                sub_queries.append(query)
        else:
            sub_queries.append(query)

    else:
        sub_queries.append(query)

    return sub_queries


class QueryAnalyzer:
    """
    意图分类 + 实体抽取 + 子查询分解
    不依赖 LLM（纯规则 + regex），快速执行
    """

    def analyze(self, query: str) -> QueryAnalysis:
        intent = _classify_intent(query)
        entities = {
            "year_month": _extract_year_month(query),
            "material_name": _extract_material(query),
            "specification": _extract_specification(query),
            "unit": _extract_unit(query),
        }
        sub_queries = _decompose(query, intent)
        analysis = QueryAnalysis(intent=intent, entities=entities, sub_queries=sub_queries)
        logger.info(f"[analyzer] query='{query[:50]}' intent={intent} sub_queries={sub_queries}")
        return analysis

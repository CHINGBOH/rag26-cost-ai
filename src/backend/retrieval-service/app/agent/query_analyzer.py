"""
Query Analyzer — 意图分类 + 实体抽取 + 子查询分解
纯规则实现，零 LLM 调用，<1ms 延迟
"""

import re
import logging
from typing import TypedDict

logger = logging.getLogger(__name__)


def _strip_question_prefix(query: str) -> str:
    return re.sub(r"^\s*\d+\s*[.．、]\s*", "", query or "").strip()

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
    "计算方法", "计算公式", "公式",
    # Q07 类：填写要求
    "填写", "怎么填", "填报",
    # Q09 类：增值税/计税方法政策解读
    "计税", "进项税", "增值税", "税前", "含税", "税额", "计税方法",
    # Q10 类：计算基数
    "计算基数", "基数", "总包管理", "发包人", "分包",
]

# ---------------------------------------------------------------------------
# 行业别名规范化：alias -> canonical material_name（对应 price_records 实际字段值）
# 用于 _normalize_material() 把同义词查询词映射为 DB 中存储的规范名称
# 与 tools.py _ABBREV_EXPAND 保持同步（两份副本，统一修改）
# ---------------------------------------------------------------------------
_MATERIAL_NORMALIZE: dict[str, str] = {
    # ── 混凝土 / 砼 ──
    "防渗混凝土": "防水混凝土",
    "抗渗混凝土": "防水混凝土",
    "防渗砼": "防水混凝土",
    "抗渗砼": "防水混凝土",
    "防水砼": "防水混凝土",
    "豆石砼": "豆石混凝土",
    "细石砼": "细石混凝土",
    "砼": "混凝土",
    "钢砼": "钢筋混凝土",
    # ── 沥青 ──
    "热拌沥青混合料": "沥青混凝土",
    "沥青混合料": "沥青混凝土",
    "AC混合料": "沥青混凝土",
    "沥青砼": "沥青混凝土",
    "沥青路面料": "沥青混凝土",
    "热拌料": "沥青混凝土",
    # ── 电线电缆 ──
    "绝缘导线": "绝缘电线",
    "BV导线": "绝缘电线",
    "铜芯绝缘线": "绝缘电线",
    "铜芯塑料线": "绝缘电线",
    "高压导线": "电力电缆",
    "输电电缆": "电力电缆",
    "动力电缆": "电力电缆",
    "弱电线缆": "控制电缆",
    "仪表电缆": "控制电缆",
    # ── 模板 ──
    "模板工": "模板制安",
    "木工": "木模板",
    "模板支拆": "模板制安",
    "木模安装": "模板制安",
}


# 常见材料列表（按长度降序匹配，优先长词）
# 含行业常用别名和省略形式，方便从用户查询中抽取材料名
MATERIAL_LIST = [
    '装配式混凝土预制构件', '预制混凝土楼板', '预制叠合楼板', '预制外墙板', '预制楼梯',
    '预制混凝土墙板', '预制混凝土梁', '预制混凝土柱', '预制混凝土阳台', '预制内墙条板',
    '电力电缆',
    '加气混凝土砌块', '普通混凝土多排孔空心砌块', '普通混凝土空心砌块', '普通混凝土实心砖',
    '普通混凝土门套砖', '普通混凝土实心配套砖', '机制混凝土人行道路面砖', '机制混凝土路面环保砖',
    '机制混凝土路面透水砖', '覆膜建筑模板', '脚手架钢管', '松杂木脚手板', '阻燃型A级密目式安全立网',
    '热轧光圆钢筋', '热轧带肋钢筋', '普通硅酸盐水泥', '普通预拌混凝土', '泵送预拌混凝土',
    '湿拌抹灰砂浆', '湿拌砌筑砂浆', '普通沥青混凝土', '改性沥青混凝土', '乳化沥青',
    # 别名 / 省略形式 — 让提取器能从用户查询词中找到材料
    '防渗混凝土', '抗渗混凝土', '防渗砼', '抗渗砼', '防水砼', '豆石砼', '钢砼',
    '热拌沥青混合料', '沥青混合料', 'AC混合料', '沥青砼',
    '绝缘导线', 'BV导线', '铜芯绝缘线', '高压导线', '输电电缆', '动力电缆',
    '弱电线缆', '仪表电缆', '模板工', '模板支拆', '木模安装', '砼',
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
_FEE_STANDARD_HINT_PATTERN = re.compile(r"费率标准|推荐费率|企业管理费|利润|安全文明施工费|履约担保手续费|夜间施工增加费|总包管理服务费|暂列金额|优质优价奖励费")
_FORMULA_EXPLAIN_PATTERN = re.compile(r"计算方法|计算公式|计算规则|公式|怎么计算|如何计算")
# Detect numeric-input calculation problems: e.g. "人工费100万、材料费200万、机械费50万 ... 利润为多少"
# Pattern: at least two cost items with explicit numeric values, plus a formulaic target (利润/管理费/总价).
_NUMERIC_CALC_INPUT_PATTERN = re.compile(
    r"(?:人工费|材料费|机械费|设备费|工料机|管理费)\s*[为是＝=]?\s*\d+(?:\.\d+)?\s*(?:万|元|亿)?"
)
_NUMERIC_CALC_TARGET_PATTERN = re.compile(
    r"(?:利润|企业管理费|管理费|总造价|工程造价|总价|合计|为多少|是多少)"
)
_FEE_COMPARISON_HINT_PATTERN = re.compile(r"参考范围|推荐费率|是否一致|一致吗|是否相同|相同吗|一样吗|有无差异|差异|区别|不同")
_FEE_ITEM_PATTERN = re.compile(
    r"企业管理费|安全文明施工费费率部分|安全文明施工费|履约担保手续费|夜间施工增加费|"
    r"总包管理服务费及发包人供应材料（设备）保管费|总包管理服务费|发包人供应材料（设备）保管费|"
    r"暂列金额|优质优价奖励费|赶工措施费|赶工费|产业工人职业训练专项经费|利润"
)
_FEE_TARGET_HINT_PATTERN = re.compile(r"推荐系数|参考范围|系数是多少|系数为多少|推荐费率")
_FILL_REQUIREMENT_HINT_PATTERN = re.compile(r"填写|怎么填|填报|按什么要求|应按什么")
_FILL_REQUIREMENT_PREFIX_PATTERN = re.compile(r"^(?:工程项目中|项目中|工程概况表中|工程概况中|表中|其中)?")
_FILL_REQUIREMENT_SUFFIX_PATTERN = re.compile(r"(?:要)?(?:按照什么要求填写|按什么要求填写|应按什么要求填写|应如何填写|如何填写|怎么填写|填写要求)[？?]?$")
_FILL_FIELD_PATTERN = re.compile(
    r"施工地点|项目地点|项目编号|施工许可工程编号|投资来源|项目名称|标段名称|项目类别|项目发包方式|"
    r"施工合同形式|结构类型|开竣工日期|工程造价文件类型|编制日期|执行清单|执行定额|费率标准|"
    r"价格信息采用期次|甲供材料设备|净下浮率|其他情况说明"
)
_APPENDIX_STANDARD_TITLE_PATTERN = re.compile(
    r"(深圳市)?[\u4e00-\u9fa5A-Za-z（）()《》·\-]{4,}?(?:标准|定额|办法|规定|通知)(?:（试行）|（暂行）|（试用）)?"
)
_MATERIAL_QUERY_NOISE_RE = re.compile(
    r"深圳市?|信息价|工程建设|建设工程|材料价格|价格|多少钱|多少|是什么|是多少|请问|根据|查询|检索|"
    r"最新|当前|本月|当月|今年|中|的|及其|是多少元"
)


class QueryAnalysis(TypedDict):
    intent: str          # 'price' | 'semantic' | 'calculation' | 'comparison' | 'trend_chart' | 'standard_ref'
    entities: dict       # {year_month, material_name, material_names, spec, unit}
    sub_queries: list    # 分解后的子查询列表


def _classify_intent(query: str) -> str:
    cleaned_query = _strip_question_prefix(query)
    q = cleaned_query.lower()
    period_mentions = re.findall(r"(20\d{2}\s*年\s*\d{1,2}\s*月|20\d{2}-\d{1,2})", cleaned_query)
    # trend_chart: 走势分析（含时间序列）
    if any(re.search(kw, q) is not None if '.' in kw else kw in q for kw in TREND_KEYWORDS):
        return "trend_chart"
    if is_fee_standard_comparison_query(query):
        return "comparison"
    if any(kw in q for kw in COMPARISON_KEYWORDS) and len(period_mentions) >= 2:
        return "comparison"
    # fee standard formula/method explanation should be treated as rule lookup, not numeric calculation
    if _FEE_STANDARD_HINT_PATTERN.search(cleaned_query) and _FORMULA_EXPLAIN_PATTERN.search(cleaned_query):
        return "standard_ref"
    # numeric calculation problem: query supplies cost values and asks for a derived figure
    # e.g. "人工费100万、材料费200万、机械费50万 ... 利润为多少？"
    numeric_inputs = _NUMERIC_CALC_INPUT_PATTERN.findall(cleaned_query)
    if len(numeric_inputs) >= 2 and _NUMERIC_CALC_TARGET_PATTERN.search(cleaned_query):
        return "calculation"
    has_price_keyword = any(kw in q for kw in PRICE_KEYWORDS)
    has_calc_keyword = any(kw in q for kw in CALC_KEYWORDS)
    if has_price_keyword:
        material = _extract_material(cleaned_query)
        year_month = _extract_year_month(cleaned_query)
        explicit_calc = any(kw in q for kw in ("乘以", "除", "加", "减", "合计", "汇总", "百分比"))
        if explicit_calc and (material or "信息价" in cleaned_query):
            return "calculation"
        if material or "信息价" in cleaned_query or year_month:
            return "price"
    # calculation: 明确有公式或数值计算
    if has_calc_keyword and has_price_keyword:
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
    cleaned = _strip_question_prefix(query)
    # 20XX年X月
    m = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", cleaned)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}"
    # 20XX-X 或 20XX-XX
    m = re.search(r"(20\d{2})-(\d{1,2})", cleaned)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}"
    # 省略世纪的年份（如“从25年开始”）
    m = re.search(r"(?<!\d)(2\d)\s*年", cleaned)
    if m:
        return f"20{m.group(1)}"
    # 20XX年 / 20XX版 / 20XX
    m = re.search(r"(20\d{2})\s*年", cleaned)
    if m:
        return m.group(1)
    m = re.search(r"(20\d{2})\s*版", cleaned)
    if m:
        return m.group(1)
    m = re.search(r"\b(20\d{2})\b", cleaned)
    if m:
        return m.group(1)
    return ""


_cc_aliases_loaded = False


def _load_cc_aliases() -> None:
    """从 canonical_concepts 表补充别名到 _MATERIAL_NORMALIZE（启动时调用一次）"""
    global _cc_aliases_loaded
    if _cc_aliases_loaded:
        return
    try:
        from app.agent.tools import _get_pg_conn, _put_pg_conn
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT aliases, normalized_name FROM canonical_concepts "
                    "WHERE aliases IS NOT NULL AND array_length(aliases, 1) > 0"
                )
                rows = cur.fetchall()
        finally:
            _put_pg_conn(conn)
        for row in rows:
            aliases = row[0] or []
            canonical = (row[1] or "").strip()
            if not canonical:
                continue
            for alias in aliases:
                alias = alias.strip()
                if alias and alias != canonical and alias not in _MATERIAL_NORMALIZE:
                    _MATERIAL_NORMALIZE[alias] = canonical
        _cc_aliases_loaded = True
    except Exception:
        _cc_aliases_loaded = True  # 失败也不重试


def _normalize_material(name: str) -> str:
    """Map alias/abbreviation to canonical material name used in price_records.
    Returns original name if no mapping found."""
    _load_cc_aliases()
    # Exact alias match first
    if name in _MATERIAL_NORMALIZE:
        return _MATERIAL_NORMALIZE[name]
    # Suffix/substring match: e.g. "每立方防渗混凝土" → find longest alias that is a substring
    best = None
    for alias, canonical in _MATERIAL_NORMALIZE.items():
        if alias in name and (best is None or len(alias) > len(best)):
            best = alias
    if best:
        # Replace the matched alias with canonical name in the original string
        return name.replace(best, _MATERIAL_NORMALIZE[best])
    return name


def _extract_material(query: str) -> str:
    normalized_query = re.sub(r"\s+", "", query or "").replace("～", "~").replace("㎡", "m²")
    for mat in sorted(MATERIAL_LIST, key=len, reverse=True):
        candidate = mat.replace("～", "~").replace("㎡", "m²")
        if candidate in normalized_query:
            return _normalize_material(mat)

    # 先去掉时间词和干扰词
    cleaned = re.sub(r"20\d{2}\s*年\s*\d{1,2}\s*月", "", query)
    cleaned = re.sub(r"20\d{2}-\d{1,2}", "", cleaned)
    cleaned = re.sub(r"20\d{2}\s*年?", "", cleaned)
    cleaned = _MATERIAL_QUERY_NOISE_RE.sub("", cleaned)
    cleaned = re.sub(r"[年月日最新当前本个吨方平米立米套组台块片工日支根卷桶箱件价格含税除税信息价造价单价费率材料费人工费机械费设备费租赁费多少钱多钱怎样怎么什么]", "", cleaned)
    matches: list[tuple[int, int, str]] = []
    for mat in MATERIAL_LIST:
        start = 0
        while True:
            idx = cleaned.find(mat, start)
            if idx == -1:
                break
            matches.append((idx, idx + len(mat), mat))
            start = idx + 1
    if matches:
        matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
        merged_start, merged_end, _ = matches[0]
        for start, end, _ in matches[1:]:
            if start <= merged_end:
                merged_end = max(merged_end, end)
            elif start == merged_end:
                merged_end = end
            else:
                break
        merged = cleaned[merged_start:merged_end].strip("，,。；;：:\"'“”‘’（）()[]【】 ")
        if merged:
            return _normalize_material(merged)
    # 按长度降序匹配，优先匹配长词
    for mat in sorted(MATERIAL_LIST, key=len, reverse=True):
        if mat in cleaned:
            return _normalize_material(mat)
    return ""


def _extract_materials(query: str) -> list[str]:
    normalized_query = re.sub(r"\s+", "", query or "").replace("～", "~").replace("㎡", "m²")
    if not normalized_query:
        return []

    matches: list[tuple[int, int, str]] = []
    for mat in sorted(MATERIAL_LIST, key=len, reverse=True):
        candidate = mat.replace("～", "~").replace("㎡", "m²")
        start = 0
        while True:
            idx = normalized_query.find(candidate, start)
            if idx == -1:
                break
            matches.append((idx, idx + len(candidate), mat))
            start = idx + 1

    if not matches:
        material = _extract_material(query)
        return [material] if material else []

    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    occupied: list[tuple[int, int]] = []
    selected: list[tuple[int, str]] = []
    for start, end, material in matches:
        if any(not (end <= left or start >= right) for left, right in occupied):
            continue
        occupied.append((start, end))
        selected.append((start, material))

    selected.sort(key=lambda item: item[0])
    unique_materials: list[str] = []
    for _, material in selected:
        if material not in unique_materials:
            unique_materials.append(material)
    return unique_materials[:4]


def _extract_specification(query: str) -> str:
    # 先去掉年份，避免 "2024" 被误识别为规格
    cleaned = _strip_question_prefix(query)
    cleaned = re.sub(r"20\d{2}\s*年\s*\d{1,2}\s*月", "", cleaned)
    cleaned = re.sub(r"20\d{2}-\d{1,2}", "", cleaned)
    cable_pattern = re.compile(
        r"(0\.\s*6/\s*1\s*[Kk][Vv]\s*[A-Za-z]{2,}\s*"
        r"\d+\s*[×xX*]\s*\d+(?:\s*\+\s*\d+\s*[×xX*]\s*\d+)?)"
    )
    cable_match = cable_pattern.search(cleaned)
    if cable_match:
        return re.sub(r"\s+", " ", cable_match.group(1)).strip()
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


def _previous_year_month(year_month: str) -> str:
    normalized = _extract_year_month(year_month)
    if not re.match(r"^\d{4}-\d{2}$", normalized):
        return ""
    year, month = normalized.split("-", 1)
    y = int(year)
    m = int(month)
    if m == 1:
        return f"{y - 1}-12"
    return f"{y}-{m - 1:02d}"


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


def is_fee_formula_query(query: str) -> bool:
    normalized = (query or "").strip()
    return bool(_FEE_STANDARD_HINT_PATTERN.search(normalized) and _FORMULA_EXPLAIN_PATTERN.search(normalized))


def is_fee_standard_comparison_query(query: str) -> bool:
    normalized = (query or "").strip()
    years = re.findall(r"(20\d{2})\s*版?", normalized)
    return bool(
        len(set(years)) >= 2
        and _FEE_STANDARD_HINT_PATTERN.search(normalized)
        and _FEE_COMPARISON_HINT_PATTERN.search(normalized)
    )


def extract_fee_formula_search_term(query: str) -> str:
    normalized = (query or "").strip()
    year_match = re.search(r"(20\d{2})\s*版?", normalized)
    year = year_match.group(1) if year_match else ""
    item_match = _FEE_ITEM_PATTERN.search(normalized)
    item = item_match.group(0) if item_match else ""

    # Choose target keyword based on what the question is asking for.
    target_match = _FEE_TARGET_HINT_PATTERN.search(normalized)
    if target_match:
        hit = target_match.group(0)
        if "参考范围" in hit:
            target = "参考范围"
        elif "推荐费率" in hit:
            target = "推荐费率"
        else:
            target = "推荐系数"
    else:
        target = "计算公式"

    if year and item:
        return f"{year} {item} {target}"
    if year:
        return f"{year} 费率标准 {target}"
    if item:
        return f"{item} {target}"
    return normalized


def extract_fee_standard_comparison_queries(query: str) -> list[str]:
    normalized = (query or "").strip()
    years: list[str] = []
    for year in re.findall(r"(20\d{2})\s*版?", normalized):
        if year not in years:
            years.append(year)

    item_match = _FEE_ITEM_PATTERN.search(normalized)
    item = item_match.group(0) if item_match else "费率"
    if item == "利润":
        item = "利润率"

    target = "推荐费率" if "推荐费率" in normalized and "参考范围" not in normalized else "参考范围"
    return [f"{year} {item} {target}" for year in years]


def is_fill_requirement_query(query: str) -> bool:
    normalized = (query or "").strip()
    return bool(_FILL_REQUIREMENT_HINT_PATTERN.search(normalized))


def extract_fill_requirement_search_term(query: str) -> str:
    normalized = (query or "").strip()
    field_match = _FILL_FIELD_PATTERN.search(normalized)
    if field_match:
        return field_match.group(0)

    cleaned = _FILL_REQUIREMENT_PREFIX_PATTERN.sub("", normalized)
    cleaned = _FILL_REQUIREMENT_SUFFIX_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"[，,。；;：:“”\"'‘’（）()【】\[\]\s]", "", cleaned)
    return cleaned


def extract_appendix_standard_title(query: str) -> str:
    normalized = (query or "").strip()
    match = _APPENDIX_STANDARD_TITLE_PATTERN.search(normalized)
    if not match:
        return ""
    return match.group(0).strip("《》")


def extract_appendix_standard_terms(query: str) -> list[str]:
    normalized = (query or "").strip()
    title = extract_appendix_standard_title(normalized)
    remainder = normalized.replace(title, "", 1) if title else normalized
    candidates: list[str] = []

    explicit_patterns = [
        r"预制箱体应用比例",
        r"装饰集成率",
        r"综合评分",
        r"适用范围",
        r"适用于",
        r"±?\s*0\.00\s*以上",
        r"土\s*0\.00\s*以上",
    ]
    for pattern in explicit_patterns:
        for match in re.finditer(pattern, remainder):
            value = re.sub(r"\s+", "", match.group(0))
            if value and value not in candidates:
                candidates.append(value)

    cleaned = re.sub(
        r"[？?，,。；;：:“”\"'‘’（）()\[\]【】]|适用于|适用|大于多少|多少|什么|是否|如何|怎么|请问|"
        r"模块化建筑|工程|定额|标准|通知|规定|办法|以上|以下|部分|单体|栋|建筑|"
        r"的工程量计算规则|工程量计算规则|的计算规则|计算规则",
        " ",
        remainder,
    )
    for token in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9\.±]{3,}", cleaned):
        token = token.strip()
        # Strip leading conjunctive particles ("中"/"对"/"关于"/...) and trailing copula
        # so 'extract_appendix_standard_terms' yields clean noun phrases for FTS.
        token = re.sub(r"^(?:中|对于|对|关于|按照|按|根据)", "", token)
        token = re.sub(r"(?:是|为)$", "", token)
        if len(token) >= 3 and token not in candidates:
            candidates.append(token)

    return candidates[:4]


def is_appendix_standard_query(query: str) -> bool:
    title = extract_appendix_standard_title(query)
    return bool(title and any(hint in (query or "") for hint in ("适用", "比例", "范围", "定义", "工期", "计算", "规则")))


def _decompose(query: str, intent: str) -> list[str]:
    """
    复杂查询分解为子查询。
    仅处理 comparison 和 price 的多时间/多材料情况。
    """
    sub_queries = []
    materials = _extract_materials(query)
    primary_material = materials[0] if materials else _extract_material(query)

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

        material = primary_material

        if len(year_months) >= 2 and material:
            for ym in year_months:
                sub_queries.append(f"{ym} {material} 价格")
            sub_queries.append(f"计算 {material} {' 与 '.join(year_months)} 价格差异")
        elif len(year_months) >= 2:
            for ym in year_months:
                sub_queries.append(f"{ym} 建材价格行情")
        else:
            sub_queries.append(query)

    elif intent in {"price", "trend_chart"}:
        period = _extract_year_month(query)
        previous_period = _previous_year_month(period) if period else ""
        if (
            len(materials) >= 2
            and period
            and any(token in query for token in ("较上月", "上月", "环比", "变化幅度"))
        ):
            for material in materials:
                if previous_period:
                    sub_queries.append(f"{previous_period} {material} 价格")
                sub_queries.append(f"{period} {material} 价格")
                if previous_period:
                    sub_queries.append(f"计算 {material} {period} 较 {previous_period} 变化幅度")
            return sub_queries

        if len(materials) >= 2 and period:
            for material in materials:
                sub_queries.append(f"{period} {material} 价格")
            return sub_queries

        # 检测是否有隐含对比（如 "现在多少钱" 暗示与历史对比）
        if re.search(r"现在|最近|最新|当前|本月", query):
            material = primary_material
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
        normalized_query = _strip_question_prefix(query)
        intent = _classify_intent(normalized_query)
        materials = _extract_materials(normalized_query)
        entities = {
            "year_month": _extract_year_month(normalized_query),
            "material_name": materials[0] if materials else _extract_material(normalized_query),
            "material_names": materials,
            "specification": _extract_specification(normalized_query),
            "unit": _extract_unit(normalized_query),
        }
        sub_queries = _decompose(normalized_query, intent)
        analysis = QueryAnalysis(intent=intent, entities=entities, sub_queries=sub_queries)
        logger.info(f"[analyzer] query='{normalized_query[:50]}' intent={intent} sub_queries={sub_queries}")
        return analysis

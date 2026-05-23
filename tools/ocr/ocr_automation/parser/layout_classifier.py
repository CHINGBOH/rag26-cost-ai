"""
版面分类器
根据OCR文字内容和关键词识别页面类型
"""

import re
from typing import List, Dict, Optional


# 页面类型优先级（从高到低）
PAGE_TYPES = [
    'cover',      # 封面
    'toc',        # 目录
    'chart',      # 趋势图/图表页
    'index_table',# 造价指数/材料费指数表
    'rental_table',# 租赁价格表
    'labor_table',# 市场劳务价格表
    'prefab_table',# 装配式构件价格表
    'formula_table',# 公式价格表（通风空调器材等）
    'price_table',# 建筑材料价格表（默认表格）
    'article',    # 普通文章/说明文字
]

# 分类关键词规则
CLASS_RULES = {
    'cover': {
        'required': [],
        'keywords': ['深圳建设工程', '价格信息', '总第', '月刊'],
        'exclude': ['目录', 'contents', '序号', '材料名称'],
        'max_cells': 20,
    },
    'toc': {
        'required': [],
        'keywords': ['目录', 'contents', '站长寄语', '政策法规', '造价信息'],
        'exclude': ['序号', '材料名称', '价格（元）'],
        'min_cells': 20,
    },
    'chart': {
        'required': [],
        'keywords': ['趋势图', '变化趋势', '走势图', '指数图', '材料费指数图'],
        'exclude': [],
    },
    'index_table': {
        'required': [],
        'keywords': ['造价指数', '材料费指数', '建安工程', '市政工程', '价格指数'],
        'exclude': ['租赁', '劳务', '材料价格'],
    },
    'rental_table': {
        'required': ['序号'],
        'keywords': ['租赁价格', '台·月', '起重机械', '脚手架', '周转材料'],
        'exclude': [],
    },
    'labor_table': {
        'required': ['序号'],
        'keywords': ['市场劳务价格', '劳务计件', '工种名称', '工日'],
        'exclude': ['租赁'],
    },
    'prefab_table': {
        'required': ['序号'],
        'keywords': ['装配式', '预制构件', '预制混凝土', '叠合板'],
        'exclude': [],
    },
    'formula_table': {
        'required': ['序号'],
        'keywords': ['价格计算公式', '执行机构', '风阀', '排烟阀', '止回阀'],
        'exclude': [],
    },
    'price_table': {
        'required': ['序号'],
        'keywords': ['材料名称', '型号、规格', '单位', '价格（元）', '建筑材料价格'],
        'exclude': ['租赁', '劳务', '指数', '装配式'],
    },
}


def classify_page(full_text: str, cell_count: int = 0) -> str:
    """
    根据全文和单元格数量分类页面类型
    
    Args:
        full_text: 页面所有文字拼接
        cell_count: OCR识别到的文字块数量
    
    Returns:
        page_type: 页面类型字符串
    """
    text = full_text.lower()
    scores = {}
    
    for ptype, rule in CLASS_RULES.items():
        score = 0
        matched = True
        
        # required keywords must exist
        for kw in rule.get('required', []):
            if kw not in full_text:
                matched = False
                break
        if not matched:
            continue
        
        # exclude keywords must NOT exist
        for kw in rule.get('exclude', []):
            if kw in full_text:
                matched = False
                break
        if not matched:
            continue
        
        # keywords scoring
        for kw in rule.get('keywords', []):
            if kw.lower() in text:
                score += 1
        
        # cell count constraints
        max_cells = rule.get('max_cells')
        if max_cells is not None and cell_count > max_cells:
            score = 0
        min_cells = rule.get('min_cells')
        if min_cells is not None and cell_count < min_cells:
            score = 0
        
        scores[ptype] = score
    
    if not scores:
        return 'article'
    
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        # fallback: if it has table-like structure
        if '序号' in full_text and ('价格' in full_text or '元' in full_text):
            return 'price_table'
        return 'article'
    
    return best


def is_continued_page(full_text: str) -> bool:
    """判断是否为续前页"""
    markers = ['(续前)', '续前', 'continued', '（续前）']
    return any(m in full_text for m in markers)


def detect_page_category_header(rows: List[List[Dict]]) -> Optional[str]:
    """
    从表格行中检测分类标题行
    
    例如：'二、水泥、砖瓦灰砂石及混凝土制品'
    """
    category_pattern = re.compile(r'^[一二三四五六七八九十]+[、\.．]\s*')
    
    for row in rows:
        texts = [c['text'].strip() for c in row if c['text'].strip()]
        if len(texts) == 1:
            t = texts[0]
            if category_pattern.match(t):
                return t
            # 无序号但明显是分类的
            if any(kw in t for kw in ['钢材', '水泥', '混凝土', '砂浆', '砖瓦', '木材', '玻璃',
                                       '涂料', '管材', '电线电缆', '电气', '五金', '防水', '保温',
                                       '门窗', '幕墙', '装配式', '金属', '塑料', '橡胶', '陶瓷',
                                       '石材', '石膏', '沥青', '路基', '桥梁', '隧道', '通风空调',
                                       '灯具', '光源', '线槽', '桥架', '电线管', '电力电缆',
                                       '通信电缆', '对绞电缆']):
                if len(t) < 50 and not any(c.isdigit() for c in t[:5]):
                    return t
    return None

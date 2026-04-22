"""
分类推理器
解决跨页表格分类丢失问题，通过关键词推理材料分类
"""

import re
from typing import Optional, List, Dict


# 材料名称 → 分类映射关键词
CATEGORY_KEYWORDS = {
    '一、黑色及有色金属': ['钢筋', '圆钢', '角钢', '槽钢', '工字钢', '扁钢', '方钢', '钢板', '钢管',
                         '钢丝', '钢绞线', '镀锌', '无缝钢管', '焊接钢管', '热轧', '冷轧', 'H型钢',
                         '不锈钢', '彩钢板', '预埋件', '钢套管'],
    '二、水泥、砖瓦灰砂石及混凝土制品': ['水泥', '混凝土', '砂浆', '砖', '瓦', '砂石', '碎石', '卵石',
                                     '加气块', '砌块', '管桩', '路缘石', '预制', '商砼'],
    '三、玻璃及玻璃制品': ['玻璃', '钢化玻璃', '夹层玻璃', '中空玻璃', '幕墙'],
    '四、涂料及防腐、防水材料': ['涂料', '油漆', '防腐', '防水', '卷材', '聚氨酯', '沥青', '防火涂料'],
    '五、油品、化工原料及胶粘材料': ['柴油', '汽油', '润滑油', '机油', '液压油', '油漆稀释剂'],
    '六、保温材料': ['保温', '岩棉', '玻璃棉', '挤塑板', '聚苯板', '橡塑', '硅酸铝'],
    '七、周转材料及五金工具': ['模板', '脚手架', '扣件', '顶托', '钢笆', '安全网', '步步紧'],
    '八、道路桥梁专用材料': ['沥青混凝土', '土工布', '土工格栅', '支座', '伸缩缝', '护栏'],
    '九、混凝土、砂浆及其他配合材料': ['泵送', '混凝土', '砂浆', '添加剂', '减水剂', '膨胀剂', '速凝剂'],
    '十、管材': ['钢管', 'PVC', 'PE', 'PPR', '排水管', '给水管', '波纹管', '铸铁管', '钢筋混凝土管'],
    '十一、电线电缆': ['电线', '电缆', 'BV', 'YJV', 'KVV', '控制电缆', '通信电缆', '对绞电缆',
                     '同轴电缆', '光缆', '电力电缆', '绝缘电线'],
    '十二、通风空调器材': ['风口', '风阀', '风管', '风机', '消声器', '百叶', '防火阀', '排烟阀',
                         '止回阀', '散流器', '静压箱'],
    '十三、灯具、光源': ['灯', '灯具', '光源', 'LED', '荧光灯', '筒灯', '射灯', '应急灯', '吸顶灯'],
    '十四、电气线路敷设材料': ['线槽', '桥架', '电线管', '镀锌管', 'JDG', 'KBG', '接线盒', '配电箱',
                             '开关', '插座', '母线槽'],
    '十五、电气装备用电线电缆': ['电线', '电缆', 'BV', 'BVV', 'RVS', 'RVV', '护套线', '绞型软线'],
    '租赁价格': ['塔式起重机', '施工电梯', '吊篮', '脚手架', '钢管', '扣件', '顶托', '钢笆',
                 '盘扣', '铝合金模板'],
    '市场劳务价格': ['钢筋工', '模板工', '架子工', '混凝土工', '抹灰工', '油漆工', '焊工', '电工',
                     '瓦工', '防水工', '玻璃工', '管工', '机械工'],
    '装配式构件': ['预制', '叠合板', '装配式', '凸窗', '承重墙', '非承重墙', '实心墙', '轻骨料'],
    '定额人工费': ['普工', '技工', '高级技工', '人工费指数'],
}


def infer_category(material_name: str, spec: str = "") -> Optional[str]:
    """
    根据材料名称和规格推断分类
    """
    if not material_name:
        return None
    
    search_text = material_name + " " + spec
    
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in search_text:
                return category
    
    return None


def resolve_categories(records: List[Dict], page_type: str = 'price_table') -> List[Dict]:
    """
    批量解析分类：先按页排序，跨页传播已知分类，再对None进行推理
    
    Args:
        records: 记录列表，每条可能包含'category'和'page_number'
        page_type: 页面类型
    
    Returns:
        补全分类后的记录列表
    """
    if not records:
        return records
    
    # 按page_number排序，确保跨页传播正确
    sorted_recs = sorted(records, key=lambda r: (r.get('page_number', 0), r.get('seq_no', 0) or 0))
    
    # 第一步：前向传播已知分类（包括跨页）
    last_category = None
    last_page = None
    for rec in sorted_recs:
        current_page = rec.get('page_number')
        
        # 如果换了新页，且新页是续前页类型，继续传播
        if current_page != last_page:
            last_page = current_page
        
        if rec.get('category'):
            last_category = rec['category']
        elif last_category and page_type in ('price_table', 'rental_table', 'labor_table', 'prefab_table', 'formula_table'):
            rec['category'] = last_category
    
    # 第二步：对仍为None的记录进行关键词推理
    for rec in sorted_recs:
        if not rec.get('category'):
            inferred = infer_category(rec.get('material_name', ''), rec.get('spec', ''))
            if inferred:
                rec['category'] = inferred
            else:
                # 兜底：根据page_type给默认分类
                if page_type == 'rental_table':
                    rec['category'] = '租赁价格'
                elif page_type == 'labor_table':
                    rec['category'] = '市场劳务价格'
                elif page_type == 'prefab_table':
                    rec['category'] = '装配式构件'
                elif page_type == 'index_table':
                    rec['category'] = '定额人工费'
                elif page_type == 'formula_table':
                    rec['category'] = '通风空调器材'
    
    return sorted_recs


def infer_page_type_from_neighbors(pages: List[Dict]) -> List[Dict]:
    """
    基于相邻页面类型修正分类（例如续前页被误判为article时修正）
    """
    for i, page in enumerate(pages):
        if page['page_type'] != 'article':
            continue
        
        # 检查是否为续前页
        full_text = page.get('full_text', '')
        if '(续前)' not in full_text and '续前' not in full_text:
            continue
        
        # 找前一个非article页面继承类型
        prev_type = None
        for j in range(i - 1, -1, -1):
            if pages[j]['page_type'] != 'article':
                prev_type = pages[j]['page_type']
                break
        
        if prev_type and prev_type in ('price_table', 'rental_table', 'labor_table', 
                                        'index_table', 'prefab_table', 'formula_table'):
            page['page_type'] = prev_type
            page['_inherited_from'] = prev_type
    
    return pages

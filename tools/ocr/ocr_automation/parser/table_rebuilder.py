"""
表格重建引擎
基于OCR文字块坐标进行行列聚类，重建表格结构
"""

import re
from typing import List, Dict, Optional, Tuple
from collections import defaultdict


def detect_table_bounds(page_height: int, page_width: int) -> Dict[str, float]:
    """
    从页面尺寸推断合理的表格聚类阈值

    A4 纸张参考：210mm × 297mm，72 DPI = 595×842 pixels

    Args:
        page_height: 页面高度（像素）
        page_width: 页面宽度（像素）

    Returns:
        {
            'y_threshold': 行聚类阈值,
            'x_threshold': 列聚类阈值,
            'dpi_estimate': 估计 DPI
        }

    Example:
        >>> bounds = detect_table_bounds(842, 595)
        >>> bounds['y_threshold']  # 应为 ~18-20
    """
    # A4 纸高度：11.69 英寸 @ 72 DPI = 842 像素
    dpi_estimate = page_height / 11.69 if page_height > 0 else 72

    # 基于字号估计：10-12pt 文本约 13-16 像素高
    # 行间距通常 20-25 像素
    # 使用 DPI 进行缩放
    y_threshold = max(15, int(dpi_estimate * 0.25 / 72))
    x_threshold = max(20, int(dpi_estimate * 0.35 / 72))

    return {
        'y_threshold': y_threshold,
        'x_threshold': x_threshold,
        'dpi_estimate': dpi_estimate
    }


def cluster_rows_adaptive(
    cells: List[Dict],
    page_height: int = 842,
    page_width: int = 595,
    force_threshold: Optional[int] = None
) -> List[List[Dict]]:
    """
    自适应行聚类

    不再依赖硬编码的阈值，而是根据页面尺寸动态计算

    Args:
        cells: OCR 文字块列表，每个块包含 'x', 'y', 'text' 等字段
        page_height: 页面高度
        page_width: 页面宽度
        force_threshold: 强制指定阈值（用于调试或特殊情况）

    Returns:
        按行分组的文字块列表
    """
    if not cells:
        return []

    # 确定阈值
    if force_threshold is not None:
        y_threshold = force_threshold
    else:
        bounds = detect_table_bounds(page_height, page_width)
        y_threshold = bounds['y_threshold']

    cells_sorted = sorted(cells, key=lambda c: c.get('y', 0))
    rows = []
    current_row = [cells_sorted[0]]

    for c in cells_sorted[1:]:
        # 改进：计算当前行的平均 Y 坐标作为基准
        row_y_positions = [cell.get('y', 0) for cell in current_row]
        avg_row_y = sum(row_y_positions) / len(row_y_positions)

        if abs(c.get('y', 0) - avg_row_y) < y_threshold:
            current_row.append(c)
        else:
            # 排序后添加到结果
            current_row.sort(key=lambda cell: cell.get('x', 0))
            rows.append(current_row)
            current_row = [c]

    if current_row:
        current_row.sort(key=lambda cell: cell.get('x', 0))
        rows.append(current_row)

    return rows


def cluster_columns_adaptive(
    rows: List[List[Dict]],
    page_height: int = 842,
    page_width: int = 595,
    force_threshold: Optional[int] = None
) -> Dict[int, float]:
    """
    自适应列聚类

    Args:
        rows: 按行分组的文字块列表
        page_height: 页面高度
        page_width: 页面宽度
        force_threshold: 强制指定阈值

    Returns:
        {col_index: x_center}
    """
    if not rows:
        return {}

    # 确定阈值
    if force_threshold is not None:
        x_threshold = force_threshold
    else:
        bounds = detect_table_bounds(page_height, page_width)
        x_threshold = bounds['x_threshold']

    all_x = []
    for row in rows:
        for c in row:
            all_x.append(c.get('x', 0))

    if not all_x:
        return {}

    all_x.sort()
    cols = [[all_x[0]]]

    for x in all_x[1:]:
        if abs(x - sum(cols[-1]) / len(cols[-1])) < x_threshold:
            cols[-1].append(x)
        else:
            cols.append([x])

    col_centers = {i: sum(c) / len(c) for i, c in enumerate(cols)}
    return col_centers


def cluster_rows(cells: List[Dict], y_threshold: int = 22) -> List[List[Dict]]:
    """按Y坐标聚类为行"""
    if not cells:
        return []
    cells_sorted = sorted(cells, key=lambda c: c['y'])
    rows = []
    current_row = [cells_sorted[0]]
    for c in cells_sorted[1:]:
        if abs(c['y'] - current_row[0]['y']) < y_threshold:
            current_row.append(c)
        else:
            current_row.sort(key=lambda c: c['x'])
            rows.append(current_row)
            current_row = [c]
    if current_row:
        current_row.sort(key=lambda c: c['x'])
        rows.append(current_row)
    return rows


def cluster_columns(rows: List[List[Dict]], x_threshold: int = 30) -> Dict[int, List[float]]:
    """
    基于所有行的X坐标聚类为列
    返回: {col_index: [x_center1, x_center2, ...]}
    """
    all_x = []
    for row in rows:
        for c in row:
            all_x.append(c['x'])
    
    if not all_x:
        return {}
    
    all_x.sort()
    cols = [[all_x[0]]]
    for x in all_x[1:]:
        if abs(x - sum(cols[-1]) / len(cols[-1])) < x_threshold:
            cols[-1].append(x)
        else:
            cols.append([x])
    
    col_centers = {i: sum(c) / len(c) for i, c in enumerate(cols)}
    return col_centers


def assign_columns(row: List[Dict], col_centers: Dict[int, float]) -> Dict[int, str]:
    """将一行中的单元格分配到最近的列"""
    result = {}
    for c in row:
        best_col = min(col_centers.keys(), key=lambda i: abs(c['x'] - col_centers[i]))
        if best_col in result:
            # 合并同一列的文本（通常是因为换行）
            result[best_col] += ' ' + c['text']
        else:
            result[best_col] = c['text']
    return result


def rebuild_table(rows: List[List[Dict]], y_threshold: int = 22, x_threshold: int = 30) -> List[Dict[str, str]]:
    """
    重建表格为结构化行数据（原始版本，保留用于兼容性）

    Returns:
        List of dicts, each dict represents a row with column_index -> text
    """
    col_centers = cluster_columns(rows, x_threshold)
    if not col_centers:
        return []

    table = []
    for row in rows:
        assigned = assign_columns(row, col_centers)
        table.append(assigned)

    return table


def rebuild_table_adaptive(rows: List[List[Dict]], page_height: int = 842, page_width: int = 595) -> List[Dict[str, str]]:
    """
    自适应表格重建

    使用动态计算的阈值而不是硬编码值

    Args:
        rows: 按行分组的文字块列表
        page_height: 页面高度
        page_width: 页面宽度

    Returns:
        List of dicts, each dict represents a row with column_index -> text
    """
    bounds = detect_table_bounds(page_height, page_width)
    col_centers = cluster_columns_adaptive(rows, page_height, page_width)

    if not col_centers:
        return []

    table = []
    for row in rows:
        assigned = assign_columns(row, col_centers)
        table.append(assigned)

    return table


def detect_header_row(table_rows: List[Dict[str, str]]) -> Optional[int]:
    """检测表头行索引"""
    header_keywords = ['序号', '材料名称', '型号', '规格', '单位', '价格', '名称', '项目', '设备名称']
    for i, row in enumerate(table_rows[:3]):
        combined = ' '.join(row.values())
        match_count = sum(1 for kw in header_keywords if kw in combined)
        if match_count >= 2:
            return i
    return None


def merge_multiline_cells(rows: List[List[Dict]]) -> List[List[Dict]]:
    """
    合并跨行断开的单元格（某些OCR会把一个单元格拆成多行）
    检测条件：某行只有一个单元格有内容，且其x坐标与上一行某单元格接近
    """
    merged = []
    pending_merge = {}  # col_index -> {text, y, x}
    
    for row in rows:
        non_empty = [(i, c) for i, c in enumerate(row) if c['text'].strip()]
        
        # 如果这一行内容很少，可能是上一行的续行
        if len(non_empty) <= 2 and merged:
            for i, c in non_empty:
                # 找上一行最近的单元格
                prev_row = merged[-1]
                best = min(prev_row, key=lambda pc: abs(pc['x'] - c['x']))
                if abs(best['x'] - c['x']) < 50:
                    best['text'] += ' ' + c['text']
                    continue
            merged.append(row)
        else:
            merged.append(row)
    
    return merged


def parse_standard_price_table(
    rows: List[List[Dict]],
    page_height: int = 842,
    page_width: int = 595,
    page_type: str = 'price_table'
) -> List[Dict]:
    """
    解析标准价格表格（序号|材料名称|型号规格|单位|价格）

    现在支持自适应阈值以适应不同分辨率的 PDF

    Args:
        rows: OCR 文字块行列表
        page_height: 页面高度，用于计算动态阈值
        page_width: 页面宽度，用于计算动态阈值
        page_type: 页面类型

    Returns:
        List of record dicts
    """
    # 合并可能的续行
    rows = merge_multiline_cells(rows)

    # 使用自适应阈值重建表格
    table = rebuild_table_adaptive(rows, page_height, page_width)
    if not table:
        return []

    # 检测并跳过表头
    header_idx = detect_header_row(table)
    if header_idx is not None:
        table = table[header_idx + 1:]

    # 跳过杂志页眉行
    filtered = []
    for row in table:
        combined = ' '.join(row.values())
        if 'SZCOST' in combined and len(combined) < 80:
            continue
        if '深圳建设工程价格信息' in combined and len(combined) < 80:
            continue
        if '造价信息' in combined and len(combined) < 50 and '栏目' in combined:
            continue
        filtered.append(row)
    table = filtered

    records = []
    current_category = None

    for row in table:
        texts = list(row.values())
        combined = ' '.join(texts)

        if not combined.strip():
            continue

        # 检测分类行
        non_empty = [t for t in texts if t.strip()]
        if len(non_empty) == 1:
            t = non_empty[0]
            if re.match(r'^[一二三四五六七八九十]+[、\.．]', t) or \
               (any(kw in t for kw in ['钢材', '水泥', '混凝土', '砂浆', '砖瓦', '木材', '玻璃',
                                        '涂料', '管材', '电线电缆', '电气', '五金', '防水', '保温',
                                        '门窗', '幕墙', '装配式', '金属', '塑料', '橡胶', '陶瓷',
                                        '石材', '石膏', '沥青', '路基', '桥梁', '隧道', '通风空调',
                                        '灯具', '光源', '线槽', '桥架', '电线管', '电力电缆',
                                        '通信电缆', '对绞电缆', '电缆']) and len(t) < 50):
                current_category = t
                continue

        # 解析数据行
        rec = parse_data_row_from_cells(texts, current_category, page_type)
        if rec:
            records.append(rec)

    return records


def parse_data_row_from_cells(texts: List[str], category: Optional[str], page_type: str) -> Optional[Dict]:
    """从单元格文本列表解析数据记录"""
    texts = [t.strip() for t in texts if t.strip()]
    if len(texts) < 3:
        return None
    
    seq_no = None
    material_name = None
    spec = None
    unit = None
    price = None
    price_formula = None
    
    # 序号检测
    first = texts[0]
    m = re.match(r'^(\d+)[\.\s]*(.*)', first)
    if m:
        seq_no = int(m.group(1)) if m.group(1).isdigit() else None
        remainder = m.group(2).strip()
        if remainder:
            material_name = remainder
    elif first.isdigit():
        seq_no = int(first)
    else:
        material_name = first
    
    # 根据列数解析
    if len(texts) >= 4:
        if material_name is None:
            material_name = texts[1] if len(texts) > 1 else None
        spec = texts[2] if len(texts) > 2 else None
        unit_price_text = texts[3] if len(texts) > 3 else None
        price_text = texts[4] if len(texts) > 4 else None
        
        if price_text:
            price = _clean_price(price_text)
            unit = _clean_unit(unit_price_text)
        else:
            # 尝试从单字段拆分单位和价格
            if unit_price_text:
                # 检测公式价格：S×200+18, D²×959+50
                if _looks_like_formula(unit_price_text):
                    price_formula = unit_price_text
                else:
                    parts = unit_price_text.split()
                    if len(parts) >= 2:
                        price = _clean_price(parts[-1])
                        unit = _clean_unit(' '.join(parts[:-1]))
                    else:
                        price = _clean_price(unit_price_text)
    elif len(texts) == 3:
        if material_name is None:
            material_name = texts[1] if len(texts) > 1 else None
        unit_price_text = texts[2] if len(texts) > 2 else None
        if unit_price_text:
            if _looks_like_formula(unit_price_text):
                price_formula = unit_price_text
            else:
                parts = unit_price_text.split()
                if len(parts) >= 2:
                    price = _clean_price(parts[-1])
                    unit = _clean_unit(' '.join(parts[:-1]))
                else:
                    price = _clean_price(unit_price_text)
    
    # 验证
    if not material_name or len(material_name) < 2:
        return None
    
    # 对于formula_table，允许没有price但有formula
    if price is None and price_formula is None:
        return None
    if price is not None and (price < 0 or price > 10_000_000):
        return None
    
    return {
        'seq_no': seq_no,
        'category': category,
        'material_name': material_name[:200],
        'spec': (spec or '')[:200],
        'unit': unit[:20] if unit else None,
        'price': price,
        'price_formula': price_formula,
    }


def _clean_price(val: str) -> Optional[float]:
    if not val:
        return None
    s = val.strip().replace(',', '').replace('，', '').replace(' ', '')
    s = re.sub(r'[元\s￥$]+$', '', s)
    try:
        return float(s)
    except Exception:
        return None


def _clean_unit(val: str) -> Optional[str]:
    if not val:
        return None
    s = val.strip()
    units = ['t', 'kg', 'm³', 'm2', '㎡', 'm', '块', '套', '根', '只', '台', '件', '张',
             '个', '卷', '组', '条', '桶', '包', '袋', '吨', '升', 'L', '工日', '台·月',
             '延长米', '延米', '套·月', '组·月', '根·月', '个·月', 't·月']
    for u in units:
        if u in s:
            return u
    if re.match(r'^[a-zA-Z·²³]+$', s):
        return s
    return s if len(s) <= 10 else None


def _looks_like_formula(s: str) -> bool:
    """检测是否为公式价格"""
    return bool(re.search(r'[×\*\+\-÷/]|²|³|[A-Za-z][²³]?\s*[×\*]', s))

#!/usr/bin/env python3
"""
GPU OCR Pipeline for 《深圳建设工程价格信息》2026年1月
Extracts: text, tables, charts
Imports to: PostgreSQL + pgvector (rag_db)
"""

import os
os.environ['LD_LIBRARY_PATH'] = '/usr/local/lib/ollama/cuda_v12:' + os.environ.get('LD_LIBRARY_PATH', '')

import fitz
from rapidocr_onnxruntime import RapidOCR
from PIL import Image
import io
import json
import re
import psycopg2
from psycopg2.extras import execute_values
from pathlib import Path
import hashlib
from collections import defaultdict
import time

PDF_PATH = "/home/l/rag-dashboard/data/knowledge_base/深圳信息价/《深圳建设工程价格信息》2026年1月.pdf"
OUTPUT_DIR = Path("/home/l/rag-dashboard/data/ocr_outputs")
OUTPUT_DIR.mkdir(exist_ok=True)
CHARTS_DIR = OUTPUT_DIR / "charts_2026_01"
CHARTS_DIR.mkdir(exist_ok=True)

DB_CONFIG = dict(host='localhost', dbname='rag_db', user='rag_user', password=os.environ.get('POSTGRES_PASSWORD', 'rag_password'))
DOC_PERIOD = "2026-01"
DOC_FNAME = "《深圳建设工程价格信息》2026年1月.pdf"

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

def doc_code_from_name(filename: str) -> str:
    return hashlib.md5(filename.encode()).hexdigest()[:16]

DOC_CODE = doc_code_from_name(DOC_FNAME)

print("Loading RapidOCR GPU engine...")
ocr_engine = RapidOCR()
print("Engine ready.")

def ocr_page(page, dpi=200):
    pix = page.get_pixmap(dpi=dpi)
    img = Image.open(io.BytesIO(pix.tobytes('png')))
    result = ocr_engine(img)
    cells = []
    if result and result[0]:
        for box in result[0]:
            coords, text, conf = box
            x1, y1 = coords[0]
            x2, y2 = coords[2]
            cells.append({
                'x': (x1+x2)/2, 'y': (y1+y2)/2,
                'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                'text': text, 'conf': conf
            })
    return cells, img

def cluster_rows(cells, y_threshold=22):
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

def classify_page(rows, full_text, img):
    text_lower = full_text.lower()
    
    # 目录/封面优先
    if ('目录' in full_text or '录' in full_text or 'contents' in text_lower) and ('站长寄语' in full_text or '政策法规' in full_text):
        return 'toc'
    if full_text.count('\n') < 5 and ('深圳建设工程' in full_text and '价格信息' in full_text):
        return 'cover'
    
    # 趋势图
    if '趋势图' in full_text or ('变化趋势' in full_text and '价格' in full_text):
        return 'chart'
    
    # 装配式构件
    if '装配式' in full_text and '预制' in full_text and '序号' in full_text:
        return 'prefab_table'
    # 租赁价格
    if '租赁价格' in full_text and '序号' in full_text and ('台·月' in full_text or 't·月' in full_text or '周转材料' in full_text):
        return 'rental_table'
    # 人工费 / 劳务
    if '定额人工费' in full_text and '序号' in full_text:
        return 'labor_table'
    if '市场劳务价格' in full_text and '序号' in full_text:
        return 'labor_table'
    # 造价指数
    if '造价指数' in full_text and '材料费指数' in full_text:
        return 'index_table'
    if '建安、市政工程造价指数' in full_text:
        return 'index_table'
    if '建安、市政工程材料费指数' in full_text:
        return 'index_table'
    # 标准价格表
    has_table_header = '序号' in full_text and '材料名称' in full_text and '价格' in full_text
    if has_table_header:
        if '租赁' in full_text:
            return 'rental_table'
        elif '人工费' in full_text or '工日' in full_text:
            return 'labor_table'
        else:
            return 'price_table'
    return 'article'

def clean_price(val_str):
    if not val_str:
        return None
    s = val_str.strip().replace(',', '').replace('，', '').replace(' ', '')
    s = re.sub(r'[元\s￥$]+$', '', s)
    try:
        return float(s)
    except Exception:
        return None

def clean_unit(val_str):
    if not val_str:
        return None
    s = val_str.strip()
    # 先处理 m3/m2 的变体
    if s in ('m3', 'M3', 'm^3'):
        return 'm³'
    if s in ('m2', 'M2', 'm^2', 'm²'):
        return '㎡'
    units = ['t', 'kg', 'm³', 'm²', 'm2', '㎡', 'm', '块', '套', '根', '只', '台', '件', '张', 
             '个', '卷', '组', '条', '桶', '包', '袋', '吨', '升', 'L', '工日', '台·月',
             '延长米', '延米', '套·月', '组·月']
    for u in units:
        if u in s:
            return u
    if re.match(r'^[a-zA-Z·²³]+$', s):
        return s
    return s if len(s) <= 10 else None

def parse_price_table_rows(rows):
    records = []
    current_category = None
    
    for row in rows:
        texts = [c['text'].strip() for c in row]
        combined = ' '.join(texts)
        
        if '序号' in combined and '材料名称' in combined:
            continue
        if 'SZCOST' in combined and len(combined) < 100:
            continue
        if '深圳建设工程价格信息' in combined and len(combined) < 100:
            continue
        if '续前' in combined and len(combined) < 50:
            continue
        if '(2026年1月价格)' in combined:
            continue
        if '建筑材料价格' in combined and len(combined) < 50:
            continue
        if '造价信息' in combined and len(combined) < 50:
            continue
        
        non_empty = [t for t in texts if t]
        if len(non_empty) == 1:
            t = non_empty[0]
            if re.match(r'^[一二三四五六七八九十]+[、\.．]', t) or \
               any(kw in t for kw in ['钢材', '水泥', '混凝土', '砂浆', '砖瓦', '木材', '玻璃', 
                                       '涂料', '管材', '电线电缆', '电气', '五金', '防水', '保温',
                                       '门窗', '幕墙', '装配式', '金属', '塑料', '橡胶', '陶瓷',
                                       '石材', '石膏', '沥青', '路基', '桥梁', '隧道']):
                current_category = t
                continue
        
        rec = parse_data_row(row, current_category)
        if rec:
            records.append(rec)
    
    return records

def parse_data_row(row, category):
    texts = [c['text'].strip() for c in row]
    non_empty = [(i, t) for i, t in enumerate(texts) if t]
    
    if len(non_empty) < 3:
        return None
    
    seq_no = None
    material_name = None
    spec = None
    unit = None
    price = None
    
    first_text = non_empty[0][1]
    
    m = re.match(r'^(\d+)[\.\s]*(.*)', first_text)
    if m:
        seq_no = int(m.group(1)) if m.group(1).isdigit() else None
        remainder = m.group(2).strip()
        if remainder:
            material_name = remainder
    elif first_text.isdigit():
        seq_no = int(first_text)
    else:
        material_name = first_text
    
    if len(non_empty) >= 4:
        if material_name is None:
            material_name = non_empty[1][1] if len(non_empty) > 1 else None
        spec = non_empty[2][1] if len(non_empty) > 2 else None
        unit_price_text = non_empty[3][1] if len(non_empty) > 3 else None
        price_text = non_empty[4][1] if len(non_empty) > 4 else None
        
        if price_text:
            price = clean_price(price_text)
            unit = clean_unit(unit_price_text)
        else:
            if unit_price_text:
                parts = unit_price_text.split()
                if len(parts) >= 2:
                    price = clean_price(parts[-1])
                    unit = clean_unit(' '.join(parts[:-1]))
                else:
                    price = clean_price(unit_price_text)
    elif len(non_empty) == 3:
        if material_name is None:
            material_name = non_empty[1][1] if len(non_empty) > 1 else None
        unit_price_text = non_empty[2][1] if len(non_empty) > 2 else None
        if unit_price_text:
            parts = unit_price_text.split()
            if len(parts) >= 2:
                price = clean_price(parts[-1])
                unit = clean_unit(' '.join(parts[:-1]))
            else:
                price = clean_price(unit_price_text)
    
    if not material_name or len(material_name) < 2:
        return None
    if price is None:
        return None
    if price < 0 or price > 10_000_000:
        return None
    
    return {
        'seq_no': seq_no,
        'category': category,
        'material_name': material_name[:200],
        'spec': (spec or '')[:200],
        'unit': unit[:20] if unit else None,
        'price': price,
    }

def parse_index_table_rows(rows):
    records = []
    for row in rows:
        texts = [c['text'].strip() for c in row]
        combined = ' '.join(texts)
        if '序号' in combined or 'SZCOST' in combined:
            continue
        
        non_empty = [t for t in texts if t]
        if len(non_empty) < 2:
            continue
        
        seq_no = None
        name = None
        price = None
        
        m = re.match(r'^(\d+)[\.\s]*(.*)', non_empty[0])
        if m:
            seq_no = int(m.group(1))
            name = m.group(2).strip() or (non_empty[1] if len(non_empty) > 1 else '')
        else:
            name = non_empty[0]
        
        for t in reversed(non_empty):
            p = clean_price(t)
            if p is not None:
                price = p
                break
        
        if name and price is not None:
            records.append({
                'seq_no': seq_no,
                'category': '定额人工费',
                'material_name': name[:200],
                'spec': '',
                'unit': '工日' if '工日' in combined else '指数',
                'price': price,
            })
    return records

def parse_rental_table_rows(rows):
    records = []
    current_category = '租赁价格'
    for row in rows:
        texts = [c['text'].strip() for c in row]
        combined = ' '.join(texts)
        if '序号' in combined or '设备名称' in combined:
            continue
        if 'SZCOST' in combined and len(combined) < 100:
            continue
        if '租赁价格' in combined and len(combined) < 50:
            continue
        
        non_empty = [t for t in texts if t]
        if len(non_empty) < 3:
            continue
        
        # 检测分类行，如"一、起重机械"
        if len(non_empty) == 1 and re.match(r'^[一二三四五六七八九十]+[、\.]', non_empty[0]):
            current_category = non_empty[0]
            continue
        
        seq_no = None
        name = None
        spec = None
        unit = '台·月'
        price = None
        
        m = re.match(r'^(\d+)[\.\s]*(.*)', non_empty[0])
        if m:
            seq_no = int(m.group(1))
        
        if len(non_empty) >= 4:
            name = non_empty[1]
            spec = non_empty[2]
            price = clean_price(non_empty[3]) if len(non_empty) > 3 else None
            if price is None and len(non_empty) > 4:
                price = clean_price(non_empty[4])
        elif len(non_empty) >= 3:
            name = non_empty[1]
            price = clean_price(non_empty[2])
        
        if name and price is not None:
            records.append({
                'seq_no': seq_no,
                'category': current_category,
                'material_name': name[:200],
                'spec': (spec or '')[:200],
                'unit': unit,
                'price': price,
            })
    return records


def parse_prefab_table_rows(rows):
    """解析装配式构件价格表：序号 | 名称 | 特征描述 | 单位 | 价格(元)"""
    records = []
    last_name = None
    
    for row in rows:
        texts = [c['text'].strip() for c in row]
        combined = ' '.join(texts)
        if '序号' in combined and '名称' in combined:
            continue
        if 'SZCOST' in combined and len(combined) < 100:
            continue
        if '装配式' in combined and len(combined) < 50:
            continue
        
        non_empty = [t for t in texts if t]
        if len(non_empty) < 3:
            continue
        
        # 提取序号
        seq_no = None
        first = non_empty[0]
        if first.isdigit():
            seq_no = int(first)
        elif re.match(r'^(\d+)[\.\s]*(.*)', first):
            m = re.match(r'^(\d+)[\.\s]*(.*)', first)
            seq_no = int(m.group(1))
        
        # 从右往左找到价格列
        price = None
        price_idx = -1
        for i in range(len(non_empty) - 1, -1, -1):
            p = clean_price(non_empty[i])
            if p is not None:
                price = p
                price_idx = i
                break
        
        if price is None:
            continue
        
        # 提取单位（价格左边1-2列）
        unit = None
        unit_idx = price_idx - 1
        if unit_idx >= 0:
            u = non_empty[unit_idx]
            # 检查是否被拆分（如 m + 3）
            if unit_idx >= 1 and u in ('2', '3'):
                prev = non_empty[unit_idx - 1]
                if prev in ('m', 'm2'):
                    unit = '㎡' if u == '2' else 'm³'
                    unit_idx -= 1
                else:
                    unit = clean_unit(u) or u
            elif unit_idx >= 1:
                combined_u = non_empty[unit_idx - 1] + u
                if combined_u in ('m3', 'm2'):
                    unit = 'm³' if combined_u == 'm3' else '㎡'
                    unit_idx -= 1
                else:
                    unit = clean_unit(u) or u
            else:
                unit = clean_unit(u) or u
        
        # 提取名称和特征描述（序号右边到单位左边）
        middle = non_empty[1:unit_idx] if unit_idx > 1 else non_empty[1:price_idx]
        
        name = None
        spec = ''
        if middle:
            first_middle = middle[0]
            # 如果第一候选包含混凝土等级/钢筋含量，它是特征描述
            if any(kw in first_middle for kw in ['C30', 'C40', 'C45', '钢筋含量', 'LC25', '抗压强度']):
                spec = first_middle
                name = last_name
            else:
                name = first_middle
                spec = ' '.join(middle[1:]) if len(middle) > 1 else ''
                last_name = name
        
        if name is None:
            name = '未知构件'
        
        records.append({
            'seq_no': seq_no,
            'category': '装配式混凝土预制构件价格',
            'material_name': name[:200],
            'spec': spec[:200],
            'unit': unit[:20] if unit else None,
            'price': price,
        })
    return records


def parse_labor_table_rows(rows):
    """解析人工费页面：包含指数表+工日价格表"""
    records = []
    in_index_table = False
    in_daily_table = False
    header_months = []
    
    for row in rows:
        texts = [c['text'].strip() for c in row]
        combined = ' '.join(texts)
        
        if '定额人工费指数' in combined:
            in_index_table = True
            in_daily_table = False
            continue
        if '定额工日价格' in combined:
            in_index_table = False
            in_daily_table = True
            continue
        if 'SZCOST' in combined and len(combined) < 100:
            continue
        if '深圳建设工程价格信息' in combined and len(combined) < 100:
            continue
        
        non_empty = [t for t in texts if t]
        if len(non_empty) < 2:
            continue
        
        # 工日价格表：序号 | 工日名称 | 单位 | 价格（元）
        if in_daily_table:
            if '工日名称' in combined or '单位' in combined:
                continue
            seq_no = None
            name = None
            unit = None
            price = None
            
            if non_empty[0].isdigit():
                seq_no = int(non_empty[0])
            
            if len(non_empty) >= 4:
                name = non_empty[1]
                unit = non_empty[2]
                price = clean_price(non_empty[3])
            elif len(non_empty) >= 3:
                name = non_empty[1]
                price = clean_price(non_empty[2])
                if '工日' in combined:
                    unit = '工日'
            
            if name and price is not None:
                records.append({
                    'seq_no': seq_no,
                    'category': '定额工日价格',
                    'material_name': name[:200],
                    'spec': '',
                    'unit': unit or '工日',
                    'price': price,
                })
        
        # 人工费指数表：序号 | 名称 | 月份1 | 月份2 | ...
        elif in_index_table:
            # 检测表头行（包含月份）
            if any(re.match(r'^\d{4}年', t) for t in non_empty):
                continue
            if any(t in ['2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月','1月'] for t in non_empty[:3]):
                continue
            
            seq_no = None
            name = None
            
            if non_empty[0].isdigit():
                seq_no = int(non_empty[0])
                name = non_empty[1] if len(non_empty) > 1 else ''
            else:
                name = non_empty[0]
            
            # 提取各月指数值
            for i, t in enumerate(non_empty[2:], 2):
                val = clean_price(t)
                if val is not None and 50 <= val <= 300:
                    # 推断月份：假设从2025-2月开始
                    month_idx = i - 2
                    year = 2025
                    month = month_idx + 2
                    if month > 12:
                        month -= 12
                        year += 1
                    records.append({
                        'seq_no': seq_no,
                        'category': '定额人工费指数',
                        'material_name': name[:200],
                        'spec': f'{year}年{month}月',
                        'unit': '指数',
                        'price': val,
                    })
    
    return records


def parse_index_table_rows_v2(rows, page_number):
    """解析造价指数表（P13-P14）：类别 | 项目 | 多个月份指数值"""
    raw_records = []
    current_category = ''
    
    for row in rows:
        texts = [c['text'].strip() for c in row]
        combined = ' '.join(texts)
        
        if 'SZCOST' in combined and len(combined) < 100:
            continue
        if '造价指数' in combined and len(combined) < 50:
            continue
        if '建安、市政工程' in combined and len(combined) < 50:
            continue
        if '类别' in combined and '项目' in combined:
            continue
        if '说明：本指数以' in combined:
            continue
        
        # 跳过年月表头行
        if any(re.match(r'^\d{4}年', t) for t in texts):
            continue
        if texts and texts[0] in ['2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月','1月']:
            continue
        
        non_empty = [t for t in texts if t]
        if len(non_empty) < 2:
            continue
        
        # 检测类别行：如"建安工程"
        if len(non_empty) == 1 and len(non_empty[0]) < 20:
            if '工程' in non_empty[0] or '市政' in non_empty[0]:
                current_category = non_empty[0]
                continue
        
        # 数据行：项目名 + 多个月份数值
        project_name = None
        values = []
        
        for t in non_empty:
            val = clean_price(t)
            if val is not None and 50 <= val <= 300:
                values.append(val)
            elif not project_name and not t.isdigit() and len(t) > 1 and '年' not in t:
                project_name = t
        
        if project_name and values:
            for val in values:
                raw_records.append({
                    'seq_no': None,
                    'category': current_category or '造价指数',
                    'material_name': project_name[:200],
                    'spec': '',  # 稍后分配
                    'unit': '指数',
                    'price': val,
                })
    
    # 后处理：按 material_name 分组，重新分配月份
    from collections import defaultdict
    by_name = defaultdict(list)
    for rec in raw_records:
        by_name[rec['material_name']].append(rec)
    
    records = []
    for name, recs in by_name.items():
        n = len(recs)
        # 过滤图表区域的噪声（值太少的行）
        if n < 5:
            continue
        
        if n >= 24:
            # 有两组（P14）：前12条 2024-02~2025-01，后12条 2025-02~2026-01
            months1 = ['2024-02','2024-03','2024-04','2024-05','2024-06',
                       '2024-07','2024-08','2024-09','2024-10','2024-11','2024-12','2025-01']
            months2 = ['2025-02','2025-03','2025-04','2025-05','2025-06',
                       '2025-07','2025-08','2025-09','2025-10','2025-11','2025-12','2026-01']
            for i, rec in enumerate(recs[:12]):
                rec['spec'] = months1[i] if i < len(months1) else f"month_{i+1}"
                records.append(rec)
            for i, rec in enumerate(recs[12:24]):
                rec['spec'] = months2[i] if i < len(months2) else f"month_{i+1}"
                records.append(rec)
            if n > 24:
                # 多余的可能也是噪声
                for rec in recs[24:]:
                    rec['spec'] = 'extra'
                    records.append(rec)
        elif n >= 12:
            # 只有一组（P13 或 P14 的上半/下半）
            months = ['2024-02','2024-03','2024-04','2024-05','2024-06',
                      '2024-07','2024-08','2024-09','2024-10','2024-11','2024-12','2025-01']
            for i, rec in enumerate(recs[:12]):
                rec['spec'] = months[i] if i < len(months) else f"month_{i+1}"
                records.append(rec)
            for rec in recs[12:]:
                rec['spec'] = 'extra'
                records.append(rec)
        else:
            for i, rec in enumerate(recs):
                rec['spec'] = f"month_{i+1}"
                records.append(rec)
    
    return records

def process_pdf():
    doc = fitz.open(PDF_PATH)
    total_pages = len(doc)
    print(f"Processing {total_pages} pages with GPU OCR...")
    
    all_results = []
    all_price_records = []
    all_text_chunks = []
    
    for i in range(total_pages):
        page = doc[i]
        pnum = i + 1
        t0 = time.time()
        
        cells, img = ocr_page(page)
        rows = cluster_rows(cells)
        full_text = '\n'.join([' '.join([c['text'] for c in r]) for r in rows])
        
        page_type = classify_page(rows, full_text, img)
        
        print(f"Page {pnum}/{total_pages}: {page_type} ({len(cells)} cells, {time.time()-t0:.2f}s)")
        
        result = {
            'page_number': pnum,
            'page_type': page_type,
            'cells': cells,
            'rows': [[{'x': c['x'], 'y': c['y'], 'text': c['text'], 'conf': c['conf']} for c in r] for r in rows],
            'full_text': full_text,
        }
        
        if page_type == 'price_table':
            recs = parse_price_table_rows(rows)
            for r in recs:
                r['page_number'] = pnum
            all_price_records.extend(recs)
            result['records'] = recs
            
        elif page_type == 'index_table':
            recs = parse_index_table_rows_v2(rows, pnum)
            for r in recs:
                r['page_number'] = pnum
            all_price_records.extend(recs)
            result['records'] = recs
            
        elif page_type == 'rental_table':
            recs = parse_rental_table_rows(rows)
            for r in recs:
                r['page_number'] = pnum
            all_price_records.extend(recs)
            result['records'] = recs
            
        elif page_type == 'prefab_table':
            recs = parse_prefab_table_rows(rows)
            for r in recs:
                r['page_number'] = pnum
            all_price_records.extend(recs)
            result['records'] = recs
            
        elif page_type == 'labor_table':
            recs = parse_labor_table_rows(rows)
            for r in recs:
                r['page_number'] = pnum
            all_price_records.extend(recs)
            result['records'] = recs
            
        elif page_type == 'chart':
            chart_path = CHARTS_DIR / f"page_{pnum:03d}_chart.png"
            img.save(chart_path)
            result['chart_image'] = str(chart_path)
            
            # 构建 chart_records（基于OCR标签）
            chart_recs = extract_chart_records_from_ocr(cells, pnum, str(chart_path))
            result['chart_records'] = chart_recs
            
            chart_desc = f"[图表] {full_text[:500]}"
            all_text_chunks.append({
                'page_number': pnum,
                'content': chart_desc,
                'chunk_type': 'chart',
            })
            
        elif page_type == 'article':
            paragraphs = [p.strip() for p in full_text.split('\n') if len(p.strip()) > 20]
            for para in paragraphs:
                all_text_chunks.append({
                    'page_number': pnum,
                    'content': para[:2000],
                    'chunk_type': 'article',
                })
                
        elif page_type in ('cover', 'toc'):
            all_text_chunks.append({
                'page_number': pnum,
                'content': full_text[:1000],
                'chunk_type': 'meta',
            })
        
        all_results.append(result)
    
    doc.close()
    
    ocr_json_path = OUTPUT_DIR / "2026-01_full_ocr.json"
    with open(ocr_json_path, 'w', encoding='utf-8') as f:
        json.dump({
            'file_name': DOC_FNAME,
            'period': DOC_PERIOD,
            'total_pages': total_pages,
            'doc_code': DOC_CODE,
            'pages': all_results,
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\nOCR complete!")
    print(f"  Total pages: {total_pages}")
    print(f"  Price records: {len(all_price_records)}")
    print(f"  Text chunks: {len(all_text_chunks)}")
    print(f"  OCR JSON saved: {ocr_json_path}")
    
    return all_price_records, all_text_chunks

def extract_chart_records_from_ocr(cells, page_number, chart_image_path):
    """从OCR结果中提取趋势图的结构化信息"""
    texts = [c['text'].strip() for c in cells]
    full_text = ' '.join(texts)
    
    # 提取主标题
    chart_title = '部分材料价格变化趋势图'
    subtitle = ''
    
    m = re.search(r'（(\d{4}-\d{4}年)）', full_text)
    if m:
        subtitle = m.group(1)
    
    # 提取单位
    unit = '元'
    m = re.search(r'（单位：([^）]+)）', full_text)
    if m:
        unit = m.group(1)
    
    # 提取Y轴刻度值（3-5位数字）
    y_labels = []
    for t in texts:
        if re.match(r'^(\d{3,5})$', t):
            val = int(t)
            if 100 <= val <= 100000:
                y_labels.append(val)
    y_labels = sorted(set(y_labels))
    
    # 提取X轴月份标签
    x_labels = []
    for t in texts:
        if re.match(r'^\d{2}-\d{2}$', t):
            x_labels.append(t)
    
    # 提取子图标题和图例
    # 子图标题通常是材料名称，后面跟着单位
    sub_charts = []
    
    # 查找所有包含材料关键词且不是标题/单位的文本
    material_keywords = ['钢筋', '水泥', '角钢', '混凝土', '砂浆', '电缆', '钢管', '钢板', '镀锌',
                         '碎石', '中砂', '柴油']
    
    # 识别子图标题：通常是短文本，在图表区域上方
    # 从 cells 中找 y 坐标相近的标题+图例组合
    legends = []
    for t in texts:
        if any(kw in t for kw in material_keywords):
            if '趋势图' not in t and '单位' not in t and len(t) < 60 and len(t) > 3:
                if t not in legends:
                    legends.append(t)
    
    # 构建 chart_records
    # 每个子图/系列一个记录
    chart_recs = []
    
    # 根据 legends 分组
    # 简单的分组策略：如果 legends 数量很多，尝试按子图标题分组
    sub_titles = []
    for t in texts:
        if len(t) < 20 and any(kw in t for kw in ['钢筋', '角钢', '钢板', '钢管', '水泥', '碎石', '中砂', '柴油']):
            if t not in sub_titles and t not in legends and '趋势图' not in t:
                sub_titles.append(t)
    
    # 为每个 legend 创建记录
    for legend in legends:
        chart_recs.append({
            'page_number': page_number,
            'chart_title': chart_title,
            'subtitle': subtitle,
            'series_name': legend,
            'unit': unit,
            'time_range': subtitle or '2023-2026年',
            'y_axis_labels': y_labels,
            'x_axis_labels': x_labels,
            'chart_image_path': chart_image_path,
            'extraction_method': 'ocr_labels',
        })
    
    if not chart_recs:
        # 至少保存一个汇总记录
        chart_recs.append({
            'page_number': page_number,
            'chart_title': chart_title,
            'subtitle': subtitle,
            'series_name': '汇总',
            'unit': unit,
            'time_range': subtitle or '2023-2026年',
            'y_axis_labels': y_labels,
            'x_axis_labels': x_labels,
            'chart_image_path': chart_image_path,
            'extraction_method': 'ocr_labels',
        })
    
    return chart_recs


def import_to_postgres(price_records, text_chunks):
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
        INSERT INTO documents (file_name, file_path, doc_type, period, total_pages, status, doc_code)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (doc_code) DO UPDATE SET
            total_pages = EXCLUDED.total_pages,
            file_path = EXCLUDED.file_path,
            status = EXCLUDED.status
        RETURNING id
    """, (DOC_FNAME, PDF_PATH, 'price_info', DOC_PERIOD, 75, 'imported', DOC_CODE))
    doc_id = cur.fetchone()[0]
    conn.commit()
    print(f"Document registered: id={doc_id}, doc_code={DOC_CODE}")
    
    if price_records:
        batch = []
        for r in price_records:
            batch.append((
                doc_id, DOC_PERIOD, r.get('category'), r['material_name'],
                r.get('spec'), r.get('unit'), r['price'], r.get('page_number'),
                json.dumps(r, ensure_ascii=False), r.get('seq_no'), 0.85, DOC_FNAME
            ))
        
        inserted = 0
        for i in range(0, len(batch), 200):
            chunk = batch[i:i+200]
            execute_values(cur, """
                INSERT INTO price_records
                    (document_id, period, category, material_name, spec, unit,
                     price, page_number, source_row, seq_no, confidence, source_doc)
                VALUES %s
                ON CONFLICT DO NOTHING
            """, chunk)
            inserted += cur.rowcount
            conn.commit()
        print(f"Inserted {inserted} price records")
    
    if text_chunks:
        batch = []
        for i, tc in enumerate(text_chunks):
            batch.append((
                doc_id, i, tc['content'], tc['page_number'],
                DOC_PERIOD, 'price_info', tc['chunk_type'], 0.85
            ))
        
        inserted = 0
        for i in range(0, len(batch), 200):
            chunk = batch[i:i+200]
            execute_values(cur, """
                INSERT INTO text_chunks
                    (document_id, chunk_index, content, page_number, period, doc_type, chunk_type, confidence)
                VALUES %s
                ON CONFLICT DO NOTHING
            """, chunk)
            inserted += cur.rowcount
            conn.commit()
        print(f"Inserted {inserted} text chunks")
    
    cur.execute("""
        INSERT INTO ocr_tasks (file_path, file_name, doc_code, total_pages, page_number, page_type, status, processed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (file_path, page_number) DO UPDATE SET
            page_type = EXCLUDED.page_type,
            status = EXCLUDED.status,
            processed_at = EXCLUDED.processed_at
    """, (PDF_PATH, DOC_FNAME, DOC_CODE, 75, 0, 'document', 'completed'))
    conn.commit()
    
    cur.close()
    conn.close()
    print("Database import complete!")

if __name__ == '__main__':
    t_start = time.time()
    price_records, text_chunks = process_pdf()
    import_to_postgres(price_records, text_chunks)
    print(f"\nTotal time: {time.time()-t_start:.1f}s")

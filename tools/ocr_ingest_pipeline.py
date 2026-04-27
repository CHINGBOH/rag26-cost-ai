#!/usr/bin/env python3
"""
OCR Ingest Pipeline - Comprehensive import of OCR JSON outputs into PostgreSQL.
Phases:
  1. Register missing documents
  2. Parse price tables from 信息价 OCR JSONs
  3. Extract chart series (price index tables + material trend data)
  4. Parse fee rate text
  5. Parse quota tables from 定额 OCR JSONs
  6. Run OCR on missing PDFs (2025-03, 2025-06, 2025-09)
"""

import json
import os
import re
import sys
import time
import hashlib
import requests
import traceback
from pathlib import Path
from collections import defaultdict

import psycopg2
from psycopg2.extras import execute_values

# ============ CONFIG ============
DB_CONFIG = dict(host='localhost', dbname='rag_db', user='rag_user', password=os.environ.get('POSTGRES_PASSWORD', 'rag_password'))

OCR_DIR       = Path('/home/l/rag-dashboard/data/ocr_outputs')
PDF_XINXI     = Path('/home/l/rag-dashboard/data/knowledge_base/深圳信息价')
PDF_STANDARD  = Path('/home/l/rag-dashboard/data/knowledge_base/深圳市建设工程地方标准')
OCR_PIPELINE  = '/home/l/rag-dashboard/data/knowledge_base/tools/ocr-pipeline/ocr_full_pdf.py'
OCR_SVC_URL   = 'http://localhost:8001'

LOG_DIR = OCR_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

# ============ HELPERS ============

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

def doc_code_from_name(filename: str) -> str:
    """Generate a stable doc_code from filename."""
    return hashlib.md5(filename.encode()).hexdigest()[:16]

def clean_num(s: str):
    """Try to parse a numeric string. Return float or None."""
    if not s:
        return None
    s = s.strip().replace(',', '').replace(' ', '').replace('，', '')
    # Strip leading noise
    s = re.sub(r'^[!！\*\+\s°]+', '', s)
    try:
        return float(s)
    except Exception:
        return None

UNIT_RE = re.compile(
    r'^(t|kg|m²|m³|m|㎡|㎥|块|套|根|只|台|件|张|个|卷|组|条|'
    r'桶|包|袋|吨|升|L|延米|延长米|[a-zA-Z]{1,4})\s*([\d.,]+)$'
)

def split_unit_price(cell_text: str):
    """
    Given a cell that may contain 'unit price' (like 'm 35.45' or 't 4150.00'),
    return (unit, price_float) or (None, None).
    """
    s = cell_text.strip()
    s = re.sub(r'^[!！\*、，\s]+', '', s)
    m = UNIT_RE.match(s)
    if m:
        return m.group(1), clean_num(m.group(2))
    v = clean_num(s)
    if v is not None:
        return None, v
    return None, None

CHINESE_NUM_PREFIX = re.compile(
    r'^[（(]?[一二三四五六七八九十百千万零○〇]+[、）)。\s]'
    r'|^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+'
    r'|^\d+\.\d+\s'  # like "1.1 something"
)

def is_category_text(text: str) -> bool:
    """Does this text look like a section header / category?"""
    t = text.strip()
    if not t:
        return False
    if CHINESE_NUM_PREFIX.match(t):
        return True
    # Pure Chinese category without leading numeral
    if len(t) > 4 and not re.search(r'\d', t) and '、' not in t[:2]:
        # Check for typical category keywords
        if any(kw in t for kw in ['金属', '水泥', '砖瓦', '灰砂', '混凝土', '木材',
                                   '板材', '玻璃', '涂料', '防腐', '化工', '管材',
                                   '电气', '仪表', '卫浴', '机械', '设备', '材料',
                                   '五金', '电缆', '线管', '型钢', '钢板', '钢管',
                                   '塑料', '橡胶', '绝热', '安全', '工具']):
            return True
    return False

def is_header_row(cells_in_row: list) -> bool:
    """Check if a row is a table header."""
    combined = ' '.join(c['text'] for c in cells_in_row)
    kw = ['序号', '材料名称', '型号', '价格（元）', '单位', '（元）', '续前']
    return sum(1 for k in kw if k in combined) >= 2

def is_title_row(cells_in_row: list) -> bool:
    """Check if this is a title row (magazine header, page title, etc.)."""
    combined = ' '.join(c['text'] for c in cells_in_row)
    kw = ['造价信息', '价格信息SZCOST', 'SZCOST深圳', '深圳建设工程价格', '建筑材料价格']
    return any(k in combined for k in kw)

FORMULA_RE = re.compile(r'[D-Z²³×÷].*[+\-×÷]|D²|H²|\d+×\d+\+')

def looks_like_formula(s: str) -> bool:
    return bool(FORMULA_RE.search(s))

# ============ STATS ============
stats = defaultdict(int)

# ============ PHASE 1: REGISTER DOCUMENTS ============

ALL_DOCS = [
    # (file_name, pdf_path, doc_type, period, doc_code_override)
    # 信息价 monthly - already in DB (doc_code from DB)
    ('2023-11.pdf',   str(PDF_XINXI/'2023-11.pdf'),   'price_info', '2023-11', '9eeb7a398703fca4'),
    ('2023-12.pdf',   str(PDF_XINXI/'2023-12.pdf'),   'price_info', '2023-12', '0c57e33b64dddecb'),
    ('2024-12.pdf',   str(PDF_XINXI/'2024-12.pdf'),   'price_info', '2024-12', '341dcca1846fb2df'),
    ('2025-01.pdf',   str(PDF_XINXI/'2025-01.pdf'),   'price_info', '2025-01', '944837378a8ec157'),
    ('2025-02.pdf',   str(PDF_XINXI/'2025-02.pdf'),   'price_info', '2025-02', '578bd266c202597e'),
    ('2025-03.pdf',   str(PDF_XINXI/'2025-03.pdf'),   'price_info', '2025-03', None),
    ('2025-04.pdf',   str(PDF_XINXI/'2025-04.pdf'),   'price_info', '2025-04', 'e2596e3ea62acb8e'),
    ('2025-05.pdf',   str(PDF_XINXI/'2025-05.pdf'),   'price_info', '2025-05', 'ff98e00f59a5326d'),
    ('2025-06.pdf',   str(PDF_XINXI/'2025-06.pdf'),   'price_info', '2025-06', None),
    ('2025-07.pdf',   str(PDF_XINXI/'2025-07.pdf'),   'price_info', '2025-07', 'b82521f622f7312c'),
    ('2025-08.pdf',   str(PDF_XINXI/'2025-08.pdf'),   'price_info', '2025-08', 'c8584697c70b6738'),
    ('2025-09.pdf',   str(PDF_XINXI/'2025-09.pdf'),   'price_info', '2025-09', None),
    ('2025-10.pdf',   str(PDF_XINXI/'2025-10.pdf'),   'price_info', '2025-10', '0cce5727deda39ff'),
    ('2025-11.pdf',   str(PDF_XINXI/'2025-11.pdf'),   'price_info', '2025-11', 'b8b02d02c78a26c6'),
    ('2025-12.pdf',   str(PDF_XINXI/'2025-12.pdf'),   'price_info', '2025-12', '03629eca712743a5'),
    ('《深圳建设工程价格信息》2026年1月.pdf',
     str(PDF_XINXI/'《深圳建设工程价格信息》2026年1月.pdf'), 'price_info', '2026-01', None),
    ('《深圳建设工程价格信息》2026年2月.pdf',
     str(PDF_XINXI/'《深圳建设工程价格信息》2026年2月.pdf'), 'price_info', '2026-02', 'a001941a3741300a'),
    # Standards
    ('深圳市建设工程计价费率标准（2023）.pdf',
     str(PDF_STANDARD/'深圳市建设工程计价费率标准（2023）.pdf'), 'fee_rate', '2023', 'fee_rate_2023'),
    ('深圳市建设工程计价费率标准（2025）.pdf',
     str(PDF_STANDARD/'深圳市建设工程计价费率标准（2025）.pdf'), 'fee_rate', '2025', 'fee_rate_2025'),
    ('第三册热力设备安装工程.pdf',
     str(PDF_STANDARD/'第三册热力设备安装工程.pdf'), 'quota', None, None),
    ('第九册通风空调工程.pdf',
     str(PDF_STANDARD/'第九册通风空调工程.pdf'), 'quota', None, None),
    ('《装饰工程消耗量标准》.pdf',
     str(PDF_STANDARD/'《装饰工程消耗量标准》.pdf'), 'quota', None, None),
    ('《市政工程造价文件分部分项和措施项目划分标准》.pdf',
     str(PDF_STANDARD/'《市政工程造价文件分部分项和措施项目划分标准》.pdf'), 'division', None, None),
    ('《房屋建筑工程造价文件分部分项和措施项目划分标准》.pdf',
     str(PDF_STANDARD/'《房屋建筑工程造价文件分部分项和措施项目划分标准》.pdf'), 'division', None, None),
    ('科技服务业标准体系建设指南（2025版）.pdf',
     str(PDF_STANDARD/'科技服务业标准体系建设指南（2025版）.pdf'), 'standard', None, None),
    ('第二册电气设备安装工程.pdf',
     str(PDF_STANDARD/'第二册电气设备安装工程.pdf'), 'quota', None, None),
]


def phase1_register_documents(conn):
    """Register all known PDFs in documents table."""
    print('\n' + '='*60)
    print('PHASE 1: Registering documents')
    print('='*60)
    cur = conn.cursor()

    doc_map = {}  # file_name → {id, doc_code}

    for fname, fpath, doc_type, period, dc_override in ALL_DOCS:
        doc_code = dc_override or doc_code_from_name(fname)

        # Check if PDF exists for page count
        total_pages = None
        pdf_path = Path(fpath)
        if pdf_path.exists():
            try:
                import fitz
                doc = fitz.open(str(pdf_path))
                total_pages = len(doc)
                doc.close()
            except Exception:
                pass

        # 'pending' for un-OCR'd, 'imported' for those with OCR
        # Special case: 第二册 is pending
        if '第二册电气设备' in fname:
            status = 'pending'
        elif period in ('2025-03', '2025-06', '2025-09'):
            status = 'pending_ocr'
        else:
            status = 'imported'

        try:
            cur.execute("""
                INSERT INTO documents (file_name, file_path, doc_type, period, total_pages, status, doc_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (doc_code) DO UPDATE SET
                    total_pages = COALESCE(EXCLUDED.total_pages, documents.total_pages),
                    file_path   = COALESCE(EXCLUDED.file_path, documents.file_path),
                    status      = CASE WHEN documents.status = 'imported' THEN documents.status
                                       ELSE EXCLUDED.status END
                RETURNING id, doc_code
            """, (fname, fpath if pdf_path.exists() else None,
                  doc_type, period, total_pages, status, doc_code))
            row = cur.fetchone()
            doc_map[fname] = {'id': row[0], 'doc_code': row[1]}
            print(f'  ✓ {fname} → doc_code={doc_code[:12]}... id={row[0]}')
            stats['docs_registered'] += 1
        except Exception as e:
            conn.rollback()
            print(f'  ✗ {fname}: {e}')
            cur = conn.cursor()
            # Try to fetch existing
            cur.execute("SELECT id, doc_code FROM documents WHERE doc_code=%s", (doc_code,))
            row = cur.fetchone()
            if row:
                doc_map[fname] = {'id': row[0], 'doc_code': row[1]}

    conn.commit()
    cur.close()
    print(f'Registered {stats["docs_registered"]} documents')
    return doc_map


# ============ PRICE TABLE PARSER ============

def group_cells_by_row(cells: list) -> dict:
    """Group cells by row index."""
    rows = defaultdict(list)
    for c in cells:
        rows[c['row']].append(c)
    for r in rows:
        rows[r].sort(key=lambda x: x['col'])
    return rows


def get_cell(row_cells, col):
    """Get text of a specific column in a row."""
    for c in row_cells:
        if c['col'] == col:
            return c['text'].strip()
    return ''


def parse_price_table(table: dict, period: str, page_number: int,
                      doc_id: int, doc_code: str, source_doc: str) -> list:
    """
    Parse a single table from OCR JSON into a list of price record dicts.
    Returns list of dicts ready for insertion.
    """
    cells = table.get('cells', [])
    if not cells:
        return []

    rows = group_cells_by_row(cells)
    if not rows:
        return []

    max_col = max(c['col'] for c in cells)
    records = []
    current_category = None

    sorted_row_ids = sorted(rows.keys())

    for row_id in sorted_row_ids:
        row_cells = rows[row_id]
        row_texts = [c['text'].strip() for c in row_cells]
        combined = ' '.join(row_texts)

        # Skip obviously empty rows
        if not combined.strip():
            continue

        # Skip title/header rows
        if is_title_row(row_cells) or is_header_row(row_cells):
            continue

        # Check for category row: typically one cell spans the whole table
        # (all other cols empty) and contains a category name
        non_empty = [t for t in row_texts if t]
        if len(non_empty) == 1 and is_category_text(non_empty[0]):
            current_category = non_empty[0].strip()
            continue

        # Also detect category from col=0 when it has category text and other cols are empty
        col0_text = get_cell(row_cells, 0)
        other_cols_empty = all(not get_cell(row_cells, c) for c in range(1, max_col + 1))
        if other_cols_empty and col0_text and is_category_text(col0_text):
            current_category = col0_text.strip()
            continue

        # Try to parse data rows
        # We need to handle multi-entry rows (e.g., col0='26 27', col1='name1 name2')
        parsed = _parse_data_row(row_cells, max_col, period, page_number,
                                  doc_id, doc_code, source_doc, current_category)
        records.extend(parsed)

    return records


def _parse_data_row(row_cells, max_col, period, page_number,
                    doc_id, doc_code, source_doc, category):
    """Parse a data row, handling variable column structures."""
    results = []

    # Build col_text dict
    col_text = {c['col']: c['text'].strip() for c in row_cells}

    # --- Try multi-item rows (seq_no col has multiple numbers) ---
    seq_raw = col_text.get(0, '')
    # Detect if there are multiple seq numbers: "26 27" or "1 2 3"
    seq_nums = re.findall(r'\d+', seq_raw)

    if len(seq_nums) > 1:
        # Multi-item row: split all columns by common patterns
        entries = _split_multi_item_row(col_text, max_col, seq_nums)
        for entry in entries:
            r = _build_record(entry, period, page_number, doc_id, doc_code,
                              source_doc, category)
            if r:
                results.append(r)
        return results

    # --- Single-item row ---
    entry = _extract_single_entry(col_text, max_col, seq_raw)
    r = _build_record(entry, period, page_number, doc_id, doc_code,
                      source_doc, category)
    if r:
        results.append(r)
    return results


def _extract_single_entry(col_text, max_col, seq_raw):
    """Extract one entry from a row with a single data item."""
    seq_no = None
    material_name = ''
    spec = ''
    unit = None
    price = None
    price_formula = None

    # seq_no from col 0
    m = re.match(r'^(\d+)\s*(.*)', seq_raw)
    if m:
        seq_no_str, remainder = m.group(1), m.group(2).strip()
        seq_no = int(seq_no_str) if seq_no_str else None
        # If there's text after seq_no in col0, it's material_name
        if remainder and not col_text.get(1, '').strip():
            material_name = remainder
    elif seq_raw and not re.search(r'\d', seq_raw):
        # col0 has non-numeric text: might be material_name
        material_name = seq_raw

    # Determine material_name and spec based on max_col
    if max_col >= 4:
        # Standard: col0=seq, col1=name, col2=spec, col3=unit or unit+price, col4=price
        if not material_name:
            material_name = col_text.get(1, '')
        spec = col_text.get(2, '')

        if max_col >= 4:
            c3 = col_text.get(3, '')
            c4 = col_text.get(4, '')
            c5 = col_text.get(5, '')

            # Try col4 or col5 as price first
            if c4 and clean_num(c4) is not None:
                price = clean_num(c4)
                unit = c3 if c3 else None
            elif c5 and clean_num(c5) is not None:
                price = clean_num(c5)
                unit = c3 if c3 else None
            elif c3:
                # col3 might have "unit price" merged
                u, p = split_unit_price(c3)
                if p is not None:
                    unit, price = u, p
                elif looks_like_formula(c3):
                    price_formula = c3
                else:
                    # c3 might be unit, price is missing
                    unit = c3 if len(c3) < 10 else None
    elif max_col == 3:
        # col0=seq, col1=name, col2=spec or name+spec, col3=price or unit+price
        if not material_name:
            material_name = col_text.get(1, '')
        spec = col_text.get(2, '')

        c3 = col_text.get(3, '')
        u, p = split_unit_price(c3)
        if p is not None:
            unit, price = u, p
        elif looks_like_formula(c3):
            price_formula = c3
    elif max_col == 2:
        # col0=seq, col1=name, col2=spec+unit+price merged or col1=name+spec, col2=price
        if not material_name:
            c1 = col_text.get(1, '')
            c2 = col_text.get(2, '')
            # c2 might be "unit price"
            u, p = split_unit_price(c2)
            if p is not None:
                unit, price = u, p
                # c1 might be "name spec" -- try to split
                material_name = c1
            else:
                # Try c2 as spec, and find price embedded in it
                material_name = c1
                spec = c2

    # Clean up
    material_name = re.sub(r'\s+', ' ', material_name).strip()
    spec = re.sub(r'\s+', ' ', spec).strip()

    # Extract unit from spec if it starts with a unit token
    if not unit and spec:
        um = re.match(r'^(t|kg|m²|m³|m|㎡|㎥|块|套|根|只|台|件|张|个|卷|组|条|桶|包|袋|吨|升)\s+', spec)
        if um:
            unit = um.group(1)
            spec = spec[um.end():].strip()

    return {
        'seq_no': seq_no,
        'material_name': material_name,
        'spec': spec,
        'unit': unit,
        'price': price,
        'price_formula': price_formula,
    }


def _split_multi_item_row(col_text, max_col, seq_nums):
    """Split a multi-item row into separate entries."""
    n = len(seq_nums)
    entries = []

    # Try to split each column's text into n parts
    def split_text(text, n):
        if not text:
            return [''] * n
        # Try newline split
        parts = [p.strip() for p in text.split('\n') if p.strip()]
        if len(parts) >= n:
            return parts[:n]
        # Try splitting by repeated number+space pattern
        # Try splitting by whitespace into n roughly equal parts
        words = text.split()
        if len(words) >= n:
            # Simple: distribute words
            chunk_size = len(words) // n
            result = []
            for i in range(n):
                start = i * chunk_size
                end = start + chunk_size if i < n - 1 else len(words)
                result.append(' '.join(words[start:end]))
            return result
        return [text] + [''] * (n - 1)

    col_parts = {}
    for col, text in col_text.items():
        col_parts[col] = split_text(text, n)

    for i in range(n):
        entry = {
            'seq_no': int(seq_nums[i]) if i < len(seq_nums) else None,
            'material_name': '',
            'spec': '',
            'unit': None,
            'price': None,
            'price_formula': None,
        }

        if max_col >= 4:
            entry['material_name'] = (col_parts.get(1, [''])[i] if i < len(col_parts.get(1, [])) else '')
            entry['spec']          = (col_parts.get(2, [''])[i] if i < len(col_parts.get(2, [])) else '')
            c3_part = (col_parts.get(3, [''])[i] if i < len(col_parts.get(3, [])) else '')
            c4_part = (col_parts.get(4, [''])[i] if i < len(col_parts.get(4, [])) else '')
            if c4_part:
                pv = clean_num(c4_part)
                if pv is not None:
                    entry['price'] = pv
                    entry['unit'] = c3_part or None
            if entry['price'] is None and c3_part:
                u, p = split_unit_price(c3_part)
                if p is not None:
                    entry['unit'], entry['price'] = u, p
        elif max_col == 2:
            entry['material_name'] = (col_parts.get(1, [''])[i] if i < len(col_parts.get(1, [])) else '')
            c2_part = (col_parts.get(2, [''])[i] if i < len(col_parts.get(2, [])) else '')
            u, p = split_unit_price(c2_part)
            if p is not None:
                entry['unit'], entry['price'] = u, p

        entries.append(entry)

    return entries


def _build_record(entry, period, page_number, doc_id, doc_code, source_doc, category):
    """Build a DB-ready dict from a parsed entry."""
    material_name = entry.get('material_name', '').strip()
    price = entry.get('price')
    price_formula = entry.get('price_formula')

    # Must have at least a name
    if not material_name or len(material_name) < 2:
        return None
    # Skip obvious junk
    if re.fullmatch(r'[\s\d\.\-,]+', material_name):
        return None
    # Must have price or formula
    if price is None and not price_formula:
        return None
    # Sanity check price range
    if price is not None and (price < 0 or price > 10_000_000):
        return None

    return {
        'document_id':   doc_id,
        'period':        period,
        'category':      category,
        'material_name': material_name[:200],
        'spec':          (entry.get('spec') or '')[:200],
        'unit':          (entry.get('unit') or '')[:20] or None,
        'price':         price,
        'price_formula': price_formula,
        'page_number':   page_number,
        'seq_no':        entry.get('seq_no'),
        'confidence':    0.85,
        'source_doc':    source_doc[:500] if source_doc else None,
        'source_row':    json.dumps(entry),
    }


def insert_price_records(conn, records: list):
    """Bulk insert price records with ON CONFLICT DO NOTHING."""
    if not records:
        return 0
    cur = conn.cursor()
    inserted = 0
    batch_size = 200
    for i in range(0, len(records), batch_size):
        batch = records[i:i+batch_size]
        vals = [
            (r['document_id'], r['period'], r['category'], r['material_name'],
             r['spec'], r['unit'], r['price'], r['page_number'],
             json.dumps(r['source_row']) if isinstance(r['source_row'], dict) else r['source_row'],
             r['price_formula'], r['seq_no'], r['confidence'], r['source_doc'])
            for r in batch
        ]
        try:
            execute_values(cur, """
                INSERT INTO price_records
                    (document_id, period, category, material_name, spec, unit,
                     price, page_number, source_row, price_formula, seq_no,
                     confidence, source_doc)
                VALUES %s
                ON CONFLICT DO NOTHING
            """, vals)
            inserted += cur.rowcount
        except Exception as e:
            conn.rollback()
            print(f'    Batch insert error: {e}')
            cur = conn.cursor()
    conn.commit()
    cur.close()
    return inserted


# ============ PHASE 2: PRICE RECORDS ============

# Maps 信息价 filenames to their OCR JSON files and doc info
XINXI_FILES = [
    # (period, ocr_json_path, doc_fname)
    ('2023-11', OCR_DIR/'深圳信息价'/'2023-11.json',      '2023-11.pdf'),
    ('2023-12', OCR_DIR/'深圳信息价'/'2023-12.json',      '2023-12.pdf'),
    ('2024-12', OCR_DIR/'深圳信息价'/'2024-12.json',      '2024-12.pdf'),
    ('2025-01', OCR_DIR/'深圳信息价'/'2025-01.json',      '2025-01.pdf'),
    ('2025-02', OCR_DIR/'深圳信息价'/'2025-02.json',      '2025-02.pdf'),
    ('2025-04', OCR_DIR/'深圳信息价'/'2025-04.json',      '2025-04.pdf'),
    ('2025-05', OCR_DIR/'深圳信息价'/'2025-05.json',      '2025-05.pdf'),
    ('2025-07', OCR_DIR/'深圳信息价'/'2025-07.json',      '2025-07.pdf'),
    ('2025-08', OCR_DIR/'深圳信息价'/'2025-08.json',      '2025-08.pdf'),
    ('2025-10', OCR_DIR/'深圳信息价'/'2025-10.json',      '2025-10.pdf'),
    ('2025-11', OCR_DIR/'深圳信息价'/'2025-11.json',      '2025-11.pdf'),
    ('2025-12', OCR_DIR/'深圳信息价'/'2025-12.json',      '2025-12.pdf'),
    ('2026-01', OCR_DIR/'深圳建设工程价格信息_2026年1月_OCR.json',
                '《深圳建设工程价格信息》2026年1月.pdf'),
    ('2026-02', OCR_DIR/'深圳信息价'/'《深圳建设工程价格信息》2026年2月.json',
                '《深圳建设工程价格信息》2026年2月.pdf'),
]


def phase2_price_records(conn, doc_map):
    """Parse price tables from 信息价 OCR JSONs."""
    print('\n' + '='*60)
    print('PHASE 2: Parsing price tables')
    print('='*60)

    # Check which periods already have sufficient records
    cur = conn.cursor()
    cur.execute("SELECT period, COUNT(*) FROM price_records GROUP BY period")
    existing = {row[0]: row[1] for row in cur.fetchall()}
    cur.close()

    total_inserted = 0

    for period, ocr_path, doc_fname in XINXI_FILES:
        print(f'\n  Processing {period} from {ocr_path.name}...')

        existing_cnt = existing.get(period, 0)
        if existing_cnt > 100:
            print(f'    Already has {existing_cnt} records, skipping')
            continue

        if not ocr_path.exists():
            print(f'    OCR file not found: {ocr_path}')
            continue

        doc_info = doc_map.get(doc_fname)
        if not doc_info:
            # Try by period
            cur = conn.cursor()
            cur.execute("SELECT id, doc_code FROM documents WHERE period=%s LIMIT 1", (period,))
            row = cur.fetchone()
            cur.close()
            if row:
                doc_info = {'id': row[0], 'doc_code': row[1]}
            else:
                print(f'    No document record for {doc_fname}')
                continue

        try:
            with open(ocr_path) as f:
                data = json.load(f)
        except Exception as e:
            print(f'    Failed to load JSON: {e}')
            continue

        pages = data.get('pages', [])
        all_records = []
        pages_with_tables = 0

        for page in pages:
            pnum = page.get('page_number', 0)
            tables = page.get('tables', [])

            for table in tables:
                cells = table.get('cells', [])
                if len(cells) < 5:
                    continue

                # Quick check: does this table have price data?
                all_text = ' '.join(c['text'] for c in cells[:10])
                if not any(kw in all_text for kw in ['材料名称', '价格', '序号', '建筑材料']):
                    continue

                pages_with_tables += 1
                recs = parse_price_table(
                    table, period, pnum,
                    doc_info['id'], doc_info['doc_code'], doc_fname
                )
                all_records.extend(recs)

        print(f'    Parsed {len(all_records)} records from {pages_with_tables} table pages')
        n = insert_price_records(conn, all_records)
        total_inserted += n
        stats['price_records_inserted'] += n
        print(f'    Inserted {n} new records')

    print(f'\nTotal price records inserted: {total_inserted}')
    return total_inserted


# ============ PHASE 3: CHART SERIES ============

def parse_index_table(table: dict):
    """
    Parse a cost index table (造价指数) into series data.
    Returns list of (series_name, year_month, value) tuples.
    """
    cells = table.get('cells', [])
    if not cells:
        return []

    rows = group_cells_by_row(cells)
    sorted_rows = sorted(rows.keys())
    if not sorted_rows:
        return []

    # Find header row: contains year-month labels
    # Look for cells with patterns like "2024年 3月" or "3月"
    month_cols = {}  # col_index → year_month string
    header_row_id = None

    MONTH_RE = re.compile(r'(\d{4})年\s*(\d{1,2})月|^(\d{1,2})月$')

    for row_id in sorted_rows[:5]:
        row_cells = rows[row_id]
        found_months = 0
        for c in row_cells:
            t = c['text'].strip()
            # Try to find year-month in this cell's text
            for line in t.split('\n'):
                mm = MONTH_RE.search(line)
                if mm:
                    if mm.group(1):  # YYYY年MM月
                        ym = f"{mm.group(1)}-{int(mm.group(2)):02d}"
                    else:            # just MM月, need to infer year
                        ym = None  # handle below
                    if ym:
                        month_cols[c['col']] = ym
                        found_months += 1
        if found_months >= 3:
            header_row_id = row_id
            break

    if not month_cols:
        return []

    results = []
    current_series = None

    for row_id in sorted_rows:
        if row_id == header_row_id:
            continue
        row_cells = rows[row_id]
        row_texts = [c['text'].strip() for c in row_cells if c['text'].strip()]
        if not row_texts:
            continue

        # First col with text might be series name
        first_text = row_cells[0]['text'].strip() if row_cells else ''
        if first_text and not re.match(r'^[\d.]+$', first_text):
            # Check if it's in a known series name list
            current_series = first_text.replace('\n', '').strip()

        if not current_series:
            continue

        # Extract values from month columns
        for c in row_cells:
            ym = month_cols.get(c['col'])
            if ym:
                v = clean_num(c['text'])
                if v is not None:
                    results.append((current_series, ym, v))

    return results


def phase3_chart_series(conn, doc_map):
    """Extract chart series from price index tables."""
    print('\n' + '='*60)
    print('PHASE 3: Extracting chart series')
    print('='*60)

    cur = conn.cursor()
    total = 0

    for period, ocr_path, doc_fname in XINXI_FILES:
        if not ocr_path.exists():
            continue

        doc_info = doc_map.get(doc_fname)
        if not doc_info:
            cur.execute("SELECT id, doc_code FROM documents WHERE period=%s LIMIT 1", (period,))
            row = cur.fetchone()
            if row:
                doc_info = {'id': row[0], 'doc_code': row[1]}
            else:
                continue

        try:
            with open(ocr_path) as f:
                data = json.load(f)
        except Exception:
            continue

        pages = data.get('pages', [])
        inserted_this_doc = 0

        for page in pages:
            pnum = page.get('page_number', 0)
            tables = page.get('tables', [])
            raw_text = page.get('raw_text', '')

            # Check if this page has index table content
            is_index_page = any(kw in raw_text for kw in
                                ['造价指数', '材料费指数', '价格指数', '多层住宅', '建安工程'])

            if not is_index_page:
                continue

            for table in tables:
                cells = table.get('cells', [])
                if len(cells) < 20:
                    continue

                # Check for year-month headers
                all_text = ' '.join(c['text'] for c in cells[:15])
                if not re.search(r'\d{4}年', all_text):
                    continue

                # Determine chart title from page text
                chart_title = None
                for title_kw in ['建安、市政工程造价指数', '建安工程造价指数',
                                  '材料费指数', '价格指数']:
                    if title_kw in raw_text:
                        chart_title = title_kw
                        break

                series_data = parse_index_table(table)

                for series_name, year_month, value in series_data:
                    if len(series_name) > 50:
                        continue
                    try:
                        cur.execute("""
                            INSERT INTO chart_series
                                (doc_code, document_id, page_number, chart_title,
                                 series_name, year_month, price_value, extraction_method, confidence)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'ocr_table', 0.9)
                            ON CONFLICT (doc_code, series_name, year_month) DO NOTHING
                        """, (doc_info['doc_code'], doc_info['id'], pnum,
                              chart_title, series_name, year_month, value))
                        inserted_this_doc += cur.rowcount
                    except Exception as e:
                        conn.rollback()

        if inserted_this_doc:
            conn.commit()
            print(f'  {period}: inserted {inserted_this_doc} chart series points')
            total += inserted_this_doc
            stats['chart_series_inserted'] += inserted_this_doc

    # Also build chart series from price_records: one point per material+period
    print('\n  Building chart series from price records...')
    try:
        cur.execute("""
            INSERT INTO chart_series
                (doc_code, document_id, page_number, chart_title, series_name,
                 year_month, price_value, extraction_method, confidence)
            SELECT
                d.doc_code,
                pr.document_id,
                pr.page_number,
                pr.category        AS chart_title,
                pr.material_name   AS series_name,
                pr.period          AS year_month,
                pr.price           AS price_value,
                'price_record'     AS extraction_method,
                0.95               AS confidence
            FROM price_records pr
            JOIN documents d ON d.id = pr.document_id
            WHERE pr.price IS NOT NULL
              AND pr.period IS NOT NULL
              AND pr.material_name IS NOT NULL
            ON CONFLICT (doc_code, series_name, year_month) DO NOTHING
        """)
        n = cur.rowcount
        conn.commit()
        print(f'  Built {n} chart series points from price records')
        stats['chart_series_from_pr'] += n
        total += n
    except Exception as e:
        conn.rollback()
        print(f'  Error building from price_records: {e}')

    cur.close()
    print(f'Total chart series inserted: {total}')
    return total


# ============ PHASE 4: FEE RATES ============

def parse_fee_rate_table(table: dict, standard_year: str):
    """Parse a fee rate table and return list of fee rate dicts."""
    cells = table.get('cells', [])
    if not cells:
        return []

    rows = group_cells_by_row(cells)
    results = []
    sorted_rows = sorted(rows.keys())

    for row_id in sorted_rows:
        row_cells = rows[row_id]
        texts = [c['text'].strip() for c in row_cells]
        combined = ' '.join(texts)

        if not combined.strip():
            continue

        # Skip header rows
        if any(kw in combined for kw in ['费用名称', '参考范围', '推荐费率', '推荐系数']):
            continue

        # Try to extract: fee_name | range | recommended
        fee_name = texts[0] if texts else ''
        if not fee_name or len(fee_name) < 2:
            continue

        rate_min = rate_max = rate_rec = None

        for text in texts[1:]:
            if not text:
                continue
            # Range: "0.96~4.16" or "1.92~5.75"
            range_m = re.search(r'([\d.]+)\s*[~～~-]\s*([\d.]+)', text)
            if range_m:
                rate_min = float(range_m.group(1))
                rate_max = float(range_m.group(2))
                continue
            # Recommended: single number
            v = clean_num(text)
            if v is not None and rate_rec is None:
                rate_rec = v

        if rate_min is None and rate_rec is None:
            continue

        results.append({
            'fee_name':          fee_name[:500],
            'standard_year':     standard_year,
            'rate_min':          rate_min,
            'rate_max':          rate_max,
            'rate_recommended':  rate_rec,
            'source_text':       combined[:1000],
        })

    return results


def phase4_fee_rates(conn, doc_map):
    """Parse fee rate data from fee rate OCR JSONs."""
    print('\n' + '='*60)
    print('PHASE 4: Parsing fee rates')
    print('='*60)

    fee_files = [
        ('2023', OCR_DIR/'深圳市建设工程计价费率标准（2023）_ocr.json',
         '深圳市建设工程计价费率标准（2023）.pdf', 'fee_rate_2023'),
        ('2025', OCR_DIR/'深圳市建设工程计价费率标准（2025）_ocr.json',
         '深圳市建设工程计价费率标准（2025）.pdf', 'fee_rate_2025'),
    ]

    cur = conn.cursor()
    total = 0

    for year, ocr_path, doc_fname, doc_code in fee_files:
        print(f'\n  Processing fee rate {year}...')

        if not ocr_path.exists():
            print(f'    OCR file not found')
            continue

        doc_info = doc_map.get(doc_fname) or {}
        if not doc_info:
            cur.execute("SELECT id FROM documents WHERE doc_code=%s", (doc_code,))
            row = cur.fetchone()
            doc_id = row[0] if row else None
        else:
            doc_id = doc_info.get('id')

        try:
            with open(ocr_path) as f:
                data = json.load(f)
        except Exception as e:
            print(f'    Load error: {e}')
            continue

        pages = data.get('pages', [])
        all_rates = []

        for page in pages:
            pnum = page.get('page_number', 0)
            tables = page.get('tables', [])

            for table in tables:
                cells = table.get('cells', [])
                if len(cells) < 4:
                    continue

                rates = parse_fee_rate_table(table, year)
                for r in rates:
                    r['doc_code'] = doc_code
                    r['document_id'] = doc_id
                    r['page_number'] = pnum
                all_rates.extend(rates)

        print(f'    Parsed {len(all_rates)} fee rate entries')

        for r in all_rates:
            try:
                cur.execute("""
                    INSERT INTO fee_rates
                        (doc_code, document_id, standard_year, fee_name,
                         rate_min, rate_max, rate_recommended, source_text, page_number)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (r['doc_code'], r['document_id'], r['standard_year'],
                      r['fee_name'], r['rate_min'], r['rate_max'],
                      r['rate_recommended'], r['source_text'], r['page_number']))
                total += cur.rowcount
            except Exception as e:
                conn.rollback()

        conn.commit()
        stats['fee_rates_inserted'] += total
        print(f'    Inserted {total} fee rates so far')

    cur.close()
    print(f'Total fee rates inserted: {total}')
    return total


# ============ PHASE 5: QUOTA ITEMS ============

QUOTA_CODE_RE = re.compile(r'\d{6,7}-\d{2,4}')

def parse_quota_tables(ocr_data: dict, doc_code: str, doc_id: int, doc_fname: str):
    """Parse quota items from a quota OCR JSON."""
    pages = ocr_data.get('pages', [])
    items = []
    current_chapter = None
    current_chapter_code = None

    for page in pages:
        pnum = page.get('page_number', 0)
        tables = page.get('tables', [])
        raw_text = page.get('raw_text', '')

        # Update chapter from text
        chapter_m = re.search(r'第[一二三四五六七八九十]+章\s*(.{2,30})', raw_text)
        if chapter_m:
            current_chapter = chapter_m.group(0).strip()

        for table in tables:
            cells = table.get('cells', [])
            if len(cells) < 6:
                continue

            all_text = ' '.join(c['text'] for c in cells)

            # Look for quota codes
            codes_in_table = QUOTA_CODE_RE.findall(all_text)
            if not codes_in_table:
                continue

            rows = group_cells_by_row(cells)
            sorted_rows = sorted(rows.keys())

            # Try to find quota_code, item_name, and cost values in the table
            for code in codes_in_table:
                # Find the cell containing this code
                code_cell = next((c for c in cells if code in c['text']), None)
                if not code_cell:
                    continue

                # Get item name from nearby cells in the same rows
                # Look in the row following the code row for item name
                code_row = code_cell['row']

                item_name_cell = None
                for c in cells:
                    if c['row'] <= code_row + 2 and '名称' in c['text'] or '子目名称' in c['text']:
                        item_name_cell = c
                        break

                # Find cost values
                base_price = None
                labor_cost = None
                material_cost = None
                machine_cost = None

                for c in cells:
                    t = c['text']
                    v = clean_num(t)
                    if v is None:
                        continue
                    # Check context
                    row_cells = rows.get(c['row'], [])
                    row_text = ' '.join(rc['text'] for rc in row_cells)
                    if '全费用' in row_text and base_price is None:
                        base_price = v
                    elif '人工' in row_text and labor_cost is None:
                        labor_cost = v
                    elif '材料' in row_text and material_cost is None:
                        material_cost = v
                    elif '机械' in row_text and machine_cost is None:
                        machine_cost = v

                # Get item name
                item_name = ''
                for c in cells:
                    if c['row'] == code_row:
                        t = c['text']
                        if t and code not in t and len(t) > 2:
                            item_name = t.strip()
                            break

                if not item_name:
                    item_name = code  # fallback

                items.append({
                    'doc_code':     doc_code,
                    'document_id':  doc_id,
                    'quota_code':   code,
                    'chapter_name': current_chapter,
                    'item_name':    item_name[:200],
                    'base_price':   base_price,
                    'labor_cost':   labor_cost,
                    'material_cost': material_cost,
                    'machine_cost': machine_cost,
                    'page_number':  pnum,
                    'source_row':   json.dumps({'page': pnum, 'code': code}),
                    'confidence':   0.7,
                })

    # Deduplicate by quota_code
    seen = set()
    unique_items = []
    for item in items:
        if item['quota_code'] not in seen:
            seen.add(item['quota_code'])
            unique_items.append(item)

    return unique_items


def phase5_quota_items(conn, doc_map):
    """Parse quota items from 定额 OCR JSONs."""
    print('\n' + '='*60)
    print('PHASE 5: Parsing quota items')
    print('='*60)

    quota_files = [
        ('第三册热力设备安装工程.pdf',   OCR_DIR/'第三册热力设备安装工程_ocr.json'),
        ('第九册通风空调工程.pdf',       OCR_DIR/'第九册通风空调工程_ocr.json'),
        ('《装饰工程消耗量标准》.pdf',   OCR_DIR/'《装饰工程消耗量标准》_ocr.json'),
    ]

    cur = conn.cursor()
    total = 0

    for doc_fname, ocr_path in quota_files:
        print(f'\n  Processing {doc_fname}...')

        if not ocr_path.exists():
            print(f'    OCR file not found')
            continue

        doc_info = doc_map.get(doc_fname)
        if not doc_info:
            dc = doc_code_from_name(doc_fname)
            cur.execute("SELECT id, doc_code FROM documents WHERE doc_code=%s OR file_name=%s LIMIT 1",
                        (dc, doc_fname))
            row = cur.fetchone()
            if row:
                doc_info = {'id': row[0], 'doc_code': row[1]}
            else:
                print(f'    No document record found')
                continue

        try:
            with open(ocr_path) as f:
                data = json.load(f)
        except Exception as e:
            print(f'    Load error: {e}')
            continue

        items = parse_quota_tables(data, doc_info['doc_code'], doc_info['id'], doc_fname)
        print(f'    Parsed {len(items)} quota items')

        for item in items:
            try:
                cur.execute("""
                    INSERT INTO quota_items
                        (doc_code, document_id, quota_code, chapter_name, item_name,
                         base_price, labor_cost, material_cost, machine_cost,
                         page_number, source_row, confidence)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (doc_code, quota_code) DO NOTHING
                """, (item['doc_code'], item['document_id'], item['quota_code'],
                      item['chapter_name'], item['item_name'],
                      item['base_price'], item['labor_cost'],
                      item['material_cost'], item['machine_cost'],
                      item['page_number'],
                      item['source_row'], item['confidence']))
                total += cur.rowcount
            except Exception as e:
                conn.rollback()
                cur = conn.cursor()

        conn.commit()
        print(f'    Inserted {total} quota items so far')
        stats['quota_items_inserted'] += total

    cur.close()
    print(f'Total quota items inserted: {total}')
    return total


# ============ PHASE 6: RUN MISSING OCR ============

def run_ocr_async(pdf_path: str, timeout: int = 600) -> str | None:
    """Submit a PDF to the async OCR service and wait for result. Returns output JSON path."""
    fname = Path(pdf_path).name
    period = re.search(r'(\d{4}-\d{2})', fname)
    period = period.group(1) if period else fname.replace('.pdf', '')

    output_path = OCR_DIR / f'{period}_ocr.json'
    if output_path.exists():
        print(f'    Already have OCR output: {output_path.name}')
        return str(output_path)

    print(f'    Submitting {fname} to OCR service...')
    try:
        with open(pdf_path, 'rb') as f:
            resp = requests.post(f'{OCR_SVC_URL}/ocr/pdf/async',
                                 files={'file': (fname, f, 'application/pdf')},
                                 timeout=30)
        if resp.status_code != 200:
            print(f'    OCR submit failed: {resp.status_code} {resp.text[:200]}')
            return None

        job_id = resp.json().get('job_id')
        if not job_id:
            print(f'    No job_id in response: {resp.text[:200]}')
            return None

        print(f'    Job {job_id} submitted, waiting...')

        # Poll for completion
        start = time.time()
        while time.time() - start < timeout:
            try:
                status_resp = requests.get(f'{OCR_SVC_URL}/ocr/pdf/async/{job_id}', timeout=15)
                if status_resp.status_code == 200:
                    data = status_resp.json()
                    status = data.get('status', 'unknown')
                    if status == 'completed':
                        # Save result
                        result = data.get('result', data)
                        with open(output_path, 'w') as f:
                            json.dump(result, f, ensure_ascii=False, indent=2)
                        print(f'    ✓ OCR completed → {output_path.name}')
                        return str(output_path)
                    elif status == 'failed':
                        print(f'    OCR failed: {data.get("error", "unknown")}')
                        return None
                    else:
                        elapsed = int(time.time() - start)
                        print(f'    Status: {status} ({elapsed}s elapsed)', end='\r')
            except Exception as e:
                print(f'    Poll error: {e}')
            time.sleep(15)

        print(f'    Timeout after {timeout}s')
        return None

    except Exception as e:
        print(f'    OCR service error: {e}')
        return None


def phase6_missing_ocr(conn, doc_map):
    """Run OCR on missing PDF files (2025-03, 2025-06, 2025-09)."""
    print('\n' + '='*60)
    print('PHASE 6: Running OCR on missing PDFs')
    print('='*60)

    missing = [
        ('2025-03', PDF_XINXI/'2025-03.pdf'),
        ('2025-06', PDF_XINXI/'2025-06.pdf'),
        ('2025-09', PDF_XINXI/'2025-09.pdf'),
    ]

    cur = conn.cursor()

    for period, pdf_path in missing:
        print(f'\n  Processing {period}...')

        if not pdf_path.exists():
            print(f'    PDF not found: {pdf_path}')
            continue

        # Check if we already have OCR output
        output_path = OCR_DIR / f'{period}_ocr.json'
        if not output_path.exists():
            output_path = run_ocr_async(str(pdf_path))
            if not output_path:
                print(f'    OCR failed or timed out for {period}')
                # Update status
                cur.execute("""
                    UPDATE documents SET status='ocr_failed'
                    WHERE period=%s AND doc_type='price_info'
                """, (period,))
                conn.commit()
                continue
            output_path = Path(output_path)
        else:
            print(f'    Using existing OCR: {output_path.name}')

        # Load and process the OCR output
        try:
            with open(output_path) as f:
                data = json.load(f)
        except Exception as e:
            print(f'    Load error: {e}')
            continue

        # Update doc status
        cur.execute("""
            UPDATE documents SET status='imported'
            WHERE period=%s AND doc_type='price_info'
        """, (period,))
        conn.commit()

        # Get doc info
        cur.execute("SELECT id, doc_code FROM documents WHERE period=%s AND doc_type='price_info' LIMIT 1",
                    (period,))
        row = cur.fetchone()
        if not row:
            continue
        doc_id, doc_code = row[0], row[1]

        # Parse price tables
        pages = data.get('pages', [])
        all_records = []

        for page in pages:
            pnum = page.get('page_number', 0)
            for table in page.get('tables', []):
                cells = table.get('cells', [])
                if len(cells) < 5:
                    continue
                all_text = ' '.join(c['text'] for c in cells[:10])
                if not any(kw in all_text for kw in ['材料名称', '价格', '序号']):
                    continue
                recs = parse_price_table(table, period, pnum, doc_id, doc_code,
                                         f'{period}.pdf')
                all_records.extend(recs)

        n = insert_price_records(conn, all_records)
        stats['price_records_inserted'] += n
        print(f'    Inserted {n} price records for {period}')

    cur.close()


# ============ TEXT CHUNKS ============

def phase_text_chunks(conn, doc_map):
    """Insert text chunks for documents that don't have them yet."""
    print('\n' + '='*60)
    print('PHASE TEXT CHUNKS: Inserting missing text chunks')
    print('='*60)

    cur = conn.cursor()
    cur.execute("SELECT document_id FROM text_chunks GROUP BY document_id")
    docs_with_chunks = {row[0] for row in cur.fetchall()}

    total = 0

    all_ocr_files = list(OCR_DIR.glob('*_ocr.json')) + [
        OCR_DIR / '2025-01.json', OCR_DIR / '2025-02.json',
        OCR_DIR / '2025-04.json', OCR_DIR / '2025-05.json',
        OCR_DIR / '2025-07.json', OCR_DIR / '2025-08.json',
        OCR_DIR / '2025-10.json', OCR_DIR / '2025-11.json',
    ]

    for ocr_path in all_ocr_files:
        if not ocr_path.exists():
            continue

        try:
            with open(ocr_path) as f:
                data = json.load(f)
        except Exception:
            continue

        # Match to document
        file_name_in_json = data.get('file_name', '')
        doc_id = None

        # Try to find doc by file_name
        cur.execute("SELECT id FROM documents WHERE file_name=%s LIMIT 1", (file_name_in_json,))
        row = cur.fetchone()
        if row:
            doc_id = row[0]
        else:
            # Try by doc_code
            doc_code_in_json = data.get('document_id', '').replace('doc_pdf_', '')[:16]
            cur.execute("SELECT id FROM documents WHERE doc_code=%s LIMIT 1", (doc_code_in_json,))
            row = cur.fetchone()
            if row:
                doc_id = row[0]

        if not doc_id:
            continue

        if doc_id in docs_with_chunks:
            continue

        pages = data.get('pages', [])
        chunk_idx = 0

        for page in pages:
            pnum = page.get('page_number', 0)
            raw_text = page.get('raw_text', '') or ''

            if len(raw_text.strip()) > 50:
                # Chunk by ~500 char segments
                chunks = [raw_text[i:i+500] for i in range(0, len(raw_text), 500)]
                for chunk in chunks:
                    if len(chunk.strip()) < 20:
                        continue
                    try:
                        cur.execute("""
                            INSERT INTO text_chunks
                                (document_id, page_number, chunk_index, content, chunk_type, confidence)
                            VALUES (%s, %s, %s, %s, 'page_text', 0.9)
                        """, (doc_id, pnum, chunk_idx, chunk.strip()))
                        chunk_idx += 1
                        total += 1
                    except Exception:
                        conn.rollback()
                        cur = conn.cursor()

        if chunk_idx > 0:
            conn.commit()
            print(f'  Added {chunk_idx} chunks for doc_id={doc_id}')

    cur.close()
    stats['text_chunks_inserted'] = total
    print(f'Total text chunks inserted: {total}')


# ============ FINAL REPORT ============

def print_report(conn):
    """Print summary of DB state after pipeline."""
    print('\n' + '='*60)
    print('FINAL REPORT')
    print('='*60)

    cur = conn.cursor()

    tables = [
        ('documents',        'SELECT COUNT(*), status FROM documents GROUP BY status ORDER BY status'),
        ('price_records',    'SELECT COUNT(*), period FROM price_records GROUP BY period ORDER BY period'),
        ('chart_series',     'SELECT COUNT(*), extraction_method FROM chart_series GROUP BY extraction_method'),
        ('fee_rates',        'SELECT COUNT(*), standard_year FROM fee_rates GROUP BY standard_year'),
        ('quota_items',      'SELECT COUNT(*), doc_code FROM quota_items GROUP BY doc_code'),
        ('text_chunks',      'SELECT COUNT(*) FROM text_chunks'),
    ]

    for label, sql in tables:
        try:
            cur.execute(sql)
            rows = cur.fetchall()
            if rows and len(rows[0]) == 1:
                print(f'\n{label}: {rows[0][0]} total')
            else:
                print(f'\n{label}:')
                for row in rows:
                    print(f'  {row}')
        except Exception as e:
            print(f'{label}: error - {e}')
            conn.rollback()
            cur = conn.cursor()

    # Sample chart series
    try:
        cur.execute("""
            SELECT series_name, year_month, price_value, extraction_method
            FROM chart_series
            ORDER BY year_month DESC, series_name
            LIMIT 10
        """)
        rows = cur.fetchall()
        if rows:
            print('\nSample chart_series:')
            for r in rows:
                print(f'  {r[0][:30]:30s} {r[1]} {str(r[2]):>10} [{r[3]}]')
    except Exception:
        pass

    cur.close()

    print('\n--- Pipeline stats ---')
    for k, v in sorted(stats.items()):
        print(f'  {k}: {v}')


# ============ MAIN ============

def main():
    print('Starting OCR Ingest Pipeline')
    print(f'DB: {DB_CONFIG["host"]}/{DB_CONFIG["dbname"]}')
    print(f'OCR dir: {OCR_DIR}')

    conn = get_conn()
    conn.autocommit = False

    try:
        # Phase 1: Register documents
        doc_map = phase1_register_documents(conn)

        # Phase 2: Price records
        phase2_price_records(conn, doc_map)

        # Phase 3: Chart series
        phase3_chart_series(conn, doc_map)

        # Phase 4: Fee rates
        phase4_fee_rates(conn, doc_map)

        # Phase 5: Quota items
        phase5_quota_items(conn, doc_map)

        # Phase 6: Missing OCR
        phase6_missing_ocr(conn, doc_map)

        # Text chunks
        phase_text_chunks(conn, doc_map)

        # Final report
        print_report(conn)

    except KeyboardInterrupt:
        print('\nInterrupted')
        conn.rollback()
    except Exception as e:
        print(f'\nFatal error: {e}')
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()


if __name__ == '__main__':
    main()

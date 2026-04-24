#!/usr/bin/env python3
"""
run_ingest.py — 一键将 OCR JSON 输出导入 PostgreSQL（匹配实际 DB schema）

实际 schema（2026-04-24 验证）：
  document_registry: id, doc_id(varchar unique), file_name, file_path, doc_type,
                     total_pages, status, price_record_count, text_chunk_count, imported_at
  price_records:     id, doc_id(varchar), file_name, material_name, specification, unit,
                     price_tax_included, price_tax_excluded, region, year_month,
                     page_number, category, metadata, embedding, created_at
  text_chunks:       id, doc_id(varchar), file_name, content, page_number, ..., created_at

用法：
  python tools/run_ingest.py                    # 导入所有 OCR JSON
  python tools/run_ingest.py --dry-run          # 只解析，不写入 DB
  python tools/run_ingest.py --file 2025-12     # 只处理 2025-12 期间
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from collections import defaultdict

import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
DB = dict(host='localhost', dbname='rag_db', user='rag_user', password=os.environ.get('POSTGRES_PASSWORD', 'rag_password'))
OCR_DIR = Path('/home/l/rag-dashboard/data/ocr_outputs')
KB_DIR  = Path('/home/l/rag-dashboard/data/knowledge_base')

# 期间正则：从文件名提取 YYYY-MM
_PERIOD_RE = re.compile(r'(\d{4})[-年](\d{1,2})')

# ── Helpers ──────────────────────────────────────────────────────────────────

def conn():
    return psycopg2.connect(**DB)

def doc_id_from_name(name: str) -> str:
    return 'doc_' + hashlib.md5(name.encode()).hexdigest()[:24]

def extract_period(name: str) -> str | None:
    m = _PERIOD_RE.search(name)
    return f"{m.group(1)}-{int(m.group(2)):02d}" if m else None

def clean_price(s) -> float | None:
    if s is None:
        return None
    try:
        return float(str(s).strip().replace(',', '').replace('，', ''))
    except Exception:
        return None

# ── Register document ────────────────────────────────────────────────────────

def register_doc(cur, ocr_data: dict, ocr_path: Path) -> str:
    """Upsert document_registry, return doc_id (VARCHAR)."""
    fname = ocr_data.get('file_name') or ocr_path.name
    did   = ocr_data.get('document_id') or doc_id_from_name(fname)
    pages = len(ocr_data.get('pages', []))
    doc_type = 'price_info' if extract_period(fname) else 'quota'

    cur.execute("""
        INSERT INTO document_registry (doc_id, file_name, doc_type, total_pages, status)
        VALUES (%s, %s, %s, %s, 'imported')
        ON CONFLICT (doc_id) DO UPDATE SET
            total_pages = EXCLUDED.total_pages,
            status      = 'imported'
        RETURNING doc_id
    """, (did, fname, doc_type, pages))
    return cur.fetchone()[0]

# ── Parse price table cells ──────────────────────────────────────────────────

_UNIT_RE = re.compile(
    r'^(t|kg|m²|m³|m|㎡|㎥|块|套|根|只|台|件|张|个|卷|组|条|'
    r'桶|包|袋|吨|升|L|延米|延长米|[a-zA-Z]{1,4})'
)
_HEADER_KW = {'序号', '材料名称', '型号', '价格', '单位', '续前'}

def _is_header(cells):
    txt = ' '.join(c.get('text', '') for c in cells)
    return sum(1 for k in _HEADER_KW if k in txt) >= 2

def _is_category(txt: str) -> bool:
    if not txt or len(txt) < 2:
        return False
    kw = ['金属', '水泥', '砖瓦', '混凝土', '木材', '板材', '玻璃', '涂料',
          '化工', '管材', '电气', '卫浴', '机械', '设备', '材料', '五金',
          '电缆', '型钢', '钢板', '钢管', '塑料', '橡胶', '安全', '工具']
    return (not re.search(r'\d', txt)) and any(k in txt for k in kw)

def parse_price_table(table: dict, period: str, page_num: int,
                      doc_id: str, file_name: str, category_hint: str = '') -> list:
    """Parse one OCR table → list of price_record dicts."""
    cells = table.get('cells', [])
    if not cells:
        return []

    rows: dict = defaultdict(list)
    for c in cells:
        rows[c['row']].append(c)
    for r in rows.values():
        r.sort(key=lambda x: x['col'])

    max_col = max(c['col'] for c in cells)
    records = []
    current_cat = category_hint

    def cell_text(row_cells, col):
        for c in row_cells:
            if c['col'] == col:
                return c['text'].strip()
        return ''

    for row_id in sorted(rows):
        rc = rows[row_id]
        texts = [c['text'].strip() for c in rc]
        combined = ' '.join(texts)
        if not combined.strip():
            continue
        if _is_header(rc):
            continue

        non_empty = [t for t in texts if t]
        if len(non_empty) == 1 and _is_category(non_empty[0]):
            current_cat = non_empty[0]
            continue

        # Extract fields by column heuristic
        name = cell_text(rc, 1) or cell_text(rc, 0)
        if not name or len(name) < 2:
            continue

        spec = cell_text(rc, 2) or cell_text(rc, 3)
        unit_raw = cell_text(rc, max_col - 1) if max_col >= 3 else ''
        price_raw = cell_text(rc, max_col)

        price = clean_price(price_raw)
        if price is None:
            # Try second-to-last col
            price = clean_price(cell_text(rc, max_col - 1)) if max_col >= 2 else None
        if price is None:
            continue
        if not (0 < price < 10_000_000):
            continue

        # Detect unit from the unit col or price col prefix
        unit = None
        um = _UNIT_RE.match(unit_raw)
        if um:
            unit = um.group(1)

        records.append({
            'doc_id':             doc_id,
            'file_name':          file_name,
            'material_name':      name[:500],
            'specification':      spec[:500] if spec else None,
            'unit':               unit,
            'price_tax_included': price,
            'year_month':         period,
            'page_number':        page_num,
            'category':           current_cat[:200] if current_cat else None,
            'metadata':           json.dumps({'raw': combined[:200]}),
        })
    return records

# ── Ingest one OCR JSON ──────────────────────────────────────────────────────

def ingest_ocr_json(cur, ocr_path: Path, dry_run=False) -> dict:
    stats = {'price_records': 0, 'text_chunks': 0}

    try:
        with open(ocr_path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        log.error(f"Failed to load {ocr_path.name}: {e}")
        return stats

    fname = data.get('file_name') or ocr_path.name
    period = extract_period(fname) or extract_period(ocr_path.name) or ''
    is_price_doc = bool(period)  # 信息价有期间

    if dry_run:
        log.info(f"[DRY] {ocr_path.name}: fname={fname} period={period} pages={len(data.get('pages', []))}")
        return stats

    doc_id = register_doc(cur, data, ocr_path)
    log.info(f"  doc_id={doc_id} fname={fname} period={period}")

    price_batch = []
    chunk_idx = 0
    chunk_batch = []

    for page in data.get('pages', []):
        pnum = page.get('page_number', 0)

        # Price tables (only for 信息价 docs with period)
        if is_price_doc:
            for table in page.get('tables', []):
                if len(table.get('cells', [])) < 5:
                    continue
                recs = parse_price_table(table, period, pnum, doc_id, fname)
                price_batch.extend(recs)

        # Text chunks from raw_text
        raw = (page.get('raw_text') or '').strip()
        if len(raw) > 50:
            for start in range(0, len(raw), 500):
                chunk = raw[start:start + 500].strip()
                if len(chunk) < 20:
                    continue
                chunk_batch.append({
                    'doc_id':      doc_id,
                    'file_name':   fname,
                    'content':     chunk,
                    'page_number': pnum,
                    'chunk_index': chunk_idx,
                })
                chunk_idx += 1

    # Bulk insert price_records
    if price_batch:
        vals = [
            (r['doc_id'], r['file_name'], r['material_name'], r['specification'],
             r['unit'], r['price_tax_included'], None, r['year_month'],
             r['page_number'], r['category'], r['metadata'])
            for r in price_batch
        ]
        execute_values(cur, """
            INSERT INTO price_records
                (doc_id, file_name, material_name, specification, unit,
                 price_tax_included, price_tax_excluded, year_month,
                 page_number, category, metadata)
            VALUES %s
            ON CONFLICT DO NOTHING
        """, vals)
        stats['price_records'] = len(price_batch)

    # Bulk insert text_chunks
    if chunk_batch:
        # Try with chunk_index first; fall back to without if column missing
        try:
            execute_values(cur, """
                INSERT INTO text_chunks (doc_id, file_name, content, page_number, chunk_index)
                VALUES %s
                ON CONFLICT DO NOTHING
            """, [(r['doc_id'], r['file_name'], r['content'], r['page_number'], r['chunk_index'])
                  for r in chunk_batch])
        except Exception:
            cur.connection.rollback()
            execute_values(cur, """
                INSERT INTO text_chunks (doc_id, file_name, content, page_number)
                VALUES %s
                ON CONFLICT DO NOTHING
            """, [(r['doc_id'], r['file_name'], r['content'], r['page_number'])
                  for r in chunk_batch])
        stats['text_chunks'] = len(chunk_batch)

    log.info(f"    → {stats['price_records']} price_records, {stats['text_chunks']} text_chunks")
    return stats

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Import OCR JSONs into PostgreSQL')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--file', help='Filter by period or filename substring')
    args = parser.parse_args()

    ocr_files = sorted(OCR_DIR.glob('*_ocr.json'))
    if not ocr_files:
        log.error(f"No *_ocr.json files found in {OCR_DIR}")
        sys.exit(1)

    if args.file:
        ocr_files = [f for f in ocr_files if args.file in f.name]
        if not ocr_files:
            log.error(f"No files match filter '{args.file}'")
            sys.exit(1)

    log.info(f"Found {len(ocr_files)} OCR JSON files to process")

    c = conn()
    cur = c.cursor()
    total_price = 0
    total_chunks = 0
    errors = []

    for ocr_path in ocr_files:
        log.info(f"Processing: {ocr_path.name}")
        try:
            stats = ingest_ocr_json(cur, ocr_path, dry_run=args.dry_run)
            total_price  += stats['price_records']
            total_chunks += stats['text_chunks']
            if not args.dry_run:
                c.commit()
        except Exception as e:
            c.rollback()
            log.error(f"  ERROR {ocr_path.name}: {e}")
            errors.append(ocr_path.name)

    cur.close()
    c.close()

    print('\n' + '='*60)
    print(f'DONE: {len(ocr_files) - len(errors)} files OK, {len(errors)} errors')
    print(f'  price_records inserted: {total_price}')
    print(f'  text_chunks  inserted: {total_chunks}')
    if errors:
        print(f'  Errors: {errors}')
    print('='*60)

    # Show final DB counts
    if not args.dry_run:
        c2 = conn()
        cur2 = c2.cursor()
        for tbl in ['document_registry', 'price_records', 'text_chunks']:
            cur2.execute(f'SELECT COUNT(*) FROM {tbl}')
            print(f'  {tbl}: {cur2.fetchone()[0]} rows')
        cur2.close()
        c2.close()

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Standalone patch: re-parse 2025-12 and 2023-12 OCR JSONs with fixed column logic,
then upsert missing price_records.

Bug: When OCR produces a 6-col padded table but only col0/1/2 have data,
the standard parser looks for price in col3/4/5 → finds nothing → drops the row.
Fix: Detect "all-empty right-cols" and fall back to 3-col layout.
"""
import os
import json, re, sys
from pathlib import Path

import psycopg2

# ── DB config ─────────────────────────────────────────────────────────────────
DB = dict(host='localhost', port=5432, database='rag_db',
          user='rag_user', password=os.environ.get('POSTGRES_PASSWORD', 'rag_password'))

# ── Files to re-process ───────────────────────────────────────────────────────
BASE = Path('/home/l/rag-dashboard/data/ocr_outputs')
TARGETS = [
    ('2025-12', BASE / '2025-12_ocr.json', 15),   # doc_id
    ('2023-12', BASE / '2023-12_ocr.json',  2),
]

# ── Number helpers ────────────────────────────────────────────────────────────
_NUM_RE = re.compile(r'(\d[\d,]*\.?\d*)')

def clean_num(s: str):
    """Extract the first number from a string, return float or None."""
    if not s:
        return None
    s = s.replace(',', '').strip()
    m = _NUM_RE.search(s)
    if not m:
        return None
    try:
        v = float(m.group(1))
        return v if 0.01 < v < 1_000_000 else None
    except ValueError:
        return None

# ── Unit extraction ───────────────────────────────────────────────────────────
_UNITS = r'(t|kg|m²|m³|m|㎡|㎥|块|套|根|只|台|件|张|个|卷|组|条|桶|包|袋|吨|升|延米|延长米|自然间)'
_UNIT_PRICE_RE = re.compile(r'^' + _UNITS + r'\s*([0-9,]+\.?[0-9]*)$')
_FORMULA_RE = re.compile(r'[×x\*\/].*[0-9]')

def split_unit_price(s: str):
    s = s.strip()
    m = _UNIT_PRICE_RE.match(s)
    if m:
        return m.group(1), float(m.group(2).replace(',', ''))
    return None, None

def looks_like_formula(s: str):
    return bool(_FORMULA_RE.search(s))

# ── Row parser (with 3-col-in-6-col fallback) ────────────────────────────────
def parse_row(cells, max_col, page_number, period, doc_id):
    """Parse one table row → list of record dicts (may be empty)."""
    if not cells:
        return []
    col = {c['col']: c['text'].strip() for c in cells}

    c0 = col.get(0, '')
    c1 = col.get(1, '')
    c2 = col.get(2, '')
    c3 = col.get(3, '')
    c4 = col.get(4, '')
    c5 = col.get(5, '')

    # Skip header / empty rows
    if not c0 and not c1:
        return []
    if re.match(r'序号|材料名称|规格|单价|备注', c0):
        return []

    # seq_no + possible material_name suffix in col0
    seq_no = None
    col0_remainder = ''
    m = re.match(r'^(\d+)\s*(.*)', c0)
    if m:
        raw_seq = int(m.group(1))
        seq_no = raw_seq if raw_seq < 2_147_483_647 else None
        col0_remainder = m.group(2).strip()

    # ── Detect 3-col-in-6-col: col3/4/5 all empty ──────────────────────────
    right_cols_empty = not c3 and not c4 and not c5

    if max_col >= 4 and right_cols_empty:
        # Price is in col2, spec in col1
        price = clean_num(c2)
        if price is None:
            return []
        material_name = col0_remainder or c1
        spec = c1 if col0_remainder else ''
        # If col0_remainder looks like a category word rather than name,
        # keep both: name = col0_remainder, spec = c1
        if col0_remainder and c1:
            material_name = col0_remainder
            spec = c1
        unit = None
        # Detect unit prefix in c2 e.g. "元/m 605.73"
        unit_m = re.match(r'^(元/\w+|' + _UNITS[1:-1] + r')\s+', c2)
        if unit_m:
            unit = unit_m.group(1)

    elif max_col >= 4:
        material_name = col0_remainder or c1
        spec = c2 if col0_remainder else c2
        if not material_name:
            material_name = c1

        # price from c4, c5 first, then c3
        price = None
        unit = None
        if c4 and clean_num(c4) is not None:
            price = clean_num(c4)
            unit = c3 or None
        elif c5 and clean_num(c5) is not None:
            price = clean_num(c5)
            unit = c3 or None
        elif c3:
            unit, price = split_unit_price(c3)
            if price is None and clean_num(c3) is not None:
                price = clean_num(c3)

    elif max_col == 3:
        material_name = col0_remainder or c1
        spec = c2 if col0_remainder else c2
        if not material_name:
            material_name = c1
        unit, price = split_unit_price(c3)
        if price is None:
            price = clean_num(c3)

    else:  # max_col <= 2
        material_name = c1
        spec = ''
        unit, price = split_unit_price(c2)
        if price is None:
            price = clean_num(c2)

    if price is None:
        return []

    material_name = re.sub(r'\s+', ' ', (material_name or '')).strip()
    spec = re.sub(r'\s+', ' ', (spec or '')).strip()

    if not material_name:
        return []

    return [{
        'period': period,
        'document_id': doc_id,
        'page_number': page_number,
        'seq_no': seq_no,
        'material_name': material_name[:200],
        'spec': spec[:200],
        'unit': (unit or '')[:20] or None,
        'price': price,
    }]


def parse_ocr(ocr_path: Path, period: str, doc_id: int):
    with open(ocr_path) as f:
        data = json.load(f)

    records = []
    for page in data.get('pages', []):
        pnum = page.get('page_number', 0)
        for table in page.get('tables', []):
            cells = table.get('cells', [])
            if not cells:
                continue
            max_col = max(c['col'] for c in cells)
            # group by row
            rows = {}
            for c in cells:
                rows.setdefault(c['row'], []).append(c)

            for row_idx in sorted(rows):
                records.extend(parse_row(rows[row_idx], max_col, pnum, period, doc_id))

    return records


def upsert(conn, records):
    cur = conn.cursor()
    inserted = 0
    skipped = 0
    for r in records:
        cur.execute("""
            INSERT INTO price_records
                (period, document_id, page_number, seq_no, material_name, spec, unit, price)
            VALUES (%(period)s, %(document_id)s, %(page_number)s, %(seq_no)s,
                    %(material_name)s, %(spec)s, %(unit)s, %(price)s)
            ON CONFLICT DO NOTHING
        """, r)
        if cur.rowcount:
            inserted += 1
        else:
            skipped += 1
    conn.commit()
    cur.close()
    return inserted, skipped


def verify(conn, period, keyword='YJV'):
    cur = conn.cursor()
    cur.execute("""
        SELECT material_name, spec, unit, price, page_number
        FROM price_records
        WHERE period=%s AND (material_name ILIKE %s OR spec ILIKE %s)
        ORDER BY page_number, price
        LIMIT 10
    """, (period, f'%{keyword}%', f'%{keyword}%'))
    rows = cur.fetchall()
    cur.close()
    return rows


def main():
    conn = psycopg2.connect(**DB)
    print('Connected to DB\n')

    for period, path, doc_id in TARGETS:
        print(f'=== {period} (doc_id={doc_id}) ===')
        if not path.exists():
            print(f'  OCR file missing: {path}')
            continue

        records = parse_ocr(path, period, doc_id)
        print(f'  Parsed {len(records)} records from OCR')

        inserted, skipped = upsert(conn, records)
        print(f'  Inserted: {inserted}  Skipped (dup): {skipped}')

        # Verify YJV 5×120
        hits = verify(conn, period, 'YJV')
        if hits:
            print(f'  YJV rows in DB:')
            for row in hits:
                print(f'    {row[0]} | {row[1]} | {row[2]} | {row[3]} | p{row[4]}')
        else:
            print(f'  WARNING: no YJV rows found for {period}')

        # Also check 5×120 directly
        hits2 = verify(conn, period, '5×120')
        hits2 += verify(conn, period, '5*120')
        hits2 += verify(conn, period, '5x120')
        seen = set()
        for row in hits2:
            key = (row[0], row[1])
            if key not in seen:
                seen.add(key)
                print(f'  5×120 hit: {row[0]} | {row[1]} | price={row[3]}')
        print()

    conn.close()
    print('Done.')


if __name__ == '__main__':
    main()

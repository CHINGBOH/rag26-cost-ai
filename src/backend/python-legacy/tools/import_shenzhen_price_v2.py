#!/usr/bin/env python3
"""
Phase 2: 深圳信息价月刊 — 精准价格表解析入库 v2
修复：价格定位更精确（行尾/单位后），排除编号误识别，去重导入
"""
import os
import sys
import re
import json
import hashlib
from collections import defaultdict
from pathlib import Path
import psycopg2

sys.path.insert(0, str(Path(__file__).parent))


def get_embed_model():
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("/home/l/rag-dashboard/models/BAAI/bge-m3")
        print(f"✓ Embedding model loaded: {model.get_sentence_embedding_dimension()}d")
        return model
    except Exception as e:
        print(f"⚠ Embedding model failed: {e}")
        return None


PG_CONFIG = {
    "host": os.environ.get("PG_HOST", "localhost"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "database": os.environ.get("PG_DB", "rag_db"),
    "user": os.environ.get("PG_USER", "rag_user"),
    "password": os.environ.get("PG_PASSWORD", "rag_password"),
}


def get_pg_conn():
    return psycopg2.connect(**PG_CONFIG)


def get_doc_id_and_code(conn, file_name, file_path, year_month, total_pages):
    doc_code = hashlib.md5(file_name.encode()).hexdigest()[:16]
    cur = conn.cursor()
    cur.execute("SELECT id FROM documents WHERE doc_code = %s", (doc_code,))
    row = cur.fetchone()
    if row:
        return row[0], doc_code
    cur.execute("""
        INSERT INTO documents (file_name, file_path, doc_type, period, total_pages, doc_code, status)
        VALUES (%s, %s, 'price_info', %s, %s, %s, 'imported')
        RETURNING id
    """, (file_name, file_path, year_month, total_pages, doc_code))
    doc_id = cur.fetchone()[0]
    conn.commit()
    return doc_id, doc_code


# ── 价格表识别 ──────────────────────────────────────────────
PRICE_TABLE_KEYWORDS = ["材料名称", "价格", "单位", "型号", "规格", "序号"]
SKIP_KEYWORDS = ["售价", "元/本", "元/套", "资料汇编", "示范文本", "图鉴", "书名", "数量"]
NON_DATA_PATTERNS = [
    r'^仅供内部查阅',
    r'^HJ53',
    r'^深圳市航建工程造价咨询',
    r'^\d+\s*$',
    r'^第\d+期',
]


def is_price_table(cells: list) -> bool:
    all_text = " ".join(c.get("text", "") for c in cells)
    if any(kw in all_text for kw in SKIP_KEYWORDS):
        return False
    header_score = sum(1 for kw in PRICE_TABLE_KEYWORDS if kw in all_text[:300])
    has_price_numbers = bool(re.search(r'\d+\.\d{2}', all_text))
    return header_score >= 2 and has_price_numbers


# ── 核心解析逻辑 v2 ────────────────────────────────────────
UNIT_PATTERN = re.compile(
    r'(t|m³|m²|㎡|m|kg|个|套|组|台|块|片|工日|支|根|卷|桶|箱|件|'
    r'台·月|立方米|平方米|吨|千克|公斤|克|升|毫升|mm|cm|dm)'
)
# 价格必须在行尾或单位后，排除6位以上纯整数（可能是编号/日期）
PRICE_PATTERN_EOL = re.compile(
    r'(?:^|.*?)(\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2}|\d{2,5})\s*$'
)
PRICE_PATTERN_AFTER_UNIT = re.compile(
    r'(?:t|m³|m²|㎡|m|kg|个|套|组|台|块|片|工日|支|根|卷|桶|箱|件|'
    r'台·月|立方米|平方米|吨|千克|公斤)\s*(\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2}|\d{2,5})'
)
SPEC_PATTERN = re.compile(r'([A-Za-z0-9]+[A-Za-z0-9\s\.~\-·×*/°℃%±]*[A-Za-z0-9]+)')


def should_skip_line(full_text: str) -> bool:
    """判断是否为非数据行"""
    if not full_text or len(full_text) < 3:
        return True
    for pat in NON_DATA_PATTERNS:
        if re.match(pat, full_text):
            return True
    if re.match(r'^[一二三四五六七八九十]+[、．.]', full_text) and len(full_text) < 40:
        return True
    if full_text in ['造价信息 深圳建设工程价格信息SZCOST', 'SZCOST深圳建设工程价格信息 造价信',
                     '●建筑材料价格', '●租赁价格', '●市场劳务价格', '支价信息 深圳建设工程价格信息SZCOST',
                     '金价信息 深圳建设工程价格信息SZCOST']:
        return True
    return False


def parse_price_row(row_cells: list) -> dict:
    """从一行cells中联合提取：序号、材料名、规格、单位、价格"""
    all_texts = [c.get("text", "").strip() for c in row_cells]
    full_text = " ".join(t for t in all_texts if t)

    if should_skip_line(full_text):
        return None

    # ── 提取价格（最严格：必须是行尾，或单位后的数字）
    price = None
    price_str = None

    # 策略1: 行尾价格
    m = PRICE_PATTERN_EOL.match(full_text)
    if m:
        candidate = m.group(1)
        val = float(candidate.replace(',', ''))
        if 0.1 <= val <= 500000:  # 租赁机械可达数十万
            price = val
            price_str = candidate

    # 策略2: 单位后价格（策略1失败时）
    if not price:
        m = PRICE_PATTERN_AFTER_UNIT.search(full_text)
        if m:
            candidate = m.group(1)
            val = float(candidate.replace(',', ''))
            if 0.1 <= val <= 500000:
                price = val
                price_str = candidate

    if not price:
        return None

    # ── 提取序号
    seq_match = re.match(r'^(\d+)', full_text)
    seq_no = int(seq_match.group(1)) if seq_match else None

    # ── 提取单位
    unit = ""
    unit_match = UNIT_PATTERN.search(full_text)
    if unit_match:
        unit = unit_match.group(1)

    # ── 清洗文本：去掉价格、单位、序号、常见噪声
    clean = full_text

    # 去掉末尾价格
    if price_str:
        clean = clean[:clean.rfind(price_str)]
    clean = clean.strip()

    # 去掉单位（末尾）
    if unit and clean.endswith(unit):
        clean = clean[:-len(unit)].strip()

    # 去掉序号前缀
    if seq_no is not None:
        clean = re.sub(r'^\d+\s*', '', clean)

    # 去掉表头残留
    clean = re.sub(r'^(?:材料名称|型号、规格|单位|价格（元）|序号|（续前）)\s*', '', clean)
    clean = re.sub(r'\s*（续前）\s*$', '', clean)
    clean = clean.strip()

    # ── 提取规格
    spec = ""
    spec_match = SPEC_PATTERN.search(clean)
    if spec_match:
        spec = spec_match.group(1).strip()
        # 确保规格不是整行材料名的一部分（长度限制）
        if len(spec) < len(clean):
            material_name = clean.replace(spec, "").strip()
            material_name = re.sub(r'^[、．.,\s]+', '', material_name)
            material_name = re.sub(r'[、．.,\s]+$', '', material_name)
        else:
            material_name = clean
            spec = ""
    else:
        material_name = clean

    # 去掉括号内容
    material_name = re.sub(r'[（(].*?[)）]', '', material_name).strip()

    if not material_name or len(material_name) < 2:
        return None

    return {
        "seq_no": seq_no,
        "material_name": material_name,
        "spec": spec,
        "unit": unit,
        "price": price,
        "raw": full_text[:200],
    }


def parse_formula_row(row_cells: list) -> dict:
    """解析公式类型行（如 D²×959+50）"""
    all_texts = [c.get("text", "").strip() for c in row_cells]
    full_text = " ".join(t for t in all_texts if t)

    if should_skip_line(full_text):
        return None

    # 检测公式特征
    formula_match = re.search(
        r'([A-Za-z][A-Za-z0-9\s]*[²²×\*\+\-/]?\s*\d+[\d\s\.×\*\+\-/]*)',
        full_text
    )
    if not formula_match:
        return None

    formula = formula_match.group(1).replace(' ', '').strip()
    if not re.search(r'[×\*\+/\-²²]', formula):
        return None

    seq_match = re.match(r'^(\d+)', full_text)
    seq_no = int(seq_match.group(1)) if seq_match else None

    # 提取材料名（公式前的中文）
    material_match = re.search(r'([\u4e00-\u9fa5]+(?:阀|管|口|风|箱|柜|架|线|槽|管|盒|盘|栅|罩))', full_text)
    material_name = material_match.group(0) if material_match else ""

    unit_match = UNIT_PATTERN.search(full_text)
    unit = unit_match.group(1) if unit_match else ""

    agency_match = re.search(r'([A-Z][a-zA-Z0-9\-]+)', full_text)
    agency_code = agency_match.group(1) if agency_match else ""

    if not material_name:
        return None

    return {
        "seq_no": seq_no,
        "material_name": material_name,
        "spec": "",
        "unit": unit,
        "price": None,
        "price_formula": formula,
        "agency_code": agency_code,
        "raw": full_text[:200],
    }


def extract_year_month(file_name: str) -> str:
    m = re.search(r'202(\d)-(\d{1,2})', file_name)
    if m:
        return f"202{m.group(1)}-{m.group(2).zfill(2)}"
    m = re.search(r'202(\d)年(\d{1,2})月', file_name)
    if m:
        return f"202{m.group(1)}-{m.group(2).zfill(2)}"
    return ""


def import_price_json(json_path: str, embed_model):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    file_name = data.get("file_name", os.path.basename(json_path))
    year_month = extract_year_month(file_name)
    total_pages = data.get("total_pages", 0)

    conn = get_pg_conn()
    doc_id, doc_code = get_doc_id_and_code(conn, file_name, json_path, year_month, total_pages)

    total_records = 0
    total_text_blocks = 0
    seen_raw_hashes = set()  # 行级去重

    for page in data.get("pages", []):
        page_num = page.get("page_number", 1)

        # ── 1. 处理价格表 ──
        for table in page.get("tables", []):
            cells = table.get("cells", [])
            if not cells:
                continue

            if not is_price_table(cells):
                continue

            rows = defaultdict(list)
            for c in cells:
                rows[c.get("row", 0)].append(c)

            for row_idx in sorted(rows.keys()):
                row_cells = sorted(rows[row_idx], key=lambda x: x.get("col", 0))

                result = parse_formula_row(row_cells)
                if not result:
                    result = parse_price_row(row_cells)

                if result:
                    h = hashlib.md5(result["raw"].encode()).hexdigest()
                    if h in seen_raw_hashes:
                        continue
                    seen_raw_hashes.add(h)

                    insert_price_record(conn, doc_id, doc_code, year_month, page_num, result)
                    total_records += 1

        # ── 2. 处理文字页 ──
        text_blocks = page.get("text_blocks", [])
        page_texts = []
        for block in text_blocks:
            text = block.get("text", "").strip()
            if len(text) >= 15 and not text.startswith("仅供内部查阅"):
                page_texts.append(text)

        if page_texts:
            full_page_text = "\n".join(page_texts)
            if len(full_page_text) > 80:
                insert_text_chunk(conn, doc_id, doc_code, year_month, page_num, full_page_text, embed_model)
                total_text_blocks += 1

    conn.commit()
    conn.close()

    print(f"✓ {file_name}: {total_pages} pages, {total_records} price_records, {total_text_blocks} text_chunks")
    return total_records, total_text_blocks


def insert_price_record(conn, doc_id, doc_code, year_month, page_num, record):
    material = record.get("material_name", "")
    spec = record.get("spec", "")
    unit = record.get("unit", "")
    price = record.get("price")
    formula = record.get("price_formula")
    agency = record.get("agency_code", "")
    seq_no = record.get("seq_no")
    raw = record.get("raw", "")

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO price_records 
        (document_id, period, material_name, spec, unit, price, price_formula, 
         agency_code, seq_no, page_number, source_doc, source_row, confidence)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """, (
        doc_id, year_month, material, spec, unit, price, formula,
        agency, seq_no, page_num, "ocr_json", json.dumps({"raw": raw}, ensure_ascii=False), 0.95
    ))


def insert_text_chunk(conn, doc_id, doc_code, year_month, page_num, content, embed_model):
    embedding = None
    if embed_model:
        try:
            embedding = embed_model.encode(content[:500]).tolist()
        except Exception:
            pass

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO text_chunks (document_id, chunk_index, content, page_number, period, doc_type, chunk_type, embedding)
        VALUES (%s, %s, %s, %s, %s, 'price_info', 'article', %s)
    """, (doc_id, page_num, content, page_num, year_month, embedding))


def main():
    print("=== Phase 2: 深圳信息价价格表精准解析入库 v2 ===\n")

    embed_model = get_embed_model()

    ocr_dir = "/home/l/rag-dashboard/data/ocr_outputs"
    all_jsons = sorted([f for f in os.listdir(ocr_dir) if f.endswith('.json')])

    # 去重策略：优先 merged 文件，跳过 chunk 文件
    merged = [f for f in all_jsons if 'merged' in f]
    single = [f for f in all_jsons if 'merged' not in f and 'chunk' not in f]

    # 建立 year_month -> 文件映射，确保每个年月只导入一次
    imported_months = set()
    target_files = []

    for f in merged + single:
        ym = extract_year_month(f)
        if ym and ym not in imported_months:
            imported_months.add(ym)
            target_files.append(f)

    print(f"Target files ({len(target_files)}): {target_files}\n")

    total_records = 0
    total_texts = 0

    for fname in target_files:
        path = os.path.join(ocr_dir, fname)
        try:
            recs, texts = import_price_json(path, embed_model)
            total_records += recs
            total_texts += texts
        except Exception as e:
            print(f"✗ {fname}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n=== Phase 2 完成 ===")
    print(f"Total price_records: {total_records}")
    print(f"Total text_chunks: {total_texts}")

    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute("SELECT period, COUNT(*) FROM price_records GROUP BY period ORDER BY period")
    print("\n价格记录分月统计:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}条")
    conn.close()


if __name__ == "__main__":
    main()

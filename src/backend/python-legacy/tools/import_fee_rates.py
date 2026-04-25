#!/usr/bin/env python3
"""
Phase 1: 计价费率标准直接入库
- 有文本层，PyMuPDF 直接提取
- 双路写入：text_chunks（全文搜索）+ fee_rates（结构化费率）
"""
import os
import sys
import re
import json
import psycopg2
from pathlib import Path

# embedding 模型加载（复用现有逻辑）
def get_embed_model():
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("/home/l/rag-dashboard/models/BAAI/bge-m3")
        print(f"✓ Embedding model loaded: {model.get_sentence_embedding_dimension()}d")
        return model
    except Exception as e:
        print(f"⚠ Embedding model failed: {e}, will skip embeddings")
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


def get_doc_id_and_code(conn, file_name, file_path, standard_year, total_pages):
    doc_code = f"fee_rate_{standard_year}"
    cur = conn.cursor()
    cur.execute("SELECT id FROM documents WHERE doc_code = %s", (doc_code,))
    row = cur.fetchone()
    if row:
        return row[0], doc_code
    cur.execute("""
        INSERT INTO documents (file_name, file_path, doc_type, period, total_pages, doc_code, status)
        VALUES (%s, %s, 'fee_standard', %s, %s, %s, 'imported')
        RETURNING id
    """, (file_name, file_path, standard_year, total_pages, doc_code))
    doc_id = cur.fetchone()[0]
    conn.commit()
    return doc_id, doc_code


def infer_category(fee_name: str) -> str:
    fee_name = fee_name.strip()
    if '安全文明' in fee_name or '文明施工' in fee_name:
        return '安全文明施工费'
    if '赶工' in fee_name:
        return '赶工措施费'
    if '夜间' in fee_name:
        return '夜间施工增加费'
    if '总包' in fee_name or '总承包' in fee_name:
        return '总承包服务费'
    if '企业管理' in fee_name:
        return '企业管理费'
    if '利润' in fee_name:
        return '利润'
    if '担保' in fee_name:
        return '履约担保手续费'
    if '计日工' in fee_name:
        return '计日工'
    return '其他项目费'


_FEE_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "企业管理费": ("企业管理费", "程，企业管理费"),
    "利润": ("利润率", "利润"),
    "安全文明施工费": ("安全文明施工费", "文明施工费"),
    "夜间施工增加费": ("夜间施工增加费",),
    "赶工措施费": ("赶工措施费",),
    "总承包服务费": ("总包管理服务费", "总承包服务费"),
    "发包人供应材料（设备）保管费": ("发包人供应材料（设备）保管费", "材料（设备）保管费"),
    "履约担保手续费": ("履约担保手续费", "担保手续费"),
}


def _normalize_fee_text(text: str) -> str:
    cleaned = text.replace("＋", "+").replace("十", "+").replace("X", "×")
    cleaned = re.sub(r"HJ53-[A-Za-z0-9\-]+", " ", cleaned)
    cleaned = re.sub(r"仅供内部查阅|仅供内部|供内部查|禁止外传|禁止外", " ", cleaned)
    cleaned = re.sub(r"\n\s*\d+\s*\n", "\n", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)
    return cleaned.strip()


def _normalize_fee_name(fee_name: str, source_text: str = "") -> str:
    for canonical, aliases in _FEE_NAME_ALIASES.items():
        if any(alias in fee_name for alias in aliases):
            return canonical
    combined = f"{fee_name} {source_text}".strip()
    for canonical, aliases in _FEE_NAME_ALIASES.items():
        if any(alias in combined for alias in aliases):
            return canonical
    return fee_name.strip()


def _extract_source_excerpt(text: str, anchor: str, window: int = 260) -> str:
    idx = text.find(anchor)
    if idx < 0:
        return text[:window].strip()
    start = max(0, idx - 40)
    end = min(len(text), idx + window)
    return text[start:end].strip()


def _extract_named_fee_records(text: str, standard_year: str) -> list[dict]:
    cleaned = _normalize_fee_text(text)
    compact = re.sub(r"\s+", "", cleaned)
    records: list[dict] = []
    specs = [
        {
            "name": "企业管理费",
            "category": "企业管理费",
            "anchor": "企业管理费",
            "range_pattern": r"企业管理费费率参考范围[为：:]?(\d+\.?\d*)[%％][～~](\d+\.?\d*)[%％]，?推荐费率[为：:]?(\d+\.?\d*)[%％]",
            "formula_pattern": r"(企业管理费[:：A-Za-z=＝]*（?人工费.*?企业管理费费率)",
        },
        {
            "name": "利润",
            "category": "利润",
            "anchor": "利润",
            "range_pattern": r"利润率参考范围[为：:]?(\d+\.?\d*)[%％][～~](\d+\.?\d*)[%％]，?推荐费率[为：:]?(\d+\.?\d*)[%％]",
            "formula_pattern": r"(利润[:：A-Za-z=＝Ff]*（?人工费.*?利润率)",
        },
    ]

    for spec in specs:
        range_match = re.search(spec["range_pattern"], compact)
        if not range_match:
            continue
        formula_match = re.search(spec["formula_pattern"], compact)
        records.append({
            'fee_name': spec["name"],
            'fee_category': spec["category"],
            'rate_min': float(range_match.group(1)),
            'rate_max': float(range_match.group(2)),
            'rate_recommended': float(range_match.group(3)),
            'standard_year': standard_year,
            'source_text': _extract_source_excerpt(cleaned, spec["anchor"]),
            'base_formula': formula_match.group(1) if formula_match else None,
        })

    return records


def parse_fee_text(text: str, standard_year: str) -> list[dict]:
    """从费率标准文本中提取结构化费率数据"""
    text = _normalize_fee_text(text)
    records = []

    for record in _extract_named_fee_records(text, standard_year):
        records.append(record)

    # 模式1: "参考范围为X%～Y%，推荐费率为Z%"
    pattern1 = re.compile(
        r'([^。\n]{2,30}?)费率?参考范围[为：:]\s*(\d+\.?\d*)[%％]\s*[～~]\s*(\d+\.?\d*)[%％][，,。、]\s*推荐费率[为：:]\s*(\d+\.?\d*)[%％]'
    )
    for m in pattern1.finditer(text):
        records.append({
            'fee_name': _normalize_fee_name(m.group(1).strip(), text[max(0, m.start()-50):m.end()+50]),
            'fee_category': infer_category(_normalize_fee_name(m.group(1).strip(), text[max(0, m.start()-50):m.end()+50])),
            'rate_min': float(m.group(2)),
            'rate_max': float(m.group(3)),
            'rate_recommended': float(m.group(4)),
            'standard_year': standard_year,
            'source_text': text[max(0, m.start()-50):m.end()+50],
            'base_formula': None,
        })

    # 模式2: "费率参考范围：X‰～Y‰，推荐费率Z‰"
    pattern2 = re.compile(
        r'([^。\n]{2,30}?)费率?参考范围[为：:]\s*(\d+\.?\d*)[‰]\s*[～~]\s*(\d+\.?\d*)[‰][，,。、]\s*推荐费率[为：:]\s*(\d+\.?\d*)[‰]'
    )
    for m in pattern2.finditer(text):
        records.append({
            'fee_name': _normalize_fee_name(m.group(1).strip(), text[max(0, m.start()-50):m.end()+50]),
            'fee_category': infer_category(_normalize_fee_name(m.group(1).strip(), text[max(0, m.start()-50):m.end()+50])),
            'rate_min': float(m.group(2)) / 10,
            'rate_max': float(m.group(3)) / 10,
            'rate_recommended': float(m.group(4)) / 10,
            'standard_year': standard_year,
            'source_text': text[max(0, m.start()-50):m.end()+50],
            'base_formula': None,
        })

    # 模式3: 表格行 "专业名称  X.XX～X.XX  X.XX"
    pattern3 = re.compile(
        r'([\u4e00-\u9fa5、，]+(?:工程|费))\s*\n\s*(\d+\.?\d*)\s*[～~]\s*(\d+\.?\d*)\s*\n\s*(\d+\.?\d*)'
    )
    for m in pattern3.finditer(text):
        records.append({
            'fee_name': _normalize_fee_name(m.group(1).strip(), text[max(0, m.start()-30):m.end()+30]),
            'fee_category': infer_category(_normalize_fee_name(m.group(1).strip(), text[max(0, m.start()-30):m.end()+30])),
            'rate_min': float(m.group(2)),
            'rate_max': float(m.group(3)),
            'rate_recommended': float(m.group(4)),
            'standard_year': standard_year,
            'source_text': text[max(0, m.start()-30):m.end()+30],
            'base_formula': None,
        })

    # 模式4: 利润/企业管理费等单独提到的推荐费率
    pattern4 = re.compile(
        r'(企业管理费|利润率|利润)[^。]*?推荐费率[为：:]\s*(\d+\.?\d*)[%％]'
    )
    for m in pattern4.finditer(text):
        # 需要从上下文找参考范围
        ctx = text[max(0, m.start()-100):m.end()]
        range_match = re.search(r'(\d+\.?\d*)[%％]\s*[～~]\s*(\d+\.?\d*)[%％]', ctx)
        if range_match:
            records.append({
                'fee_name': _normalize_fee_name(m.group(1).strip(), ctx),
                'fee_category': infer_category(_normalize_fee_name(m.group(1).strip(), ctx)),
                'rate_min': float(range_match.group(1)),
                'rate_max': float(range_match.group(2)),
                'rate_recommended': float(m.group(2)),
                'standard_year': standard_year,
                'source_text': ctx,
                'base_formula': None,
            })

    # 去重
    seen = set()
    unique = []
    for r in records:
        key = (r['fee_name'], r['rate_recommended'], r['standard_year'])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def split_paragraphs(text: str, min_len=50) -> list[str]:
    paragraphs = []
    for para in re.split(r'\n{2,}', text):
        para = para.strip()
        if len(para) < min_len:
            continue
        if '仅供内部查阅' in para and len(para) < 150:
            continue
        if '深圳市航建工程造价咨询' in para and len(para) < 150:
            continue
        if re.match(r'^\d+\s*$', para):
            continue
        paragraphs.append(para)
    return paragraphs


def import_fee_rate_pdf(pdf_path: str, standard_year: str, embed_model):
    import fitz
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    file_name = os.path.basename(pdf_path)

    conn = get_pg_conn()
    doc_id, doc_code = get_doc_id_and_code(conn, file_name, pdf_path, standard_year, total_pages)

    chunk_idx = 0
    fee_records = []

    for page_num in range(1, total_pages + 1):
        page = doc[page_num - 1]
        text = page.get_text()

        paragraphs = split_paragraphs(text)
        for para in paragraphs:
            embedding = None
            if embed_model:
                try:
                    embedding = embed_model.encode(para).tolist()
                except Exception as e:
                    pass
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO text_chunks (document_id, chunk_index, content, page_number, doc_type, chunk_type, embedding)
                VALUES (%s, %s, %s, %s, 'fee_standard', 'fee_text', %s)
            """, (doc_id, chunk_idx, para, page_num, embedding))
            chunk_idx += 1

        page_fees = parse_fee_text(text, standard_year)
        for r in page_fees:
            r['page_number'] = page_num
        fee_records.extend(page_fees)

    cur = conn.cursor()
    for r in fee_records:
        embedding = None
        if embed_model:
            try:
                embed_text = r['fee_name'] + " " + r.get('source_text', '')[:200]
                embedding = embed_model.encode(embed_text).tolist()
            except Exception:
                pass
        cur.execute("""
            INSERT INTO fee_rates (doc_code, document_id, standard_year, fee_name, fee_category,
                rate_min, rate_max, rate_recommended, source_text, page_number, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (
            doc_code, doc_id, r['standard_year'], r['fee_name'], r['fee_category'],
            r['rate_min'], r['rate_max'], r['rate_recommended'],
            r.get('source_text', ''), r.get('page_number', 1),
            embedding
        ))

    conn.commit()
    doc.close()
    conn.close()

    print(f"✓ {file_name} ({standard_year}): {total_pages} pages, {chunk_idx} text_chunks, {len(fee_records)} fee_records")
    return chunk_idx, len(fee_records)


def main():
    print("=== Phase 1: 计价费率标准直接入库 ===\n")

    embed_model = get_embed_model()

    base = "/home/l/rag-dashboard/data/knowledge_base/深圳市建设工程地方标准"
    files = [
        (os.path.join(base, "深圳市建设工程计价费率标准（2023）.pdf"), "2023"),
        (os.path.join(base, "深圳市建设工程计价费率标准（2025）.pdf"), "2025"),
    ]

    total_chunks = 0
    total_fees = 0
    for path, year in files:
        if not os.path.exists(path):
            print(f"✗ File not found: {path}")
            continue
        chunks, fees = import_fee_rate_pdf(path, year, embed_model)
        total_chunks += chunks
        total_fees += fees

    print(f"\n=== Phase 1 完成 ===")
    print(f"Total text_chunks: {total_chunks}")
    print(f"Total fee_rates: {total_fees}")

    # 验证
    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute("SELECT standard_year, fee_category, COUNT(*) FROM fee_rates GROUP BY standard_year, fee_category ORDER BY standard_year, fee_category")
    print("\n费率分类统计:")
    for row in cur.fetchall():
        print(f"  {row[0]} | {row[1]:20s} | {row[2]}条")
    conn.close()


if __name__ == "__main__":
    main()

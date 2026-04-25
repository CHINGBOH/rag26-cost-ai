#!/usr/bin/env python3
"""
费率标准入库脚本（修复版）
原始文件：src/backend/python-legacy/tools/import_fee_rates.py

修复点：
  1. text_chunks INSERT：(document_id INT FK) → (doc_id TEXT, file_name TEXT)
  2. fee_rates INSERT：补充 doc_id 列（tools.py _query_structured_tables 依赖此列）
  3. 修正 embedding 模型路径（bge-m3 snapshots 路径）
  4. text_chunks embedding 使用 %s::vector cast
"""
import os
import re
import psycopg2
from pathlib import Path

# ── 配置 ─────────────────────────────────────────────────────────
PG_CONFIG = {
    "host":     os.environ.get("PG_HOST", "localhost"),
    "port":     int(os.environ.get("PG_PORT", "5432")),
    "database": os.environ.get("PG_DB", "rag_db"),
    "user":     os.environ.get("PG_USER", "rag_user"),
    "password": os.environ.get("PG_PASSWORD") or "",
}

KNOWLEDGE_BASE = Path("/home/l/rag-dashboard/data/knowledge_base/深圳市建设工程地方标准")
PDF_FILES = [
    (KNOWLEDGE_BASE / "深圳市建设工程计价费率标准（2023）.pdf", "2023"),
    (KNOWLEDGE_BASE / "深圳市建设工程计价费率标准（2025）.pdf", "2025"),
]

# 按优先级尝试模型路径
_MODEL_CANDIDATES = [
    "/home/l/rag-dashboard/models/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181",
    "/home/l/rag-dashboard/models/BAAI/bge-m3",
]


# ── 工具函数 ──────────────────────────────────────────────────────
def get_pg_conn():
    return psycopg2.connect(**PG_CONFIG)


def get_embed_model():
    try:
        import torch
        from sentence_transformers import SentenceTransformer
        device = "cuda" if torch.cuda.is_available() else "cpu"
        for path in _MODEL_CANDIDATES:
            if Path(path).exists():
                model = SentenceTransformer(path, device=device)
                print(f"✓ 模型已加载 ({model.get_embedding_dimension()}d) [{device}]: {path}")
                return model
        model = SentenceTransformer("BAAI/bge-m3", device=device)
        print(f"✓ 模型已从 HuggingFace 加载 [{device}]")
        return model
    except Exception as e:
        print(f"⚠ 嵌入模型加载失败: {e}，跳过 embedding 生成")
        return None


def infer_category(fee_name: str) -> str:
    n = fee_name.strip()
    if "安全文明" in n or "文明施工" in n: return "安全文明施工费"
    if "赶工" in n:                        return "赶工措施费"
    if "夜间" in n:                        return "夜间施工增加费"
    if "总包" in n or "总承包" in n:       return "总承包服务费"
    if "企业管理" in n:                    return "企业管理费"
    if "利润" in n:                        return "利润"
    if "担保" in n:                        return "履约担保手续费"
    if "计日工" in n:                      return "计日工"
    return "其他项目费"


_FEE_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "企业管理费": ("企业管理费", "程，企业管理费"),
    "利润": ("利润率", "利润"),
    "安全文明施工费": ("安全文明施工费", "文明施工费"),
    "夜间施工增加费": ("夜间施工增加费",),
    "赶工措施费": ("赶工措施费",),
    "总承包服务费": ("总包管理服务费", "总承包服务费"),
    "发包人供应材料（设备）保管费": ("发包人供应材料（设备）保管费", "材料（设备）保管费"),
    "履约担保手续费": ("履约担保手续费", "担保手续费"),
    "暂列金额": ("暂列金额",),
    "优质优价奖励费": ("优质优价奖励费",),
    "计日工": ("计日工",),
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
            "fee_name": spec["name"],
            "fee_category": spec["category"],
            "rate_min": float(range_match.group(1)),
            "rate_max": float(range_match.group(2)),
            "rate_recommended": float(range_match.group(3)),
            "standard_year": standard_year,
            "source_text": _extract_source_excerpt(cleaned, spec["anchor"]),
            "base_formula": formula_match.group(1) if formula_match else None,
        })

    return records


def parse_fee_text(text: str, standard_year: str) -> list[dict]:
    """
    PDF 费率提取 — 支持两种格式：
      A. 内联文字: "...参考范围为9%～25%，推荐费率为16.2%"
         及 "参考范围：2‰～6‰，推荐费率4‰"
      B. 表格行（PyMuPDF 提取后以换行分隔）:
            建筑工程\n1.92～5.75\n3.68
         需要结合当前 section 标题推断 fee_category。
    """
    text = _normalize_fee_text(text)
    records = []
    seen: set = set()

    def add(name, cat, rmin, rmax, rrec, src, formula=None):
        canonical_name = _normalize_fee_name(name, src)
        canonical_category = cat or infer_category(canonical_name)
        key = (canonical_name, rmin, rmax, str(rrec), standard_year)
        if key in seen:
            return
        seen.add(key)
        records.append({
            "fee_name": canonical_name,
            "fee_category": canonical_category,
            "rate_min": rmin,
            "rate_max": rmax,
            "rate_recommended": rrec,
            "standard_year": standard_year,
            "source_text": src[:300],
            "base_formula": formula,
        })

    for record in _extract_named_fee_records(text, standard_year):
        add(
            record["fee_name"],
            record["fee_category"],
            record["rate_min"],
            record["rate_max"],
            record["rate_recommended"],
            record["source_text"],
            record.get("base_formula"),
        )

    # ── A1: "...参考范围[为：:]X%～Y%，推荐费率Z%" ─────────────────
    p_inline_pct = re.compile(
        r'([^。\n]{2,40}?)'
        r'费率?参考范围[为：:]\s*(\d+\.?\d*)\s*[%％]\s*[～~]\s*(\d+\.?\d*)\s*[%％]'
        r'[，,、。]?\s*推荐费率[为：:为]?\s*(\d+\.?\d*)\s*[%％]'
    )
    for m in p_inline_pct.finditer(text):
        add(m.group(1).strip(), None,
            float(m.group(2)), float(m.group(3)), float(m.group(4)),
            text[max(0, m.start()-30): m.end()+50])

    # ── A2: "参考范围：2‰～6‰，推荐费率4‰"（‰ 转为 % 除以10）──────
    p_inline_per_mille = re.compile(
        r'([^。\n]{2,40}?)'
        r'费率?参考范围[为：:]\s*(\d+\.?\d*)\s*[‰]\s*[～~]\s*(\d+\.?\d*)\s*[‰]'
        r'[，,、。]?\s*推荐费率[为：:为]?\s*(\d+\.?\d*)\s*[‰]'
    )
    for m in p_inline_per_mille.finditer(text):
        add(m.group(1).strip(), None,
            float(m.group(2)) / 10, float(m.group(3)) / 10, float(m.group(4)) / 10,
            text[max(0, m.start()-30): m.end()+50])

    # ── B: 表格行（含 section 上下文感知）────────────────────────────
    # 识别当前所处的 section（费用大类）
    SECTION_MAP = {
        "安全文明施工": "安全文明施工费",
        "夜间施工":     "夜间施工增加费",
        "赶工措施":     "赶工措施费",
        "总承包服务":   "总承包服务费",
        "履约担保":     "履约担保手续费",
        "产业工人职业训练": "产业工人职业训练专项经费",
    }
    # 逐行解析，追踪 section
    range_pat = re.compile(r'^(\d+\.?\d*)\s*[～~]\s*(\d+\.?\d*)$')
    num_pat   = re.compile(r'^(\d+\.?\d*)$')
    p_row     = re.compile(
        r'([一-鿿、，\w]{2,25})\s+'
        r'(\d+\.?\d*)\s*[～~]\s*(\d+\.?\d*)\s+'
        r'(\d+\.?\d*)'
    )
    lines = text.splitlines()
    current_section = ""
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # 更新 section 标题
        for kw, cat in SECTION_MAP.items():
            if kw in line and ("费" in line or "经费" in line):
                current_section = cat
                break

        # 模式 B1: 专业名称行 + 下一行 "X～Y" + 再下一行 "Z"（或同一行空格分隔）
        # 例:  "建筑工程\n1.92～5.75\n3.68"

        if (range_pat.match(line) is None and num_pat.match(line) is None
                and len(line) >= 2 and len(line) <= 40
                and re.search(r'[\u4e00-\u9fff]', line)):
            # 可能是名称行，往后找数值
            # 跳过空行
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                next_line = lines[j].strip()
                rm = range_pat.match(next_line)
                if rm:
                    # 再往后找推荐值
                    k = j + 1
                    while k < len(lines) and not lines[k].strip():
                        k += 1
                    if k < len(lines):
                        rec_line = lines[k].strip()
                        nm = num_pat.match(rec_line)
                        if nm:
                            fee_name = line.replace('\n', '').strip()
                            # 过滤掉表头行
                            SKIP = {"费用名称", "专业工程", "系数", "费率", "推荐费率", "参考范围", "推荐系数"}
                            if fee_name not in SKIP and not re.match(r'^[\d.]+$', fee_name):
                                add(
                                    fee_name,
                                    current_section or infer_category(fee_name),
                                    float(rm.group(1)), float(rm.group(2)), float(nm.group(1)),
                                    "\n".join(lines[max(0,i-1): k+2]),
                                )
                            i = k + 1
                            continue

        # 模式 B2: 单行表格 "名称  X～Y  Z"

        m2 = p_row.match(line)
        if m2:
            fee_name = m2.group(1).strip()
            SKIP = {"费用名称", "专业工程", "系数", "费率", "推荐费率", "参考范围"}
            if fee_name not in SKIP:
                add(
                    fee_name,
                    current_section or infer_category(fee_name),
                    float(m2.group(2)), float(m2.group(3)), float(m2.group(4)),
                    line,
                )
        i += 1

    return records


def split_paragraphs(text: str, min_len: int = 50) -> list[str]:
    result = []
    for para in re.split(r"\n{2,}", text):
        para = para.strip()
        if len(para) >= min_len:
            result.append(para)
    return result


# ── 核心入库函数 ──────────────────────────────────────────────────
def import_one(pdf_path: Path, standard_year: str, embed_model, conn) -> tuple[int, int]:
    import fitz  # PyMuPDF

    doc = fitz.open(str(pdf_path))
    file_name = pdf_path.name
    doc_id = f"fee_rate_{standard_year}"
    cur = conn.cursor()
    chunk_idx = 0
    fee_records = []

    try:
        cur.execute("DELETE FROM text_chunks WHERE doc_id = %s", (doc_id,))
        cur.execute("DELETE FROM fee_rates WHERE doc_id = %s", (doc_id,))
        conn.commit()

        for page_num in range(1, len(doc) + 1):
            text = doc[page_num - 1].get_text()

            # ── text_chunks 写入（修复：用 doc_id TEXT，不是 document_id INT FK）──
            for para in split_paragraphs(text):
                embedding = None
                if embed_model:
                    try:
                        embedding = embed_model.encode(para, normalize_embeddings=True).tolist()
                    except Exception:
                        pass

                cur.execute(
                    """INSERT INTO text_chunks
                       (doc_id, file_name, chunk_index, content, page_number, embedding)
                       VALUES (%s, %s, %s, %s, %s, %s::vector)
                       ON CONFLICT DO NOTHING""",
                    (doc_id, file_name, chunk_idx, para, page_num, embedding),
                )
                chunk_idx += 1

            fee_records.extend(
                [{**r, "page_number": page_num} for r in parse_fee_text(text, standard_year)]
            )

        # ── fee_rates 写入（修复：加 doc_id 列）─────────────────────────
        for r in fee_records:
            embedding = None
            if embed_model:
                try:
                    embed_text = r["fee_name"] + " " + r.get("source_text", "")[:200]
                    embedding = embed_model.encode(embed_text, normalize_embeddings=True).tolist()
                except Exception:
                    pass
            cur.execute(
                """INSERT INTO fee_rates
                   (doc_id, doc_code, document_id, standard_year,
                    fee_name, fee_category, base_formula,
                    rate_min, rate_max, rate_recommended,
                    source_text, page_number, embedding)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                   ON CONFLICT DO NOTHING""",
                (
                    doc_id, doc_id, None,
                    r["standard_year"], r["fee_name"], r["fee_category"], r.get("base_formula"),
                    r["rate_min"], r["rate_max"], r["rate_recommended"],
                    r.get("source_text", ""), r.get("page_number", 1),
                    embedding,
                ),
            )

        conn.commit()
    finally:
        doc.close()

    print(f"  ✓ {file_name} ({standard_year}): {chunk_idx} text_chunks, {len(fee_records)} fee_rates")
    return chunk_idx, len(fee_records)


def main():
    print("=== 费率标准入库（修复版）===\n")
    embed_model = get_embed_model()
    conn = get_pg_conn()
    try:
        total_chunks, total_fees = 0, 0
        for pdf_path, year in PDF_FILES:
            if not pdf_path.exists():
                print(f"✗ 文件不存在: {pdf_path}")
                continue
            c, f = import_one(pdf_path, year, embed_model, conn)
            total_chunks += c
            total_fees += f
    finally:
        conn.close()

    print(f"\n完成: {total_chunks} text_chunks, {total_fees} fee_rates rows")

    # 统计汇报
    conn2 = get_pg_conn()
    try:
        cur = conn2.cursor()
        cur.execute(
            "SELECT standard_year, fee_category, COUNT(*) FROM fee_rates "
            "GROUP BY standard_year, fee_category ORDER BY standard_year, fee_category"
        )
        rows = cur.fetchall()
    finally:
        conn2.close()
    if rows:
        print("\n── fee_rates 分类统计 ──")
        for yr, cat, n in rows:
            print(f"  {yr}  {(cat or '未分类'):<25s}  {n} 条")


if __name__ == "__main__":
    main()

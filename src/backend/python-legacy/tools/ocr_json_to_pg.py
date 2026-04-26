#!/usr/bin/env python3
"""
OCR JSON → price_records
解析 OCR 输出中的表格数据，提取结构化价格信息写入 PostgreSQL + pgvector。
"""

import os
import sys
import json
import re
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

# Allow imports from project root
project_root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(project_root))

import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OCR_DIR = Path(os.environ.get("OCR_OUTPUT_DIR", project_root / "data" / "ocr_outputs"))
KB_DIR = Path(os.environ.get("KB_DIR", project_root / "data" / "knowledge_base" / "documents"))

PG_CONFIG = {
    "host": os.environ.get("PG_HOST", "localhost"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "database": os.environ.get("PG_DB", "rag_db"),
    "user": os.environ.get("PG_USER", "rag_user"),
    "password": os.environ.get("PG_PASSWORD", "rag_password"),
}

# Embedding (reuse local model)
EMBEDDING_MODEL = None
_EMBEDDING_LOAD_FAILED = False  # Cache load failure to avoid retrying per-row
UNIT_TOKEN_RE = re.compile(r"^(m³|m²|㎡|m|t|kg|个|套|组|台|块|片|工日|支|根|卷|桶|箱|件)$")
INVALID_MATERIAL_RE = re.compile(r"[，,。；;：:]")
MATERIAL_SKIP_TOKENS = (
    "价格信息",
    "造价信息",
    "材料名称",
    "部分材料价格变化趋势图",
    "深圳建设工程价格信息",
)
MAX_REASONABLE_PRICE = 10_000_000.0


def _get_embedding_model():
    global EMBEDDING_MODEL, _EMBEDDING_LOAD_FAILED
    if _EMBEDDING_LOAD_FAILED:
        return None
    if EMBEDDING_MODEL is not None:
        return EMBEDDING_MODEL
    try:
        from sentence_transformers import SentenceTransformer

        model_path = os.environ.get("EMBEDDING_MODEL", str(project_root / "models" / "BAAI" / "bge-m3"))
        logger.info(f"Loading embedding model: {model_path}")
        EMBEDDING_MODEL = SentenceTransformer(model_path, device="cpu")
        return EMBEDDING_MODEL
    except Exception as e:
        logger.warning(f"Failed to load embedding model: {e}. Embeddings will be NULL.")
        _EMBEDDING_LOAD_FAILED = True
        return None


def get_embedding(text: str) -> Optional[List[float]]:
    model = _get_embedding_model()
    if model is None:
        return None
    try:
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()
    except Exception as e:
        logger.warning(f"Embedding failed: {e}")
        return None


def get_pg_conn():
    return psycopg2.connect(**PG_CONFIG)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def extract_year_month(filename: str) -> str:
    """从文件名提取年月，如 '2025-01_ocr.json' → '2025-01'"""
    # 模式1: 2025-01, 2025年1月, 2025年01月
    m = re.search(r"(20\d{2})[\-\s年]?(\d{1,2})\s*[月_]?", filename)
    if m:
        y, mo = m.group(1), m.group(2).zfill(2)
        return f"{y}-{mo}"
    # 模式2: 2025年1月（中文格式）
    m = re.search(r"(20\d{2})年(\d{1,2})月", filename)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}"
    # 模式3: 只匹配年月数字组合，排除 chunk_001 等
    m = re.search(r"(20\d{2})(\d{2})[^\d]", filename)
    if m:
        y, mo = m.group(1), m.group(2)
        if 1 <= int(mo) <= 12:
            return f"{y}-{mo}"
    return ""


def parse_table_cells(cells: List[Dict]) -> List[Dict[str, str]]:
    """将 cells 数组转为行字典列表"""
    if not cells:
        return []
    # 确定行列范围
    rows = {}
    for c in cells:
        r = c.get("row", 0)
        col = c.get("col", 0)
        text = c.get("text", "").strip()
        if r not in rows:
            rows[r] = {}
        rows[r][col] = text

    # 找到表头行（包含"材料名称"、"规格"、"单位"、"价格"等关键词）
    header_row_idx = None
    header_map = {}
    for r_idx, cols in sorted(rows.items()):
        values = " ".join(cols.values())
        if any(k in values for k in ("材料名称", "名称", "规格", "单位", "价格", "含税", "除税")):
            header_row_idx = r_idx
            for col_idx, text in cols.items():
                t = text.strip()
                if "材料" in t or "名称" in t:
                    header_map["material"] = col_idx
                elif "规格" in t:
                    header_map["spec"] = col_idx
                elif "单位" in t:
                    header_map["unit"] = col_idx
                elif "含税" in t:
                    header_map["price_tax"] = col_idx
                elif "除税" in t:
                    header_map["price_no_tax"] = col_idx
                elif "价格" in t or "单价" in t:
                    header_map["price"] = col_idx
            break

    if header_row_idx is None:
        return []

    results = []
    for r_idx, cols in sorted(rows.items()):
        if r_idx <= header_row_idx:
            continue
        row = {}
        for key, col_idx in header_map.items():
            row[key] = cols.get(col_idx, "").strip()
        if row.get("material"):
            results.append(row)
    return results


def parse_markdown_table(md: str) -> List[Dict[str, str]]:
    """解析 markdown 表格为结构化行"""
    lines = [l.strip() for l in md.split("\n") if l.strip()]
    if len(lines) < 2:
        return []
    # 第一行是表头
    header_line = lines[0]
    headers = [h.strip() for h in header_line.split("|") if h.strip()]

    header_map = {}
    for i, h in enumerate(headers):
        if "材料" in h or "名称" in h:
            header_map["material"] = i
        elif "规格" in h:
            header_map["spec"] = i
        elif "单位" in h:
            header_map["unit"] = i
        elif "含税" in h:
            header_map["price_tax"] = i
        elif "除税" in h:
            header_map["price_no_tax"] = i
        elif "价格" in h or "单价" in h:
            header_map["price"] = i

    if not header_map:
        return []

    results = []
    for line in lines[2:]:
        cols = [c.strip() for c in line.split("|") if c.strip() or line.split("|")]
        # 重新对齐
        raw = line.split("|")
        cols = [c.strip() for c in raw[1:-1]] if len(raw) > 2 else [c.strip() for c in raw]
        row = {}
        for key, idx in header_map.items():
            if idx < len(cols):
                row[key] = cols[idx]
        if row.get("material"):
            results.append(row)
    return results


def clean_price(val: str) -> Optional[float]:
    """从字符串提取数字价格"""
    if not val:
        return None
    # 去掉逗号、空格、非数字字符（保留小数点）
    cleaned = re.sub(r"[^\d.\-]", "", val.replace(",", ""))
    try:
        parsed = float(cleaned) if cleaned else None
        if parsed is None:
            return None
        if abs(parsed) > MAX_REASONABLE_PRICE:
            return None
        return parsed
    except ValueError:
        return None


def normalize_material_unit(material_name: str, unit: str) -> str:
    normalized = (unit or "").strip().replace("㎡", "m²").replace("?", "")
    if normalized in {"m", "m²"} and material_name in {"中砂", "碎石", "碎石5~25", "碎石5～25", "石粉渣"}:
        return "m³"
    return normalized


def sanitize_price_record_fields(material: str, spec: str, unit: str) -> tuple[str, str, str]:
    """Clamp field lengths to schema constraints and drop invalid units."""
    clean_material = (material or "").strip()[:200]
    clean_spec = (spec or "").strip()[:200]
    clean_unit = normalize_material_unit(clean_material, unit or "")
    if clean_unit and not UNIT_TOKEN_RE.match(clean_unit):
        clean_unit = ""
    if len(clean_unit) > 20:
        clean_unit = ""
    return clean_material, clean_spec, clean_unit[:20]


def split_collapsed_unit_price(text: str, material_name: str) -> tuple[str, Optional[float], str]:
    normalized = (text or "").strip()
    if not normalized:
        return "", None, ""

    match = re.match(
        r"^(?P<unit>m³|m²|㎡|m|t|kg|个|套|组|台|块|片|工日|支|根|卷|桶|箱|件)\s*(?P<price>\d+(?:\.\d+)?)$",
        normalized,
    )
    if match:
        unit = normalize_material_unit(material_name, match.group("unit"))
        return unit, clean_price(match.group("price")), ""

    price = clean_price(normalized)
    if price is not None:
        return "", price, ""

    return "", None, normalized


def normalize_price_row(row: Dict[str, str]) -> Dict[str, str]:
    normalized = dict(row)
    material = (normalized.get("material") or "").strip()
    spec = (normalized.get("spec") or "").strip()
    unit = (normalized.get("unit") or "").strip()
    price_tax = normalized.get("price_tax", "")
    price = normalized.get("price", "")

    if not unit and not price_tax and spec:
        split_unit, split_price, split_spec = split_collapsed_unit_price(spec, material)
        if split_unit or split_price is not None:
            normalized["unit"] = split_unit
            normalized["price_tax"] = "" if split_price is None else str(split_price)
            normalized["spec"] = split_spec

    if unit and not price_tax and not price and spec and not UNIT_TOKEN_RE.match(unit):
        merged = f"{unit} {spec}".strip()
        split_unit, split_price, split_spec = split_collapsed_unit_price(merged, material)
        if split_unit or split_price is not None:
            normalized["unit"] = split_unit
            normalized["price_tax"] = "" if split_price is None else str(split_price)
            normalized["spec"] = split_spec

    normalized["unit"] = normalize_material_unit(material, normalized.get("unit", ""))
    return normalized


def is_valid_material_label(material_name: str) -> bool:
    normalized = re.sub(r"\s+", "", (material_name or ""))
    if len(normalized) < 2 or len(normalized) > 80:
        return False
    if INVALID_MATERIAL_RE.search(normalized):
        return False
    if any(token in normalized for token in MATERIAL_SKIP_TOKENS):
        return False
    if not re.search(r"[\u4e00-\u9fffA-Za-z]", normalized):
        return False
    return True


def infer_category(material_name: str) -> str:
    """从材料名推断品类"""
    name = material_name.lower()
    mapping = {
        "水泥": "水泥",
        "钢筋": "钢材",
        "钢材": "钢材",
        "混凝土": "混凝土",
        "砂石": "砂石",
        "砖": "砖瓦",
        "瓦": "砖瓦",
        "玻璃": "玻璃",
        "涂料": "涂料",
        "油漆": "涂料",
        "防水": "防水材料",
        "保温": "保温材料",
        "管材": "管材",
        "电线": "电气",
        "电缆": "电气",
        "阀门": "阀门",
        "门窗": "门窗",
        "模板": "模板",
        "脚手架": "脚手架",
    }
    for k, v in mapping.items():
        if k in name:
            return v
    return "其他"


# ---------------------------------------------------------------------------
# Core import logic
# ---------------------------------------------------------------------------

def import_ocr_file(path: Path, conn) -> int:
    """导入单个 OCR JSON 文件中的价格表格，返回导入记录数"""
    logger.info(f"Processing {path.name}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to parse {path}: {e}")
        return 0

    doc_id = data.get("document_id", path.stem)
    file_name = data.get("file_name", path.name)
    year_month = extract_year_month(file_name)
    pages = data.get("pages", [])

    records = []
    for page in pages:
        page_num = page.get("page_number", 0)
        for table in page.get("tables", []):
            rows = []
            # 优先用 cells 解析
            cells = table.get("cells", [])
            if cells:
                rows = parse_table_cells(cells)
            # fallback: markdown
            if not rows:
                md = table.get("markdown", "").strip()
                if md:
                    rows = parse_markdown_table(md)
            # fallback: html（简化提取）
            if not rows:
                html = table.get("html", "").strip()
                if html:
                    # 非常简化的 HTML 表格行提取
                    rows = _parse_html_table_simple(html)

            for row in rows:
                row = normalize_price_row(row)
                material = row.get("material", "").strip()
                if not is_valid_material_label(material):
                    logger.warning(f"  Skip suspicious material label '{material}' on page {page_num} ({path.name})")
                    continue
                spec = row.get("spec", "").strip()
                unit = row.get("unit", "").strip()
                material, spec, unit = sanitize_price_record_fields(material, spec, unit)
                if not material:
                    continue
                price_tax = clean_price(row.get("price_tax", ""))
                price_no_tax = clean_price(row.get("price_no_tax", ""))
                if price_tax is None:
                    price_tax = clean_price(row.get("price", ""))

                embedding_text = f"{material} {spec}".strip()
                embedding = get_embedding(embedding_text) if embedding_text else None

                records.append((
                    doc_id, file_name, material, spec, unit,
                    price_tax, price_no_tax, "深圳", year_month,
                    page_num, infer_category(material),
                    json.dumps({"source": "ocr_table"}),
                    embedding,
                ))

    if not records:
        logger.info(f"  No price records found in {path.name}")
        return 0

    # Batch insert
    try:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO price_records
                (doc_id, file_name, material_name, specification, unit,
                 price_tax_included, price_tax_excluded, region, year_month,
                 page_number, category, metadata, embedding)
                VALUES %s
                ON CONFLICT DO NOTHING
                """,
                records,
                template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)",
            )
            conn.commit()
        logger.info(f"  ✅ Imported {len(records)} price records from {path.name}")
        return len(records)
    except Exception as e:
        conn.rollback()
        logger.warning(f"  ⚠ Batch insert failed for {path.name}, fallback to row-by-row: {e}")
        inserted = 0
        with conn.cursor() as cur:
            for rec in records:
                try:
                    cur.execute(
                        """
                        INSERT INTO price_records
                        (doc_id, file_name, material_name, specification, unit,
                         price_tax_included, price_tax_excluded, region, year_month,
                         page_number, category, metadata, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                        ON CONFLICT DO NOTHING
                        """,
                        rec,
                    )
                    if cur.rowcount > 0:
                        inserted += 1
                except Exception as row_exc:
                    conn.rollback()
                    logger.warning(f"  Skip invalid row for {path.name}: {row_exc}")
                else:
                    conn.commit()
        logger.info(f"  ✅ Imported {inserted} price records from {path.name} (row fallback)")
        return inserted


def _parse_html_table_simple(html: str) -> List[Dict[str, str]]:
    """非常简化的 HTML 表格行提取"""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            return []
        rows = []
        for tr in table.find_all("tr")[1:]:
            tds = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(tds) >= 3:
                rows.append({"material": tds[0], "spec": tds[1] if len(tds) > 1 else "", "unit": tds[2] if len(tds) > 2 else "", "price_tax": tds[-1] if len(tds) > 3 else ""})
        return rows
    except Exception:
        return []


def find_ocr_files() -> List[Path]:
    """收集所有 OCR JSON 文件（去重）"""
    files = set()
    for d in [OCR_DIR, KB_DIR]:
        if not d.exists():
            continue
        for f in d.rglob("*_ocr.json"):
            files.add(f)
        for f in d.rglob("*.json"):
            if f.name in ("processing_summary.json", "processed_documents.log"):
                continue
            if "_ocr" in f.name or "chunk" not in f.name.lower():
                files.add(f)
    return sorted(files)


def main():
    conn = get_pg_conn()
    files = find_ocr_files()
    logger.info(f"Found {len(files)} OCR files to process")

    total = 0
    for f in files:
        try:
            total += import_ocr_file(f, conn)
        except Exception as e:
            logger.error(f"Failed to import {f}: {e}")

    logger.info(f"=== Total imported: {total} price records ===")
    conn.close()


if __name__ == "__main__":
    main()

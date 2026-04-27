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
from psycopg2 import sql as pgsql

from src.database.scripts.ocr_output_reconciliation import build_ocr_source_candidate_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OCR_DIR = Path(os.environ.get("OCR_OUTPUT_DIR", project_root / "data" / "ocr_outputs"))
KB_DIR = Path(os.environ.get("KB_DIR", project_root / "data" / "knowledge_base" / "documents"))
INCLUDE_LEGACY_KB_OCR = os.environ.get("INCLUDE_LEGACY_KB_OCR", "").lower() in {"1", "true", "yes"}
_SKIP_OCR_FILENAMES = {"processing_summary.json", "processed_documents.log", "_scan_state.json"}

PG_CONFIG = {
    "host": os.environ.get("PG_HOST", "localhost"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "database": os.environ.get("PG_DB", "rag_db"),
    "user": os.environ.get("PG_USER", "rag_user"),
    "password": os.environ.get("PG_PASSWORD", "rag_password"),
}

# Embedding (reuse local model)
EMBEDDING_MODEL = None
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
_DOCUMENT_REGISTRY_SUPPORTED: Optional[bool] = None
_DOCUMENT_REGISTRY_KEY_COLUMN: Optional[str] = None
_REGISTRY_COUNT_COLUMNS: dict[str, bool] = {}


def _get_embedding_model():
    global EMBEDDING_MODEL
    if EMBEDDING_MODEL is not None:
        return EMBEDDING_MODEL

    import torch
    from sentence_transformers import SentenceTransformer

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for OCR price import embeddings")

    model_path = os.environ.get("EMBEDDING_MODEL", str(project_root / "models" / "BAAI" / "bge-m3"))
    logger.info(f"Loading embedding model: {model_path} [cuda]")
    EMBEDDING_MODEL = SentenceTransformer(model_path, device="cuda")
    return EMBEDDING_MODEL


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


def _has_registry_column(cur, column_name: str) -> bool:
    if column_name in _REGISTRY_COUNT_COLUMNS:
        return _REGISTRY_COUNT_COLUMNS[column_name]
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'document_registry' AND column_name = %s
        LIMIT 1
        """,
        (column_name,),
    )
    exists = cur.fetchone() is not None
    _REGISTRY_COUNT_COLUMNS[column_name] = exists
    return exists


def _get_registry_key_column(cur) -> Optional[str]:
    global _DOCUMENT_REGISTRY_SUPPORTED, _DOCUMENT_REGISTRY_KEY_COLUMN

    if _DOCUMENT_REGISTRY_SUPPORTED is False:
        return None
    if _DOCUMENT_REGISTRY_KEY_COLUMN is not None:
        return _DOCUMENT_REGISTRY_KEY_COLUMN

    for candidate in ("doc_id", "doc_code"):
        if _has_registry_column(cur, candidate):
            _DOCUMENT_REGISTRY_KEY_COLUMN = candidate
            _DOCUMENT_REGISTRY_SUPPORTED = True
            return candidate

    _DOCUMENT_REGISTRY_SUPPORTED = False
    logger.warning("document_registry upsert skipped: no doc_id/doc_code column found")
    return None


def register_document(cur, doc_id: str, file_name: str, total_pages: int) -> None:
    global _DOCUMENT_REGISTRY_SUPPORTED

    if _DOCUMENT_REGISTRY_SUPPORTED is False:
        return

    key_column = _get_registry_key_column(cur)
    if not key_column:
        return

    doc_type = "price_info" if extract_year_month(file_name) else "quota"
    cur.execute("SAVEPOINT price_register_doc")
    try:
        cur.execute(
            pgsql.SQL(
                """
                INSERT INTO document_registry ({}, file_name, doc_type, total_pages, status)
                VALUES (%s, %s, %s, %s, 'imported')
                ON CONFLICT ({}) DO UPDATE SET
                    file_name = EXCLUDED.file_name,
                    doc_type = EXCLUDED.doc_type,
                    total_pages = EXCLUDED.total_pages,
                    status = 'imported'
                """
            ).format(pgsql.Identifier(key_column), pgsql.Identifier(key_column)),
            (doc_id, file_name, doc_type, total_pages),
        )
    except Exception as exc:
        cur.execute("ROLLBACK TO SAVEPOINT price_register_doc")
        cur.execute("RELEASE SAVEPOINT price_register_doc")
        _DOCUMENT_REGISTRY_SUPPORTED = False
        logger.warning(f"document_registry upsert skipped: {exc}")
    else:
        cur.execute("RELEASE SAVEPOINT price_register_doc")
        _DOCUMENT_REGISTRY_SUPPORTED = True


def update_registry_count(cur, doc_id: str, column_name: str, table_name: str) -> None:
    global _DOCUMENT_REGISTRY_SUPPORTED

    if _DOCUMENT_REGISTRY_SUPPORTED is False or _REGISTRY_COUNT_COLUMNS.get(column_name) is False:
        return

    key_column = _get_registry_key_column(cur)
    if not key_column:
        return
    if not _has_registry_column(cur, column_name):
        return

    cur.execute(
        pgsql.SQL("SELECT COUNT(*) FROM {} WHERE doc_id = %s").format(pgsql.Identifier(table_name)),
        (doc_id,),
    )
    total = int(cur.fetchone()[0] or 0)

    cur.execute("SAVEPOINT price_update_registry_count")
    try:
        cur.execute(
            pgsql.SQL("UPDATE document_registry SET {} = %s WHERE {} = %s").format(
                pgsql.Identifier(column_name),
                pgsql.Identifier(key_column),
            ),
            (total, doc_id),
        )
    except Exception as exc:
        cur.execute("ROLLBACK TO SAVEPOINT price_update_registry_count")
        cur.execute("RELEASE SAVEPOINT price_update_registry_count")
        _REGISTRY_COUNT_COLUMNS[column_name] = False
        if _DOCUMENT_REGISTRY_SUPPORTED is not False:
            logger.warning(f"document_registry.{column_name} update skipped: {exc}")
    else:
        cur.execute("RELEASE SAVEPOINT price_update_registry_count")
        _REGISTRY_COUNT_COLUMNS[column_name] = True


def normalize_document_label(value: str) -> str:
    return re.sub(r"\s+", "", (value or "")).strip()


def score_ocr_source_candidate(path: Path, data: Dict[str, Any]) -> tuple[int, int, int, int, int, str]:
    return build_ocr_source_candidate_score(path, data, OCR_DIR)


def refresh_price_records(cur, doc_id: str, file_name: str) -> int:
    normalized_file_name = normalize_document_label(file_name)
    if normalized_file_name:
        # OCR reruns can regenerate document_id values or introduce whitespace drift
        # in file_name. Refresh by both identities so stale structured rows are removed.
        cur.execute(
            """
            DELETE FROM price_records
            WHERE doc_id = %s
               OR regexp_replace(COALESCE(file_name, ''), '\\s+', '', 'g') = %s
            """,
            (doc_id, normalized_file_name),
        )
    else:
        cur.execute("DELETE FROM price_records WHERE doc_id = %s", (doc_id,))
    return int(cur.rowcount or 0)


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
                    header_map.setdefault("material", col_idx)
                if "规格" in t:
                    header_map.setdefault("spec", col_idx)
                if "单位" in t:
                    header_map.setdefault("unit", col_idx)
                if "含税" in t:
                    header_map.setdefault("price_tax", col_idx)
                if "除税" in t:
                    header_map.setdefault("price_no_tax", col_idx)
                if "价格" in t or "单价" in t:
                    header_map.setdefault("price", col_idx)
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
        row = repair_price_row_from_cells(cols, row)
        has_price = False
        for price_key in ("price_tax", "price_no_tax", "price"):
            unit_hint, parsed_price, spec_hint = extract_structured_price(row.get(price_key, ""), row.get("material", ""))
            if parsed_price is None:
                continue
            row[price_key] = str(parsed_price)
            if unit_hint and not row.get("unit"):
                row["unit"] = unit_hint
            if spec_hint and not row.get("spec"):
                row["spec"] = spec_hint
            has_price = True
        if row.get("material") and has_price:
            results.append(row)
    return results


def strip_leading_row_index(text: str) -> str:
    stripped = (text or "").strip()
    stripped = re.sub(r'^["\'\'“”‘’!！:：;；,.，。·•\-_/\\]+', "", stripped)
    stripped = re.sub(r'^\d+\s*', "", stripped)
    return stripped.strip()


def extract_structured_price(text: str, material_name: str) -> tuple[str, Optional[float], str]:
    normalized = (text or "").strip()
    if not normalized:
        return "", None, ""

    split_unit, split_price, split_spec = split_collapsed_unit_price(normalized, material_name)
    numeric_text = re.sub(r"[^\d.]", "", normalized)
    if split_price is not None and (split_unit or "." in numeric_text):
        return split_unit, split_price, split_spec

    if "." not in numeric_text:
        return "", None, ""

    parsed = clean_price(normalized)
    if parsed is None:
        return "", None, ""
    return "", parsed, ""


def repair_price_row_from_cells(cols: Dict[int, str], row: Dict[str, str]) -> Dict[str, str]:
    repaired = dict(row)
    ordered_cols = [(col_idx, (text or "").strip()) for col_idx, text in sorted(cols.items())]
    ordered_cols = [(col_idx, text) for col_idx, text in ordered_cols if text]
    if not ordered_cols:
        return repaired

    material = (repaired.get("material") or "").strip()
    spec = (repaired.get("spec") or "").strip()
    unit = (repaired.get("unit") or "").strip()
    price_tax = (repaired.get("price_tax") or repaired.get("price") or "").strip()
    material_col = None
    price_col = None

    for col_idx, text in reversed(ordered_cols):
        split_unit, split_price, split_spec = extract_structured_price(text, material)
        if split_price is None:
            continue
        price_col = col_idx
        if not price_tax:
            repaired["price_tax"] = str(split_price)
            price_tax = repaired["price_tax"]
        if split_unit and not unit:
            repaired["unit"] = split_unit
            unit = split_unit
        if split_spec and not spec:
            repaired["spec"] = split_spec
            spec = split_spec
        break

    if not is_valid_material_label(material):
        for col_idx, text in ordered_cols:
            if col_idx == price_col:
                continue
            candidate = strip_leading_row_index(text)
            if not candidate or clean_price(candidate) is not None:
                continue
            if is_valid_material_label(candidate):
                repaired["material"] = candidate
                material = candidate
                material_col = col_idx
                break

    if material_col is None and material:
        for col_idx, text in ordered_cols:
            if strip_leading_row_index(text) == material:
                material_col = col_idx
                break

    if not spec:
        for col_idx, text in ordered_cols:
            if col_idx in {material_col, price_col}:
                continue
            candidate = strip_leading_row_index(text)
            if not candidate:
                continue
            split_unit, split_price, split_spec = extract_structured_price(candidate, material)
            if split_price is not None:
                if split_unit and not unit:
                    repaired["unit"] = split_unit
                    unit = split_unit
                if not price_tax:
                    repaired["price_tax"] = str(split_price)
                    price_tax = repaired["price_tax"]
                candidate = split_spec
            if not candidate or clean_price(candidate) is not None:
                continue
            repaired["spec"] = candidate
            break

    return repaired


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
    if UNIT_TOKEN_RE.match(normalized):
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

    try:
        with conn.cursor() as cur:
            register_document(cur, doc_id, file_name, len(pages))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.warning(f"Failed to register {path.name} in document_registry: {exc}")

    records = []
    seen_record_keys = set()
    duplicate_records_skipped = 0
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
                if price_tax is None and price_no_tax is None:
                    continue

                embedding_text = f"{material} {spec}".strip()
                embedding = get_embedding(embedding_text) if embedding_text else None

                record_key = (page_num, material, spec, unit, price_tax, price_no_tax)
                if record_key in seen_record_keys:
                    duplicate_records_skipped += 1
                    continue
                seen_record_keys.add(record_key)

                records.append((
                    doc_id, file_name, material, spec, unit,
                    price_tax, price_no_tax, "深圳", year_month,
                    page_num, infer_category(material),
                    json.dumps({"source": "ocr_table"}),
                    embedding,
                ))

    if not records:
        try:
            with conn.cursor() as cur:
                deleted = refresh_price_records(cur, doc_id, file_name)
                update_registry_count(cur, doc_id, "price_record_count", "price_records")
            conn.commit()
            logger.info(f"  No price records found in {path.name}; cleared {deleted} existing rows")
        except Exception as e:
            conn.rollback()
            logger.warning(f"  Failed to refresh empty price rows for {path.name}: {e}")
        return 0

    # Batch insert
    try:
        with conn.cursor() as cur:
            deleted = refresh_price_records(cur, doc_id, file_name)
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
            update_registry_count(cur, doc_id, "price_record_count", "price_records")
            conn.commit()
        details = []
        if deleted:
            details.append(f"replaced {deleted} existing rows")
        if duplicate_records_skipped:
            details.append(f"skipped {duplicate_records_skipped} duplicate rows")
        detail_suffix = f" ({'; '.join(details)})" if details else ""
        logger.info(
            f"  ✅ Refreshed {len(records)} price records from {path.name}{detail_suffix}"
        )
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
        try:
            with conn.cursor() as cur:
                update_registry_count(cur, doc_id, "price_record_count", "price_records")
            conn.commit()
        except Exception as count_exc:
            conn.rollback()
            logger.warning(f"  Failed to update document_registry count for {path.name}: {count_exc}")
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
    files_by_identity: Dict[str, tuple[tuple[int, int, int, int, str], Path]] = {}
    scan_dirs = [OCR_DIR]
    if INCLUDE_LEGACY_KB_OCR:
        scan_dirs.append(KB_DIR)
    for d in scan_dirs:
        if not d.exists():
            continue
        for f in sorted(d.rglob("*.json")):
            if f.name in _SKIP_OCR_FILENAMES or "chunk" in f.name.lower():
                continue
            try:
                with open(f, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except Exception:
                continue
            if not isinstance(data.get("pages"), list):
                continue
            file_name = str(data.get("file_name") or f.name)
            source_identity = normalize_document_label(file_name) or normalize_document_label(f.stem) or str(f)
            candidate = (score_ocr_source_candidate(f, data), f)
            current = files_by_identity.get(source_identity)
            if current is None or candidate[0] > current[0]:
                files_by_identity[source_identity] = candidate
    return sorted(path for _, path in files_by_identity.values())


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

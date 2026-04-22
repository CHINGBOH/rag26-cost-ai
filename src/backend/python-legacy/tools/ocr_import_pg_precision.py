#!/usr/bin/env python3
"""
OCR 数据精准导入 PostgreSQL
- 文字入 text_chunks（含 embedding + tsvector）
- 价格表格入 price_records（含 embedding）
- 通过 documents.id 关联
"""

import os
import sys
import json
import re
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

import psycopg2
from psycopg2.extras import execute_values

import torch
from transformers import AutoTokenizer, AutoModel
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

OCR_DIR = Path("/home/l/rag-dashboard/data/ocr_outputs")
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "rag_db",
    "user": "rag_user",
    "password": "your_password_here",
}

# Embedding model (global)
TOKENIZER = None
MODEL = None
DEVICE = "cpu"


def init_embedding_model():
    global TOKENIZER, MODEL, DEVICE
    if MODEL is not None:
        return
    model_path = "/home/l/rag-dashboard/models/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181"
    logger.info("Loading embedding model: BAAI/bge-m3 ...")
    TOKENIZER = AutoTokenizer.from_pretrained(model_path)
    MODEL = AutoModel.from_pretrained(model_path)
    MODEL.eval()
    if torch.cuda.is_available():
        DEVICE = "cuda"
        MODEL = MODEL.to(DEVICE)
    logger.info(f"Model loaded on {DEVICE}")


def encode_texts(texts: List[str], batch_size: int = 16) -> np.ndarray:
    """Mean pooling + normalize"""
    if MODEL is None:
        init_embedding_model()
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        inputs = TOKENIZER(batch, return_tensors="pt", padding=True, truncation=True, max_length=512)
        if DEVICE != "cpu":
            inputs = {k: v.to(DEVICE) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = MODEL(**inputs)
            attention_mask = inputs["attention_mask"]
            last_hidden = outputs.last_hidden_state
            mask_expanded = attention_mask.unsqueeze(-1).expand(last_hidden.size()).float()
            sum_embeddings = torch.sum(last_hidden * mask_expanded, 1)
            sum_mask = torch.clamp(mask_expanded.sum(1), min=1e-9)
            embeddings = sum_embeddings / sum_mask
            embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
        all_embeddings.append(embeddings.cpu().numpy())
    return np.vstack(all_embeddings)


def classify_doc_type(file_name: str) -> str:
    fname = file_name.lower()
    price_keywords = ["信息价", "价格信息", "造价信息", "价格", "费率", "计价"]
    if any(k in fname for k in price_keywords):
        return "price"
    standard_keywords = ["标准", "规范", "规程", "指南", "划分", "体系"]
    if any(k in fname for k in standard_keywords):
        return "standard"
    return "general"


def extract_period(file_name: str) -> str:
    m = re.search(r"(\d{4})[-_]?(\d{1,2})", file_name)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}"
    m = re.search(r"(\d{4})年(\d{1,2})月", file_name)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}"
    return ""


def get_ocr_files() -> List[Path]:
    """获取所有 OCR JSON 文件，chunk 文件与 merged 文件去重"""
    all_json = sorted(OCR_DIR.glob("*.json"))
    # 优先使用 merged，其次主文件，最后 chunk
    merged = {f.stem.replace("_merged_ocr", ""): f for f in all_json if "_merged_" in f.name}
    chunks = {f.stem.replace("_chunk_", ""): f for f in all_json if "_chunk_" in f.name}
    main_files = {}
    for f in all_json:
        name = f.stem
        if "_merged_" in name or "_chunk_" in name:
            continue
        # 去掉 _ocr 后缀作为 key
        key = name.replace("_ocr", "").replace(".json", "")
        main_files[key] = f

    selected = {}
    for key in set(list(merged.keys()) + list(main_files.keys()) + list(chunks.keys())):
        if key in merged:
            selected[key] = merged[key]
        elif key in main_files:
            selected[key] = main_files[key]
        elif key in chunks:
            selected[key] = chunks[key]

    return list(selected.values())


def chunk_page_text(
    page_number: int,
    text_blocks: List[Dict],
    max_chunk_size: int = 800,
    overlap: int = 100,
) -> List[Dict]:
    """对单页 text_blocks 进行语义分块，不跨页"""
    # 按 bbox y 坐标排序（从上到下）
    blocks = sorted(text_blocks, key=lambda b: b.get("bbox", {}).get("y", 0))
    lines = []
    for b in blocks:
        text = b.get("text", "").strip()
        if text:
            lines.append({
                "text": text,
                "confidence": b.get("confidence", 1.0),
                "bbox": b.get("bbox", {}),
            })

    if not lines:
        return []

    # 拼接为段落（用换行符分隔）
    full_text = "\n".join(l["text"] for l in lines)
    if len(full_text) <= max_chunk_size:
        return [{
            "content": full_text,
            "page_number": page_number,
            "metadata": {
                "line_count": len(lines),
                "avg_confidence": round(sum(l["confidence"] for l in lines) / len(lines), 4),
                "bbox_list": [l["bbox"] for l in lines],
            }
        }]

    # 滑动窗口切分（优先在换行处切分）
    chunks = []
    start = 0
    while start < len(full_text):
        end = min(start + max_chunk_size, len(full_text))
        if end < len(full_text):
            # 尝试在最近的换行处切分
            nl_pos = full_text.rfind("\n", start, end)
            if nl_pos > start + max_chunk_size // 2:
                end = nl_pos + 1
        chunk_text = full_text[start:end].strip()
        if chunk_text:
            chunks.append({
                "content": chunk_text,
                "page_number": page_number,
                "metadata": {
                    "char_start": start,
                    "char_end": end,
                }
            })
        start = max(start + 1, end - overlap)

    return chunks


def parse_price_table(cells: List[Dict]) -> List[Dict]:
    """从不规则的 OCR 表格 cells 中提取价格记录"""
    # 按行分组
    rows = defaultdict(list)
    for c in cells:
        rows[c.get("row", 0)].append(c)

    records = []
    for row_idx in sorted(rows.keys()):
        row_cells = sorted(rows[row_idx], key=lambda x: x.get("col", 0))
        texts = [c.get("text", "").strip() for c in row_cells]

        # 跳过表头/空行
        if any(k in "".join(texts) for k in ["序号", "材料名称", "型号", "规格", "单位", "价格", "造价信息", "SZCOST"]):
            continue
        if not any(texts):
            continue

        # 提取材料名称和规格（通常在 col 0-2）
        material_name = ""
        spec = ""
        for t in texts[:3]:
            # 去除序号前缀
            t_clean = re.sub(r"^\d+\s*[,，]?\s*", "", t).strip()
            if t_clean and not material_name:
                material_name = t_clean
            elif t_clean and not spec:
                spec = t_clean

        # 提取单位和价格（通常在 col 3+）
        unit = ""
        price = None
        for t in texts[3:]:
            # 匹配 "单位 价格" 或 "价格" 格式
            m = re.search(r"([\w/·³²㎡℃%°\.]+)\s+(\d+[\d,]*\.?\d*)", t)
            if m:
                unit = m.group(1).strip()
                price_str = m.group(2).replace(",", "")
                try:
                    price = float(price_str)
                except ValueError:
                    pass
            else:
                # 单独匹配价格数字
                m2 = re.search(r"(\d+[\d,]*\.?\d*)", t)
                if m2 and price is None:
                    try:
                        price = float(m2.group(1).replace(",", ""))
                    except ValueError:
                        pass
                # 单独匹配单位
                if not unit:
                    units = re.findall(r"[t m³ kg ㎡ 工日 个 套 组 台 套 件 块 片 m² ·/]", t)
                    if units:
                        unit = "".join(units).strip()

        if material_name and price is not None and price > 0:
            records.append({
                "material_name": material_name,
                "spec": spec,
                "unit": unit,
                "price": price,
            })

    return records


def process_file(conn, ocr_file: Path, doc_type: str, period: str):
    """处理单个 OCR 文件，返回统计"""
    with open(ocr_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    file_name = data.get("file_name", ocr_file.name)
    total_pages = len(data.get("pages", []))

    # 1. 插入 documents，获取自增 id
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (file_name, doc_type, period, total_pages, status, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            RETURNING id
            """,
            (file_name, doc_type, period, total_pages, "imported"),
        )
        document_id = cur.fetchone()[0]

    # 2. 提取文本 chunks
    all_chunks = []
    all_price_records = []

    for page in data.get("pages", []):
        page_number = page.get("page_number", 1)

        # 2a. text_chunks
        text_blocks = page.get("text_blocks", [])
        if text_blocks:
            chunks = chunk_page_text(page_number, text_blocks)
            for idx, c in enumerate(chunks):
                all_chunks.append({
                    "document_id": document_id,
                    "chunk_index": idx,
                    "content": c["content"],
                    "page_number": c["page_number"],
                    "period": period,
                    "doc_type": doc_type,
                })

        # 2b. price_records（仅 price 类型文档）
        if doc_type == "price":
            for table in page.get("tables", []):
                records = parse_price_table(table.get("cells", []))
                for r in records:
                    r["document_id"] = document_id
                    r["period"] = period
                    r["page_number"] = page_number
                    r["source_row"] = json.dumps(r, ensure_ascii=False)
                    all_price_records.append(r)

    # 3. 生成 embeddings 并插入 text_chunks
    if all_chunks:
        texts = [c["content"] for c in all_chunks]
        embeddings = encode_texts(texts, batch_size=16)

        chunk_data = []
        for c, emb in zip(all_chunks, embeddings):
            chunk_data.append((
                c["document_id"], c["chunk_index"], c["content"],
                c["page_number"], c["period"], c["doc_type"],
                emb.tolist(),
            ))

        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO text_chunks
                (document_id, chunk_index, content, page_number, period, doc_type, embedding)
                VALUES %s
                """,
                chunk_data,
                template="(%s, %s, %s, %s, %s, %s, %s::vector)",
            )

    # 4. 生成 embeddings 并插入 price_records
    if all_price_records:
        texts = [f"{r['material_name']} {r['spec']}".strip() for r in all_price_records]
        embeddings = encode_texts(texts, batch_size=16)

        price_data = []
        for r, emb in zip(all_price_records, embeddings):
            price_data.append((
                r["document_id"], r["period"], r.get("category", ""),
                r["material_name"], r["spec"], r["unit"],
                r["price"], r["page_number"], r["source_row"],
                emb.tolist(),
            ))

        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO price_records
                (document_id, period, category, material_name, spec, unit, price, page_number, source_row, embedding)
                VALUES %s
                """,
                price_data,
                template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)",
            )

    conn.commit()
    return {
        "document_id": document_id,
        "chunks": len(all_chunks),
        "price_records": len(all_price_records),
    }


def main():
    init_embedding_model()

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False

    files = get_ocr_files()
    logger.info(f"Total OCR files to import: {len(files)}")

    total_docs = 0
    total_chunks = 0
    total_prices = 0

    for i, ocr_file in enumerate(files, 1):
        doc_type = classify_doc_type(ocr_file.name)
        period = extract_period(ocr_file.name)
        logger.info(f"[{i}/{len(files)}] {ocr_file.name} | type={doc_type} | period={period}")

        try:
            stats = process_file(conn, ocr_file, doc_type, period)
            total_docs += 1
            total_chunks += stats["chunks"]
            total_prices += stats["price_records"]
            logger.info(f"  -> doc_id={stats['document_id']}, chunks={stats['chunks']}, prices={stats['price_records']}")
        except Exception as e:
            conn.rollback()
            logger.error(f"  FAILED: {e}", exc_info=True)

    conn.close()

    logger.info("=" * 60)
    logger.info("Import complete!")
    logger.info(f"Documents: {total_docs}")
    logger.info(f"Text chunks: {total_chunks}")
    logger.info(f"Price records: {total_prices}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

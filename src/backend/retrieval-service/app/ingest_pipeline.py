"""Issue #69 Phase A: ingest pipeline backed by PG state.

Extractors output a uniform Block contract:
    {doc_id, page, block_id, type, text, bbox?, metadata}

State machine:
    queued -> extracting -> chunking -> embedding -> indexing -> done
                                                              \-> failed

Topology principle: workers are stateless; PG ingest_jobs + ingest_write_log
are the source of truth. Killing/restarting the process must not cause
duplicate writes (write_log PK guards each phase write).
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("ingest_pipeline")


# ────────────────────────────── Block contract ──────────────────────────────
@dataclass
class Block:
    doc_id: str
    page: int
    block_id: str
    type: str           # text | table | figure | caption
    text: str
    bbox: tuple | None = None
    metadata: dict = field(default_factory=dict)


# ────────────────────────────── PG helpers ──────────────────────────────
def _conn():
    from app.agent.tools import _get_pg_conn
    return _get_pg_conn()


def _release(conn):
    from app.agent.tools import _put_pg_conn
    _put_pg_conn(conn)


def job_create(file_name: str, file_path: str, file_size: int, mime: str) -> str:
    job_id = uuid.uuid4().hex[:16]
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingest_jobs
                  (job_id, doc_id, file_name, file_path, file_size, mime, status, phase)
                VALUES (%s, %s, %s, %s, %s, %s, 'queued', 'queued')
                """,
                (job_id, job_id, file_name, file_path, file_size, mime),
            )
        conn.commit()
    finally:
        _release(conn)
    return job_id


def job_update(job_id: str, **fields) -> None:
    if not fields:
        return
    cols = list(fields.keys())
    vals = list(fields.values())
    sets = ", ".join(f"{c} = %s" for c in cols)
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE ingest_jobs SET {sets} WHERE job_id = %s", vals + [job_id])
        conn.commit()
    finally:
        _release(conn)


def job_get(job_id: str) -> dict | None:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT job_id, doc_id, file_name, file_path, file_size, mime, status,
                          phase, progress_pct, error, blocks_total, chunks_pg,
                          vectors_qdrant, triples_neo4j, ocr_pages, text_chars,
                          extractor, duration_ms, created_at, updated_at,
                          started_at, finished_at, metadata
                   FROM ingest_jobs WHERE job_id = %s""",
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
    finally:
        _release(conn)


def job_list(limit: int = 50, status: str | None = None) -> list[dict]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            if status:
                cur.execute(
                    """SELECT job_id, doc_id, file_name, file_size, mime, status, phase,
                              progress_pct, blocks_total, chunks_pg, vectors_qdrant,
                              extractor, duration_ms, created_at, updated_at, error
                       FROM ingest_jobs WHERE status = %s
                       ORDER BY created_at DESC LIMIT %s""",
                    (status, limit),
                )
            else:
                cur.execute(
                    """SELECT job_id, doc_id, file_name, file_size, mime, status, phase,
                              progress_pct, blocks_total, chunks_pg, vectors_qdrant,
                              extractor, duration_ms, created_at, updated_at, error
                       FROM ingest_jobs
                       ORDER BY created_at DESC LIMIT %s""",
                    (limit,),
                )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        _release(conn)


def write_log_has(job_id: str, phase: str, key: str) -> bool:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM ingest_write_log WHERE job_id=%s AND phase=%s AND key=%s",
                (job_id, phase, key),
            )
            return cur.fetchone() is not None
    finally:
        _release(conn)


def write_log_put(job_id: str, phase: str, key: str) -> None:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ingest_write_log (job_id, phase, key)
                   VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                (job_id, phase, key),
            )
        conn.commit()
    finally:
        _release(conn)


# ────────────────────────────── extractors ──────────────────────────────
def extract_text_file(path: Path, doc_id: str) -> tuple[list[Block], str]:
    """Plain .txt / .md — one block per non-empty paragraph."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    blocks: list[Block] = []
    for i, para in enumerate(p.strip() for p in text.split("\n\n")):
        if para:
            blocks.append(Block(doc_id=doc_id, page=1, block_id=f"p1_b{i}",
                                type="text", text=para))
    return blocks, "text"


def extract_csv(path: Path, doc_id: str) -> tuple[list[Block], str]:
    """CSV — one Block per row, plus a header summary block."""
    import csv
    blocks: list[Block] = []
    rows: list[list[str]] = []
    with open(path, newline="", encoding="utf-8", errors="ignore") as fh:
        # try utf-8-sig in case of BOM
        try:
            reader = csv.reader(fh)
            for row in reader:
                rows.append([(c or "").strip() for c in row])
        except Exception as e:
            raise RuntimeError(f"csv parse failed: {e}")

    if not rows:
        return [], "csv"

    header = rows[0]
    blocks.append(Block(
        doc_id=doc_id, page=1, block_id="hdr",
        type="caption", text="表头: " + " | ".join(header),
        metadata={"row": 0, "header": header},
    ))
    for ri, row in enumerate(rows[1:], start=1):
        if not any(row):
            continue
        # render as "key: val | key: val" for embedding-friendliness
        cells = [f"{header[i] if i < len(header) else f'col{i}'}: {v}"
                 for i, v in enumerate(row) if v]
        blocks.append(Block(
            doc_id=doc_id, page=1, block_id=f"row{ri}",
            type="table_row", text=" | ".join(cells),
            metadata={"row": ri},
        ))
    return blocks, "csv"


def extract_xlsx(path: Path, doc_id: str) -> tuple[list[Block], str]:
    """Excel — each sheet → caption block + one table_row block per data row."""
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    blocks: list[Block] = []
    page = 0
    try:
        for sname in wb.sheetnames:
            page += 1
            ws = wb[sname]
            rows_iter = ws.iter_rows(values_only=True)
            try:
                header_raw = next(rows_iter)
            except StopIteration:
                continue
            header = [str(c) if c is not None else "" for c in header_raw]
            blocks.append(Block(
                doc_id=doc_id, page=page, block_id=f"sheet{page}_hdr",
                type="caption", text=f"工作表 [{sname}] 表头: " + " | ".join(h for h in header if h),
                metadata={"sheet": sname, "row": 0, "header": header},
            ))
            for ri, row in enumerate(rows_iter, start=1):
                cells_raw = [("" if v is None else str(v)).strip() for v in row]
                if not any(cells_raw):
                    continue
                cells = [f"{header[i] if i < len(header) else f'col{i}'}: {v}"
                         for i, v in enumerate(cells_raw) if v]
                if not cells:
                    continue
                blocks.append(Block(
                    doc_id=doc_id, page=page, block_id=f"sheet{page}_r{ri}",
                    type="table_row", text=" | ".join(cells),
                    metadata={"sheet": sname, "row": ri},
                ))
    finally:
        wb.close()
    return blocks, "xlsx"


def _extract_pdf_tables(path: Path, doc_id: str) -> list[Block]:
    """pdfplumber-based table extraction; merges per page, robust to failures."""
    blocks: list[Block] = []
    try:
        import pdfplumber
    except Exception:
        return blocks
    try:
        with pdfplumber.open(str(path)) as pdf:
            for pi, page in enumerate(pdf.pages, start=1):
                try:
                    tables = page.extract_tables() or []
                except Exception:
                    continue
                for ti, tbl in enumerate(tables):
                    if not tbl or not any(any(c for c in r) for r in tbl):
                        continue
                    header = [str(c or "").strip() for c in tbl[0]]
                    blocks.append(Block(
                        doc_id=doc_id, page=pi,
                        block_id=f"p{pi}_t{ti}_hdr",
                        type="caption",
                        text=f"表 {pi}-{ti+1} 表头: " + " | ".join(h for h in header if h),
                        metadata={"table": ti, "row": 0, "header": header},
                    ))
                    for ri, row in enumerate(tbl[1:], start=1):
                        cells_raw = [str(c or "").strip() for c in row]
                        if not any(cells_raw):
                            continue
                        cells = [f"{header[i] if i < len(header) else f'col{i}'}: {v}"
                                 for i, v in enumerate(cells_raw) if v]
                        if not cells:
                            continue
                        blocks.append(Block(
                            doc_id=doc_id, page=pi,
                            block_id=f"p{pi}_t{ti}_r{ri}",
                            type="table_row",
                            text=" | ".join(cells),
                            metadata={"table": ti, "row": ri},
                        ))
    except Exception as e:
        logger.warning("pdfplumber table extraction failed: %s", e)
    return blocks


def extract_pdf_native(path: Path, doc_id: str) -> tuple[list[Block], str] | None:
    """Try PyMuPDF first; if pages have very little text, signal caller to OCR.

    Streams page-by-page so 905M files don't blow up memory.
    Also pulls native tables via pdfplumber and merges into the block stream
    (sorted by page, with text first, then tables — chunker preserves order).
    """
    try:
        import fitz  # PyMuPDF
    except Exception:
        return None
    blocks: list[Block] = []
    total_text_chars = 0
    n_pages = 0
    try:
        with fitz.open(str(path)) as doc:
            n_pages = doc.page_count
            for pi in range(n_pages):
                page = doc.load_page(pi)
                txt = page.get_text("text") or ""
                total_text_chars += len(txt)
                for bi, para in enumerate(p.strip() for p in txt.split("\n\n")):
                    if para and len(para) > 4:
                        blocks.append(Block(
                            doc_id=doc_id, page=pi + 1,
                            block_id=f"p{pi+1}_b{bi}",
                            type="text", text=para,
                        ))
    except Exception as e:
        logger.warning("pymupdf failed: %s", e)
        return None
    if not blocks or (total_text_chars / max(1, n_pages)) < 30:
        return None  # signal scan / needs OCR

    # native PDF: also try to pull tables (best-effort, never fatal)
    try:
        tbl_blocks = _extract_pdf_tables(path, doc_id)
        if tbl_blocks:
            blocks.extend(tbl_blocks)
            blocks.sort(key=lambda b: (b.page, 0 if b.type == "text" else 1))
            logger.info("pdfplumber added %d table blocks", len(tbl_blocks))
    except Exception as e:
        logger.warning("table extraction skipped: %s", e)

    return blocks, "pymupdf"


async def extract_pdf_or_image_via_ocr(path: Path, doc_id: str, file_name: str) -> tuple[list[Block], str]:
    import httpx
    ocr_url = os.environ.get("OCR_SERVICE_URL", "http://localhost:8001")
    suffix = path.suffix.lower()
    endpoint = "/ocr/pdf" if suffix == ".pdf" else "/ocr/image"
    blocks: list[Block] = []
    pages_seen = 0
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            with open(path, "rb") as fh:
                r = await client.post(
                    f"{ocr_url}{endpoint}",
                    files={"file": (file_name, fh)},
                )
        if r.status_code != 200:
            raise RuntimeError(f"OCR HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        pages = data.get("pages") or []
        pages_seen = len(pages)
        for pi, p in enumerate(pages):
            txt = p.get("text") or p.get("ocr_text") or ""
            page_no = p.get("page") or (pi + 1)
            for bi, para in enumerate(s.strip() for s in txt.split("\n\n")):
                if para and len(para) > 4:
                    blocks.append(Block(
                        doc_id=doc_id, page=page_no,
                        block_id=f"p{page_no}_b{bi}",
                        type="text", text=para,
                        metadata={"ocr": True},
                    ))
    except Exception as e:
        raise RuntimeError(f"ocr extract failed: {e}")
    return blocks, "ocr_paddle"


# ────────────────────────────── chunking ──────────────────────────────
def chunk_blocks(blocks: list[Block], max_chars: int = 400) -> list[Block]:
    """Page-aware chunker.

    - text blocks: merged within page until max_chars.
    - table_row / caption / figure: kept as their own chunk so retrieval
      can pinpoint a row without diluting the embedding.
    """
    out: list[Block] = []
    cur_buf: list[str] = []
    cur_page = -1
    cur_doc_id = ""

    def flush():
        nonlocal cur_buf, cur_page, cur_doc_id
        if cur_buf:
            txt = "\n\n".join(cur_buf)
            out.append(Block(
                doc_id=cur_doc_id, page=cur_page,
                block_id=f"chunk_{len(out)}",
                type="text", text=txt,
            ))
            cur_buf = []

    for b in blocks:
        cur_doc_id = b.doc_id
        # non-text blocks: emit as-is, bypass buffer
        if b.type != "text":
            flush()
            out.append(Block(
                doc_id=b.doc_id, page=b.page,
                block_id=f"chunk_{len(out)}",
                type=b.type, text=b.text,
                metadata=b.metadata,
            ))
            cur_page = b.page
            continue
        if b.page != cur_page:
            flush()
            cur_page = b.page
        if not cur_buf:
            cur_buf.append(b.text)
        elif sum(len(x) for x in cur_buf) + len(b.text) + 2 <= max_chars:
            cur_buf.append(b.text)
        else:
            flush()
            cur_page = b.page
            if len(b.text) <= max_chars:
                cur_buf = [b.text]
            else:
                for k in range(0, len(b.text), max_chars):
                    out.append(Block(
                        doc_id=b.doc_id, page=b.page,
                        block_id=f"chunk_{len(out)}",
                        type="text", text=b.text[k:k + max_chars],
                    ))
                cur_buf = []
    flush()
    return out


# ────────────────────────────── ingest write ──────────────────────────────
def write_chunks_to_pg(job_id: str, doc_id: str, file_name: str,
                       chunks: list[Block]) -> tuple[int, int]:
    """Returns (inserted_pg, embedded_count). Idempotent via write_log."""
    from app.agent.tools import _get_embedding_svc
    emb = _get_embedding_svc()
    inserted = 0
    embedded = 0
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO document_registry
                       (doc_id, file_name, total_pages, status, text_chunk_count, imported_at)
                   VALUES (%s, %s, %s, 'ingesting', %s, NOW())
                   ON CONFLICT (doc_id) DO UPDATE
                     SET text_chunk_count = EXCLUDED.text_chunk_count,
                         status = 'ingesting'""",
                (doc_id, file_name,
                 max((c.page for c in chunks), default=1),
                 len(chunks)),
            )
            conn.commit()

            for i, c in enumerate(chunks):
                key = str(i)
                if write_log_has(job_id, "pg_chunk", key):
                    inserted += 1
                    embedded += 1
                    continue
                try:
                    vec = emb.encode(c.text)
                    vec_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)
                    embedded += 1
                except Exception as ee:
                    logger.warning("embed failed chunk %s: %s", i, ee)
                    vec_list = None

                try:
                    cur.execute(
                        """INSERT INTO text_chunks
                             (doc_id, file_name, chunk_index, content, page_number,
                              section, metadata, embedding, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, NOW())
                           ON CONFLICT (doc_id, file_name, chunk_index) DO UPDATE
                             SET content = EXCLUDED.content,
                                 page_number = EXCLUDED.page_number,
                                 embedding = COALESCE(EXCLUDED.embedding, text_chunks.embedding),
                                 metadata = EXCLUDED.metadata""",
                        (doc_id, file_name, i, c.text, c.page, "",
                         json.dumps({**c.metadata, "job_id": job_id,
                                     "block_type": c.type}, ensure_ascii=False),
                         vec_list),
                    )
                    conn.commit()
                    write_log_put(job_id, "pg_chunk", key)
                    inserted += 1
                except Exception as ce:
                    conn.rollback()
                    logger.warning("pg insert failed chunk %s: %s", i, ce)

            cur.execute(
                "UPDATE document_registry SET status='ready' WHERE doc_id=%s",
                (doc_id,),
            )
            conn.commit()
    finally:
        _release(conn)
    return inserted, embedded


# ────────────────────────────── orchestrator ──────────────────────────────
async def run_ingest_job(job_id: str) -> None:
    started = time.time()
    job = job_get(job_id)
    if not job:
        logger.error("job %s not found", job_id)
        return
    file_path = Path(job["file_path"])
    file_name = job["file_name"]
    suffix = file_path.suffix.lower()
    doc_id = job["doc_id"] or job_id

    job_update(job_id, status="extracting", phase="extract", progress_pct=10,
               started_at=time.strftime("%Y-%m-%d %H:%M:%S"))

    try:
        # 1) extract
        blocks: list[Block] = []
        extractor = ""
        if suffix in (".txt", ".md"):
            blocks, extractor = extract_text_file(file_path, doc_id)
        elif suffix == ".csv":
            blocks, extractor = extract_csv(file_path, doc_id)
        elif suffix in (".xlsx", ".xlsm"):
            blocks, extractor = extract_xlsx(file_path, doc_id)
        elif suffix == ".pdf":
            res = extract_pdf_native(file_path, doc_id)
            if res:
                blocks, extractor = res
            else:
                # scanned PDF → OCR
                blocks, extractor = await extract_pdf_or_image_via_ocr(file_path, doc_id, file_name)
        elif suffix in (".png", ".jpg", ".jpeg"):
            blocks, extractor = await extract_pdf_or_image_via_ocr(file_path, doc_id, file_name)
        else:
            raise RuntimeError(f"unsupported extension: {suffix}")

        text_chars = sum(len(b.text) for b in blocks)
        job_update(job_id, blocks_total=len(blocks), text_chars=text_chars,
                   extractor=extractor, phase="chunk", progress_pct=40)

        if not blocks:
            raise RuntimeError("extractor produced 0 blocks")

        # 2) chunk
        chunks = chunk_blocks(blocks, max_chars=400)
        job_update(job_id, phase="embed", progress_pct=60)

        # 3) write to PG (with embedding) — idempotent
        inserted, embedded = write_chunks_to_pg(job_id, doc_id, file_name, chunks)
        job_update(job_id, chunks_pg=inserted, vectors_qdrant=embedded,
                   phase="index", progress_pct=90)

        # 4) finalize
        duration_ms = int((time.time() - started) * 1000)
        job_update(job_id, status="done", phase="done", progress_pct=100,
                   duration_ms=duration_ms,
                   finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        logger.info("job %s done: extractor=%s blocks=%d chunks=%d ms=%d",
                    job_id, extractor, len(blocks), inserted, duration_ms)

    except Exception as e:
        duration_ms = int((time.time() - started) * 1000)
        job_update(job_id, status="failed", phase="error",
                   error=str(e)[:1000], duration_ms=duration_ms,
                   finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        logger.exception("job %s failed: %s", job_id, e)

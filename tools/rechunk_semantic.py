"""
rechunk_semantic.py — Semantic rechunking for engineering standard documents.

Strategy:
  1. Convert per-page OCR markdown → structured markdown with # headers
     based on section numbers (10.2.6 → ### 10.2.6 ...).
     List-item numbers (1, 2, 3 without dots) are NOT treated as headers.
  2. Detect section number gaps (e.g., 10.2.5 → 10.2.7) and inject missing
     titles by cross-referencing the 子目构成表 (10.3.x) and 说明 (10.1.x).
  3. MarkdownHeaderTextSplitter → one chunk per logical section.
  4. RecursiveCharacterTextSplitter for oversized sections (> 1200 chars).
  5. Metadata anchoring: prepend breadcrumb to each child chunk text so the
     embedding vector is anchored to the business domain cluster.
  6. Parent-Child storage:
       parent = full section text (NOT embedded, stored as chunk_type='section')
       child  = sub-content units (embedded with bge-m3, chunk_type='clause')
  7. Sync to PostgreSQL text_chunks + Qdrant ocr_documents collection.

Usage:
  python tools/rechunk_semantic.py --file 第二册电气设备安装工程 [--dry-run] [--all]
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import psycopg2
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

# ── path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "backend" / "retrieval-service"))

OCR_DIRS = [
    Path(__file__).parent.parent / "data" / "ocr_outputs" / "深圳市建设工程地方标准",
    Path(__file__).parent.parent / "data" / "ocr_outputs",
]

# section numbers that indicate real headings vs list items
# Pattern: starts with digit.digit (e.g. 10.2 or 10.2.6) at line start
# OR starts with a single chapter number (e.g. "10电气调整") followed by Chinese
_SECTION_RE = re.compile(
    r"^(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)\s*([\u4e00-\u9fff\(\（].{0,60})"
)
_CHAPTER_RE = re.compile(r"^(\d{1,2})\s*([\u4e00-\u9fff].{1,30})")
_PAGE_MARKER_RE = re.compile(r"<!--PAGE:(\d+)-->")
_SECTION_NUM_LEADING_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,2})")


def _extract_chapter_id(metadata: dict) -> Optional[str]:
    """Extract the most specific section number (e.g. '10.2.6') from metadata fields.

    MarkdownHeaderTextSplitter maps ## → 'section', ### → 'subsection'.
    There are no # (chapter) level headers because _CHAPTER_RE is disabled to
    avoid false positives on list items. So metadata['chapter'] is always None
    unless we parse it from the section/subsection text here.
    """
    for key in ("subsection", "section"):
        val = (metadata.get(key) or "").strip()
        m = _SECTION_NUM_LEADING_RE.match(val)
        if m:
            return m.group(1)
    return None

CHILD_MAX_CHARS = 1200
CHILD_OVERLAP   = 150


# ── OCR JSON loading ──────────────────────────────────────────────────────────

def find_ocr_json(stem: str) -> Path:
    """Locate the OCR JSON file for a given file stem."""
    for d in OCR_DIRS:
        for p in d.glob("*.json"):
            if stem in p.stem:
                return p
    raise FileNotFoundError(f"OCR JSON not found for: {stem!r}")


def load_ocr_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── Markdown normalisation ────────────────────────────────────────────────────

def _header_level(section_num: str) -> int:
    """Return # depth: X → 1, X.Y → 2, X.Y.Z → 3"""
    return section_num.count(".") + 1


def normalize_to_markdown(pages: list[dict]) -> str:
    """
    Concatenate all page markdown fields into one structured markdown string
    with # headers derived from section numbers.

    Page boundaries are marked as <!--PAGE:N--> comments so we can later
    recover page_number metadata for each chunk.
    """
    lines_out: list[str] = []

    for page in sorted(pages, key=lambda x: x.get("page_number", 0)):
        pnum = page.get("page_number", 0)
        md   = page.get("markdown", "") or page.get("raw_text", "")
        if not md.strip():
            continue

        lines_out.append(f"\n<!--PAGE:{pnum}-->")

        for raw_line in md.split("\n"):
            line = raw_line.strip()
            if not line:
                lines_out.append("")
                continue

            # Skip bare page number footer lines like "304", "305"
            if re.fullmatch(r"\d{2,4}\.?", line):
                continue

            # Match X.Y.Z / X.Y style section numbers
            m_sec = _SECTION_RE.match(line)
            if m_sec:
                num   = m_sec.group(1)
                rest  = m_sec.group(2).strip()
                depth = _header_level(num)
                prefix = "#" * min(depth, 3)
                # Ensure space between section number and title text
                lines_out.append(f"{prefix} {num} {rest}")
                continue

            # NOTE: _CHAPTER_RE (single-digit chapter numbers like "10电气调整")
            # is intentionally NOT applied here. Single-digit chapter numbers are
            # indistinguishable from list item numbers (e.g. "1变压器保护调试，..."),
            # so applying _CHAPTER_RE causes false section headers in the markdown
            # that pollute the title_map used for gap detection. We only use
            # X.Y and X.Y.Z format (matched by _SECTION_RE) as real headers.

            lines_out.append(line)

    return "\n".join(lines_out)


# ── Section gap detection + title injection ───────────────────────────────────

def _extract_section_titles(full_md: str) -> dict[str, str]:
    """
    Build a mapping of section_number → title by scanning all ### headers.
    Used to infer missing titles for detected gaps.
    """
    mapping: dict[str, str] = {}
    for line in full_md.split("\n"):
        for prefix in ("### ", "## ", "# "):
            if line.startswith(prefix):
                content = line[len(prefix):].strip()
                # Match "10.2.6 送配电装置系统调试..." (with space after number)
                m = re.match(r"^(\d+\.\d+(?:\.\d+)?)\s+(.{2,})", content)
                if m:
                    num   = m.group(1)
                    title = m.group(2).strip()
                    # Strip trailing 【OCR...】 markers if already injected
                    title = re.sub(r"【OCR.*?】", "", title).strip()
                    if title:
                        mapping[num] = title
                break
    return mapping


def _insert_missing_section_titles(full_md: str, title_map: dict[str, str]) -> str:
    """
    Detect numbered-section gaps in ### headers and inject a placeholder
    title.  For example if 10.2.5 is followed immediately by 10.2.7 at the
    same depth, we inject:
        ### 10.2.6 送配电装置系统调试【OCR缺失标题，已从子目构成表推断】
    The inferred title is looked up in the 10.3.x / 10.1.x mirror sections
    if available, else left as UNKNOWN.
    """
    lines = full_md.split("\n")
    result: list[str] = []
    prev_sec: Optional[str] = None
    prev_depth: int = 0

    for line in lines:
        # Detect the current header depth + section number
        m = re.match(r"^(#{1,3}) (\d+\.\d+(?:\.\d+)?)\s+", line)
        if m:
            depth  = len(m.group(1))
            secnum = m.group(2)
            parts  = [int(x) for x in secnum.split(".")]

            # Only check for gap within same depth and parent
            if (
                prev_sec is not None
                and depth == prev_depth
                and len(parts) == len(prev_sec.split("."))
            ):
                prev_parts = [int(x) for x in prev_sec.split(".")]
                # Same parent (all but last component equal)
                if parts[:-1] == prev_parts[:-1]:
                    last_prev = prev_parts[-1]
                    last_curr = parts[-1]
                    # Inject one missing entry if exactly one was skipped
                    if last_curr == last_prev + 2:
                        missing_num = ".".join(
                            str(x) for x in prev_parts[:-1] + [last_prev + 1]
                        )
                        # Look for the title in mirror sections
                        inferred = _infer_missing_title(missing_num, title_map)
                        prefix = "#" * depth
                        result.append(
                            f"{prefix} {missing_num} {inferred}"
                            f"【OCR缺失标题，已从文档推断】"
                        )

            prev_sec   = secnum
            prev_depth = depth

        result.append(line)

    return "\n".join(result)


def _infer_missing_title(missing_num: str, title_map: dict[str, str]) -> str:
    """
    Return UNKNOWN — we cannot reliably infer a title for a missing section
    from mirror sections because the numbering may not align across sub-sections.
    The chunk will still be created; retrieval relies on the content text.
    """
    return "UNKNOWN"


# ── MarkdownHeaderTextSplitter pipeline ──────────────────────────────────────

_HEADER_SPLITS = [
    ("#",   "chapter"),
    ("##",  "section"),
    ("###", "subsection"),
]

_rc_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHILD_MAX_CHARS,
    chunk_overlap=CHILD_OVERLAP,
    separators=["\n\n", "\n", "。", "；", " ", ""],
)


def split_into_chunks(full_md: str, file_name: str) -> list[dict]:
    """
    Split structured markdown into semantic chunks.

    Returns a list of dicts:
      {
        "content":      str,          # text to embed (with breadcrumb prefix)
        "raw_content":  str,          # text without breadcrumb (for display)
        "metadata":     dict,         # chapter / section / subsection / page_number
        "chunk_type":   "clause"|"section",
        "page_number":  int,
      }
    """
    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=_HEADER_SPLITS,
        strip_headers=False,
    )
    docs = splitter.split_text(full_md)

    chunks: list[dict] = []

    for doc in docs:
        text     = doc.page_content
        metadata = doc.metadata

        # Extract page number from <!--PAGE:N--> markers
        page_nums = [int(m) for m in _PAGE_MARKER_RE.findall(text)]
        page_num  = min(page_nums) if page_nums else 0
        # Strip the page markers from stored text
        clean_text = _PAGE_MARKER_RE.sub("", text).strip()

        if len(clean_text) < 15:
            continue

        # Derive chapter_id from section/subsection since no '#' headers are
        # generated (see _CHAPTER_RE note above). chapter_id = most specific
        # section number found, e.g. '10.2.6' or '12.2'.
        chapter_id = _extract_chapter_id(metadata)
        metadata = dict(metadata)          # make mutable copy
        metadata["chapter"] = chapter_id

        # Build breadcrumb for metadata anchoring
        breadcrumb_parts = [file_name]
        if metadata.get("chapter"):    breadcrumb_parts.append(metadata["chapter"])
        if metadata.get("section"):    breadcrumb_parts.append(metadata["section"])
        if metadata.get("subsection"): breadcrumb_parts.append(metadata["subsection"])
        breadcrumb = " > ".join(breadcrumb_parts)

        # Parent chunk: the full section text (not re-split)
        parent_base = {
            "raw_content": clean_text,
            "metadata":    metadata,
            "chunk_type":  "section",
            "page_number": page_num,
            "breadcrumb":  breadcrumb,
        }

        if len(clean_text) <= CHILD_MAX_CHARS:
            # Section fits in one child chunk
            anchored = f"[{breadcrumb}]\n{clean_text}"
            chunks.append({**parent_base, "content": anchored, "chunk_type": "clause"})
        else:
            # Oversized section → parent + children
            children = _rc_splitter.split_text(clean_text)
            for i, child_text in enumerate(children):
                anchored = f"[{breadcrumb}]\n{child_text}"
                chunks.append({
                    **parent_base,
                    "content":     anchored,
                    "raw_content": child_text,
                    "chunk_type":  "clause",
                    "chunk_index_in_parent": i,
                })

    return chunks


# ── Database helpers ──────────────────────────────────────────────────────────

def get_pg_conn():
    return psycopg2.connect(
        host=os.environ.get("PG_HOST", "localhost"),
        port=int(os.environ.get("PG_PORT", 5432)),
        user=os.environ.get("PG_USER", "rag_user"),
        password=os.environ.get("PG_PASSWORD", "rag_password"),
        dbname=os.environ.get("PG_DB", "rag_db"),
    )


def get_doc_id(cur, file_name: str) -> Optional[int]:
    cur.execute("SELECT id FROM document_registry WHERE file_name = %s", (file_name,))
    row = cur.fetchone()
    return row[0] if row else None


def delete_old_chunks(conn, file_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM text_chunks WHERE file_name = %s", (file_name,)
        )
        n = cur.rowcount
    conn.commit()
    return n


def insert_chunks(conn, chunks: list[dict], file_name: str, doc_id: Optional[int]) -> int:
    inserted = 0
    with conn.cursor() as cur:
        for i, ch in enumerate(chunks):
            sec = ch["metadata"].get("subsection") or ch["metadata"].get("section") or ch["metadata"].get("chapter")
            meta = json.dumps({
                "chapter":    ch["metadata"].get("chapter"),
                "section":    ch["metadata"].get("section"),
                "subsection": ch["metadata"].get("subsection"),
                "breadcrumb": ch["breadcrumb"],
                "chunk_type": ch["chunk_type"],
            })
            cur.execute(
                """
                INSERT INTO text_chunks
                    (doc_id, file_name, chunk_index, content, page_number, section, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    doc_id,
                    file_name,
                    i,
                    ch["content"],      # anchored text (for embedding)
                    ch["page_number"],
                    sec,
                    meta,
                ),
            )
            inserted += 1
    conn.commit()
    return inserted


# ── Qdrant sync ───────────────────────────────────────────────────────────────

def delete_qdrant_points(file_name: str) -> int:
    """Delete all Qdrant points for a given file_name."""
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        qc = QdrantClient(host="localhost", port=6333)
        result = qc.delete(
            collection_name="ocr_documents",
            points_selector=Filter(
                must=[FieldCondition(key="file_name", match=MatchValue(value=file_name))]
            ),
        )
        return result.status.value if hasattr(result, "status") else -1
    except Exception as e:
        print(f"  [Qdrant] delete warning: {e}")
        return -1


# ── Main pipeline ─────────────────────────────────────────────────────────────

def process_file(stem: str, dry_run: bool = False) -> dict:
    """Process one OCR JSON file end-to-end."""
    t0 = time.time()
    print(f"\n{'='*60}")
    print(f"Processing: {stem}")

    # 1. Load OCR JSON
    ocr_path = find_ocr_json(stem)
    data      = load_ocr_json(ocr_path)
    file_name = data.get("file_name", ocr_path.stem + ".pdf")
    pages     = data.get("pages", [])
    print(f"  OCR pages: {len(pages)}  file_name={file_name!r}")

    # 2. Normalize to structured markdown
    full_md = normalize_to_markdown(pages)

    # 3. Build title map and inject missing section titles
    title_map = _extract_section_titles(full_md)
    full_md   = _insert_missing_section_titles(full_md, title_map)
    print(f"  Known section titles: {len(title_map)}")

    # 4. Split into semantic chunks
    chunks = split_into_chunks(full_md, file_name)
    print(f"  Semantic chunks: {len(chunks)}")

    # Show gap-injection stats
    injected = sum(1 for c in chunks if "OCR缺失标题" in c["content"])
    if injected:
        print(f"  Injected missing-title chunks: {injected}")

    if dry_run:
        # Print sample chunks
        for c in chunks[:5]:
            print(f"\n  --- chunk (p{c['page_number']}) type={c['chunk_type']} ---")
            print(f"  {c['content'][:200]!r}")
        print(f"\n  [DRY RUN] Would delete + re-insert for {file_name!r}")
        return {"file_name": file_name, "chunks": len(chunks), "dry_run": True}

    # 5. PostgreSQL: delete old + insert new
    conn   = get_pg_conn()
    doc_id = None
    with conn.cursor() as cur:
        doc_id = get_doc_id(cur, file_name)
    if doc_id is None:
        conn.close()
        print(f"  [SKIP] {file_name!r} has no document_registry entry (doc_id=NULL)")
        return {"file_name": file_name, "chunks": 0, "skipped": True}
    deleted  = delete_old_chunks(conn, file_name)
    inserted = insert_chunks(conn, chunks, file_name, doc_id)
    conn.close()
    print(f"  PG: deleted {deleted} old chunks, inserted {inserted} new chunks")

    # 6. Qdrant: delete old vectors
    qdrant_result = delete_qdrant_points(file_name)
    print(f"  Qdrant: deleted points for {file_name!r} (status={qdrant_result})")

    # 7. Backfill embeddings (reuse existing script)
    print(f"  Backfilling embeddings ...")
    import subprocess
    env = os.environ.copy()
    env["PG_PASSWORD"] = os.environ.get("PG_PASSWORD", "rag_password")
    result = subprocess.run(
        [
            sys.executable,
            "src/database/scripts/backfill_embeddings.py",
            "--table", "text_chunks",
            "--backend", "sentence_transformers",
        ],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  [WARNING] backfill stderr: {result.stderr[-500:]}")
    else:
        # Count how many got embedded
        last_lines = result.stdout.strip().split("\n")[-5:]
        for ln in last_lines:
            print(f"    {ln}")

    elapsed = time.time() - t0
    print(f"  Done in {elapsed:.1f}s")
    return {
        "file_name":  file_name,
        "chunks":     inserted,
        "deleted":    deleted,
        "elapsed_s":  round(elapsed, 1),
    }


_ALL_STEMS = [
    "第二册电气设备安装工程",
    "第三册热力设备安装工程",
    "第九册通风空调工程",
    "装饰工程消耗量标准",
    "市政工程造价文件分部分项和措施项目划分标准",
    "房屋建筑工程造价文件分部分项和措施项目划分标准",
    "深圳市建设工程计价费率标准（2023）",
    "深圳市建设工程计价费率标准（2025）",
    "科技服务业标准体系建设指南",
]


def main():
    parser = argparse.ArgumentParser(description="Semantic rechunking for engineering standards")
    parser.add_argument("--file", help="File stem to process (e.g. 第二册电气设备安装工程)")
    parser.add_argument("--all",  action="store_true", help="Process all known standard files")
    parser.add_argument("--dry-run", action="store_true", help="Preview chunks without DB write")
    args = parser.parse_args()

    if not args.file and not args.all:
        parser.print_help()
        sys.exit(1)

    stems = _ALL_STEMS if args.all else [args.file]
    results = []
    for stem in stems:
        try:
            r = process_file(stem, dry_run=args.dry_run)
            results.append(r)
        except FileNotFoundError as e:
            print(f"  SKIP: {e}")
        except Exception as e:
            import traceback
            print(f"  ERROR: {e}")
            traceback.print_exc()

    print("\n" + "="*60)
    print("Summary:")
    for r in results:
        if r.get("dry_run"):
            print(f"  [DRY RUN] {r['file_name']}: {r['chunks']} chunks")
        else:
            print(f"  {r['file_name']}: {r['chunks']} new chunks (was {r['deleted']}), {r['elapsed_s']}s")


if __name__ == "__main__":
    main()

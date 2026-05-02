"""Phase F regression: validate IngestDocument schema and PaddleOCR adapter.

Runs against the existing data/ocr_outputs/*.json fixture so it does NOT need
the OCR service running.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "backend" / "retrieval-service"))

from app.ingest_schema import IngestDocument, from_paddle_ocr_json, to_legacy_blocks  # noqa: E402


def main() -> int:
    fixture = ROOT / "data" / "ocr_outputs" / "深圳市建设工程地方标准" / "第二册电气设备安装工程.json"
    if not fixture.exists():
        print(f"FIXTURE MISSING: {fixture}")
        return 2
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    doc = from_paddle_ocr_json(raw, doc_id="fix-elec", file_name=fixture.name)
    print(f"[1] doc.extractor={doc.extractor}  pages={len(doc.pages)}")

    # find page 14 (had a table per earlier inspection)
    p14 = next((p for p in doc.pages if p.page == 14), None)
    assert p14 is not None, "no page 14"
    table_blocks = [b for b in p14.blocks if b.type == "table"]
    assert len(table_blocks) >= 1, f"page 14 expected ≥1 table block, got {len(table_blocks)}"
    tb = table_blocks[0]
    assert tb.table is not None
    assert tb.table.html, "table.html empty"
    assert isinstance(tb.table.cells, list) and len(tb.table.cells) >= 1, "cells must be non-empty list"
    print(f"[2] page 14 table OK: n_rows={tb.table.n_rows} n_cols={tb.table.n_cols} html_len={len(tb.table.html)}")

    # find any page with figures
    fig_pages = [p for p in doc.pages if any(b.type == "figure" for b in p.blocks)]
    print(f"[3] pages with figures: {len(fig_pages)} (first={fig_pages[0].page if fig_pages else None})")

    # text block sanity
    text_count = sum(1 for p in doc.pages for b in p.blocks if b.type == "text")
    assert text_count > 100, f"expected lots of text blocks, got {text_count}"
    print(f"[4] text blocks total: {text_count}")

    # Pydantic round-trip
    j = doc.model_dump()
    doc2 = IngestDocument.model_validate(j)
    assert doc2.pages[0].blocks[0].text == doc.pages[0].blocks[0].text
    print("[5] pydantic round-trip OK")

    # Legacy block conversion (without importing app.ingest_pipeline.Block — needs fitz etc.,
    # so just verify the function is callable structurally by patching a stub)
    try:
        legacy = to_legacy_blocks(doc)
        print(f"[6] to_legacy_blocks OK: {len(legacy)} blocks")
    except Exception as e:
        print(f"[6] to_legacy_blocks FAILED (likely import-only env): {type(e).__name__}: {e}")
        return 1

    print("\nSCHEMA PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

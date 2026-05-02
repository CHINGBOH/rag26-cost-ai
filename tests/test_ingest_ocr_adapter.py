"""Phase G regression: OCR adapter consumes tables/figures, falls back gracefully.

Two scenarios:
  A. Mock the OCR endpoint (httpx_mock not available, so monkeypatch httpx
     AsyncClient) and verify the adapter emits a table_row Block with
     table_html / table_cells in metadata.
  B. Force OCR to be unreachable (OCR_SERVICE_URL → invalid host) and verify
     a synthetic scan-only PDF still completes via degraded fallback.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "backend" / "retrieval-service"))

# tests need DB / proxy off
for k in ("http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(k, None)

from app.ingest_pipeline import extract_pdf_or_image_via_ocr  # noqa: E402


# ── Scenario A: OCR reachable, returns tables + figures ─────────────────────
class _FakeResp:
    status_code = 200
    text = ""
    def __init__(self, payload): self._payload = payload
    def json(self): return self._payload


class _FakeAsyncClient:
    payload = {
        "pages": [
            {
                "page_number": 1,
                "text_blocks": [
                    {"text": "送配电装置系统调试", "confidence": 0.99, "bbox": [10,10,200,30]}
                ],
                "tables": [
                    {
                        "html": "<table><tr><td>项目</td><td>单价</td></tr><tr><td>送配电</td><td>1234.56</td></tr></table>",
                        "markdown": "| 项目 | 单价 |\n|---|---|\n| 送配电 | 1234.56 |",
                        "cells": [["项目","单价"],["送配电","1234.56"]],
                    }
                ],
                "figures": [
                    {"region_type": "chart", "text_in_region": "走势图：2023-2026 价格"}
                ],
                "raw_text": "送配电装置系统调试",
            }
        ]
    }
    def __init__(self, *a, **kw): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return None
    async def post(self, *a, **kw): return _FakeResp(self.payload)


def test_a_mock_ocr_consumes_tables_figures():
    pdf = Path(tempfile.mkdtemp()) / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%fake")

    with patch("httpx.AsyncClient", _FakeAsyncClient):
        blocks, extractor = asyncio.run(
            extract_pdf_or_image_via_ocr(pdf, "doc-A", "fake.pdf")
        )

    assert extractor == "ocr_paddle", extractor
    types = sorted({b.type for b in blocks})
    print(f"[A] extractor={extractor} blocks={len(blocks)} types={types}")
    assert "text" in types
    assert "table_row" in types, f"table_row missing! got {types}"
    assert "caption" in types, f"caption (figure) missing! got {types}"

    table_b = next(b for b in blocks if b.type == "table_row")
    assert table_b.metadata.get("table_html"), "table_html missing in metadata"
    assert table_b.metadata.get("table_cells"), "table_cells missing in metadata"
    assert "送配电" in table_b.text, f"markdown not in text: {table_b.text[:100]}"
    print(f"[A] table block OK: html_len={len(table_b.metadata['table_html'])} cells={table_b.metadata['table_cells']}")

    fig_b = next(b for b in blocks if b.type == "caption")
    assert fig_b.metadata.get("figure_region_type") == "chart", fig_b.metadata
    assert "走势图" in fig_b.text
    print(f"[A] figure block OK: region={fig_b.metadata['figure_region_type']} text='{fig_b.text}'")
    print("[A] PASS\n")


# ── Scenario B: OCR unreachable → degraded path ─────────────────────────────
def test_b_ocr_unreachable_degraded():
    # build a 2-page native PDF with no images — sparse text triggers OCR path,
    # but OCR_SERVICE_URL points to closed port → must fall back to native scan
    import fitz
    pdf = Path(tempfile.mkdtemp()) / "scan.pdf"
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page()
        page.insert_text((50, 50), f"P{i+1}", fontsize=10)  # 2 chars only — sparse
    doc.save(str(pdf))
    doc.close()

    os.environ["OCR_SERVICE_URL"] = "http://127.0.0.1:1"  # closed
    blocks, extractor = asyncio.run(
        extract_pdf_or_image_via_ocr(pdf, "doc-B", "scan.pdf", job_id=None)
    )
    print(f"[B] extractor={extractor} blocks={len(blocks)}")
    # Did NOT raise — that's the test
    assert extractor in ("scan_no_ocr_fallback", "pymupdf"), extractor
    print("[B] PASS — pipeline degraded gracefully instead of crashing\n")


if __name__ == "__main__":
    test_a_mock_ocr_consumes_tables_figures()
    test_b_ocr_unreachable_degraded()
    print("OCR ADAPTER PASS")

"""IngestDocument JSON schema — unified shape every extractor must emit.

Phase F of issue #69. Decouples extractors (pymupdf / paddleocr / pdfplumber /
csv / xlsx) from the downstream writers (PG / Qdrant / Neo4j) by inserting a
typed contract in the middle.
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple
from pydantic import BaseModel, Field


class IngestTable(BaseModel):
    html: str = ""
    markdown: str = ""
    # Cells can be either a 2D matrix or a flat list of {row,col,text,bbox} dicts —
    # we store both forms so downstream code can pick what it needs.
    cells: List[Any] = Field(default_factory=list)
    n_rows: int = 0
    n_cols: int = 0


class IngestFigure(BaseModel):
    region_type: str = "figure"  # figure / chart / diagram / formula / trend
    text_in_region: str = ""


class IngestBlock(BaseModel):
    block_id: str
    type: str = "text"  # text | table | figure | formula | caption
    text: str = ""  # human/embedding-friendly representation
    bbox: Optional[Tuple[float, float, float, float]] = None
    confidence: Optional[float] = None
    table: Optional[IngestTable] = None
    figure: Optional[IngestFigure] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestPage(BaseModel):
    page: int
    text: str = ""  # raw merged text fallback
    blocks: List[IngestBlock] = Field(default_factory=list)


class IngestBlindspot(BaseModel):
    page: int
    kind: str  # chart | figure | scan_no_ocr | db_drift
    reason: str = ""
    image_count: int = 0
    text_chars: int = 0


class IngestDocument(BaseModel):
    doc_id: str
    file_name: str
    extractor: str  # pymupdf | paddleocr | pdfplumber | csv | xlsx | mixed
    pages: List[IngestPage] = Field(default_factory=list)
    blindspots: List[IngestBlindspot] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Adapters ──────────────────────────────────────────────────────────────────

def from_paddle_ocr_json(data: dict, *, doc_id: str, file_name: str) -> IngestDocument:
    """Convert the existing data/ocr_outputs/*.json shape (PaddleOCR + PPStructure)
    into IngestDocument.

    Source schema (from src/backend/ocr-service/ocr_service.py):
      pages[*].page_number, text_blocks[{text,confidence,bbox}],
              tables[{html,markdown,cells}],
              figures[{region_type,text_in_region}],
              raw_text, markdown, confidence
    """
    pages: list[IngestPage] = []
    for raw in data.get("pages") or []:
        pn = int(raw.get("page_number") or raw.get("page") or len(pages) + 1)
        blocks: list[IngestBlock] = []

        # text blocks
        for bi, tb in enumerate(raw.get("text_blocks") or []):
            text = (tb or {}).get("text") or ""
            if not text.strip():
                continue
            blocks.append(IngestBlock(
                block_id=f"p{pn}_t{bi}",
                type="text",
                text=text,
                bbox=tuple(tb["bbox"]) if isinstance(tb.get("bbox"), (list, tuple)) and len(tb["bbox"]) == 4 else None,
                confidence=tb.get("confidence"),
            ))

        # tables — markdown is the embedding-friendly form
        for ti, tb in enumerate(raw.get("tables") or []):
            cells = tb.get("cells") or []
            # PaddleOCR PPStructure can give either a 2D list[list[str]] or a
            # flat list[{row,col,text,bbox}]. Normalize n_rows/n_cols accordingly.
            if cells and isinstance(cells[0], dict):
                n_rows = max((c.get("row", 0) for c in cells), default=-1) + 1
                n_cols = max((c.get("col", 0) for c in cells), default=-1) + 1
            elif cells and isinstance(cells[0], list):
                n_rows = len(cells)
                n_cols = max((len(r) for r in cells), default=0)
            else:
                n_rows = n_cols = 0
            md = tb.get("markdown") or ""
            html = tb.get("html") or ""
            text = md or html or ""
            if not text.strip():
                continue
            blocks.append(IngestBlock(
                block_id=f"p{pn}_tbl{ti}",
                type="table",
                text=text,
                table=IngestTable(html=html, markdown=md, cells=cells, n_rows=n_rows, n_cols=n_cols),
            ))

        # figures (charts / trends)
        for fi, fg in enumerate(raw.get("figures") or []):
            tir = fg.get("text_in_region") or ""
            blocks.append(IngestBlock(
                block_id=f"p{pn}_fig{fi}",
                type="figure",
                text=tir or f"[图表区域 page {pn}]",
                figure=IngestFigure(
                    region_type=fg.get("region_type") or "figure",
                    text_in_region=tir,
                ),
            ))

        pages.append(IngestPage(page=pn, text=raw.get("raw_text") or "", blocks=blocks))

    return IngestDocument(
        doc_id=doc_id,
        file_name=file_name,
        extractor="paddleocr",
        pages=pages,
    )


def to_legacy_blocks(doc: IngestDocument) -> list:
    """Down-convert an IngestDocument to the legacy app.ingest_pipeline.Block
    flow, so existing chunking / writing code keeps working untouched.

    Mapping:
      type=text                         → Block(type="text")
      type=table                        → Block(type="table_row", text=markdown,
                                                metadata={"table": cells, "html": ..})
      type=figure                       → Block(type="caption", text=text_in_region,
                                                metadata={"figure": region_type})
      type=formula                      → Block(type="caption", text=text)
      type=caption                      → Block(type="caption", text=text)
    """
    from app.ingest_pipeline import Block  # local to avoid circular at module import
    out: list = []
    for page in doc.pages:
        for b in page.blocks:
            md = dict(b.metadata) if b.metadata else {}
            if b.confidence is not None:
                md.setdefault("confidence", b.confidence)
            if b.bbox is not None:
                md.setdefault("bbox", list(b.bbox))
            if b.type == "text":
                btype = "text"
            elif b.type == "table":
                btype = "table_row"
                if b.table:
                    md["table_html"] = b.table.html
                    md["table_cells"] = b.table.cells
                    md["table_n_rows"] = b.table.n_rows
                    md["table_n_cols"] = b.table.n_cols
            elif b.type == "figure":
                btype = "caption"
                if b.figure:
                    md["figure_region_type"] = b.figure.region_type
            else:
                btype = "caption"
            out.append(Block(
                doc_id=doc.doc_id,
                page=page.page,
                block_id=b.block_id,
                type=btype,
                text=b.text,
                metadata=md,
            ))
    return out

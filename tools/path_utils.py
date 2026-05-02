"""Shared chunk path/depth computation.

Used by ingest writers (rechunk_semantic, ocr_ingest_pipeline) and the
backfill script. Single source of truth for the materialized path scheme.

Path scheme:
  - Chapter docs (e.g. 第二册电气设备安装工程.pdf): "<book>/<section>/<subsection>"
    derived from metadata.breadcrumb when available. depth = number of segments.
  - Price-info docs (e.g. 《深圳建设工程价格信息》2026年1月.pdf): "<filename_stem>"
    depth = 1.
  - Fallback: filename stem, depth = 1.
"""

from __future__ import annotations

import os
import re
from typing import Optional, Tuple


def _strip_ext(file_name: str) -> str:
    return os.path.splitext(file_name or "")[0]


def _from_breadcrumb(breadcrumb: str) -> Optional[Tuple[str, int]]:
    """Convert breadcrumb 'a.pdf > 1.0 X > 1.2.6 Y' to ('a/1.0/1.2.6', 3).

    Strips the file extension off the first segment and any human-readable
    title text after the leading numeric/identifier token of each segment.
    """
    if not breadcrumb:
        return None
    parts = [p.strip() for p in breadcrumb.split(">")]
    parts = [p for p in parts if p]
    if not parts:
        return None
    out: list[str] = []
    for i, seg in enumerate(parts):
        if i == 0:
            out.append(_strip_ext(seg))
            continue
        # Take leading token before first whitespace (handles "1.2.6 标题")
        token = seg.split()[0] if seg else seg
        # Strip trailing punctuation
        token = token.rstrip("、,.，。:：")
        out.append(token or seg)
    path = "/".join(out)
    return path, len(out)


_PRICE_INFO_RE = re.compile(r"价格信息|信息价")
_PERIOD_RE = re.compile(r"(20\d{2})[年\-_](\d{1,2})月?")


def compute_chunk_path(
    file_name: Optional[str],
    metadata: Optional[dict] = None,
) -> Tuple[Optional[str], Optional[int]]:
    """Compute (path, depth) for a text chunk.

    Returns (None, None) if file_name is empty.
    """
    if not file_name:
        return None, None

    md = metadata or {}

    # 1. Best signal: breadcrumb in metadata
    bc = md.get("breadcrumb") if isinstance(md, dict) else None
    if bc:
        result = _from_breadcrumb(bc)
        if result:
            return result

    # 2. Price-info docs → period-based path
    if _PRICE_INFO_RE.search(file_name) or "价格信息" in file_name:
        m = _PERIOD_RE.search(file_name)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}", 1
        return _strip_ext(file_name), 1

    # 3. Filename of form 2025-12.pdf → keep as-is
    stem = _strip_ext(file_name)
    if re.fullmatch(r"20\d{2}-\d{2}", stem):
        return stem, 1

    # 4. Generic fallback: filename stem, depth=1
    return stem, 1

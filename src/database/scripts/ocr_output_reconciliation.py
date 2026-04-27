#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OCR_OUTPUT_DIR = Path(os.environ.get("OCR_OUTPUT_DIR", ROOT / "data" / "ocr_outputs"))
DEFAULT_ARCHIVE_ROOT = ROOT / "archive" / "ocr-output-duplicates"
_SKIP_OCR_FILENAMES = {"processing_summary.json", "processed_documents.log", "_scan_state.json"}

_SCAN_STATE_ENTRIES_CACHE: dict[str, list[dict[str, str]]] = {}
_SCAN_STATE_OUTPUTS_CACHE: dict[str, set[str]] = {}


def normalize_document_label(value: str) -> str:
    return "".join((value or "").split()).strip()


def _cache_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except Exception:
        return False


def load_scan_state_entries(ocr_output_dir: Path = DEFAULT_OCR_OUTPUT_DIR) -> list[dict[str, str]]:
    cache_key = _cache_key(ocr_output_dir)
    cached = _SCAN_STATE_ENTRIES_CACHE.get(cache_key)
    if cached is not None:
        return cached

    scan_state_path = ocr_output_dir / "_scan_state.json"
    entries: list[dict[str, str]] = []
    if scan_state_path.exists():
        try:
            payload = json.loads(scan_state_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            for source_pdf, item in payload.items():
                if not isinstance(item, dict):
                    continue
                if str(item.get("status") or "").lower() != "done":
                    continue
                output = str(item.get("output") or "").strip()
                if not output:
                    continue
                entries.append(
                    {
                        "source_pdf": str(source_pdf),
                        "output": output,
                        "normalized_file_name": normalize_document_label(Path(str(source_pdf)).name),
                    }
                )

    _SCAN_STATE_ENTRIES_CACHE[cache_key] = entries
    _SCAN_STATE_OUTPUTS_CACHE[cache_key] = {str(Path(entry["output"]).resolve()) for entry in entries}
    return entries


def load_scan_state_output_paths(ocr_output_dir: Path = DEFAULT_OCR_OUTPUT_DIR) -> set[str]:
    cache_key = _cache_key(ocr_output_dir)
    if cache_key not in _SCAN_STATE_OUTPUTS_CACHE:
        load_scan_state_entries(ocr_output_dir)
    return _SCAN_STATE_OUTPUTS_CACHE.get(cache_key, set())


def build_ocr_source_candidate_score(
    path: Path,
    data: dict[str, Any],
    ocr_output_dir: Path = DEFAULT_OCR_OUTPUT_DIR,
) -> tuple[int, int, int, int, int, str]:
    pages = data.get("pages")
    page_count = len(pages) if isinstance(pages, list) else 0
    table_count = 0
    text_len = 0
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue
            tables = page.get("tables")
            if isinstance(tables, list):
                table_count += len(tables)
            text = page.get("text")
            if isinstance(text, str):
                text_len += len(text)
    try:
        file_size = path.stat().st_size
    except OSError:
        file_size = 0
    scan_state_priority = 1 if str(path.resolve()) in load_scan_state_output_paths(ocr_output_dir) else 0
    return (page_count, table_count, text_len, file_size, scan_state_priority, str(path))


def list_missing_scan_state_outputs(ocr_output_dir: Path = DEFAULT_OCR_OUTPUT_DIR) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    for entry in load_scan_state_entries(ocr_output_dir):
        if not Path(entry["output"]).exists():
            missing.append(entry)
    return missing


def _iter_candidate_roots(ocr_output_dir: Path, archive_root: Path) -> list[Path]:
    roots = [ocr_output_dir]
    if archive_root.exists():
        roots.extend(sorted((child for child in archive_root.iterdir() if child.is_dir()), reverse=True))
    return roots


def _iter_candidate_paths(
    source_pdf: str,
    target_path: Path,
    ocr_output_dir: Path,
    archive_root: Path,
):
    pdf_stem = Path(source_pdf).stem.strip()
    candidate_patterns = [
        target_path.name,
        f"{pdf_stem}.json",
        f"{pdf_stem}_ocr.json",
        f"{pdf_stem}_OCR.json",
        f"*{pdf_stem}*.json",
    ]
    seen: set[str] = set()
    for root in _iter_candidate_roots(ocr_output_dir, archive_root):
        for pattern in candidate_patterns:
            for path in root.rglob(pattern):
                if path.name in _SKIP_OCR_FILENAMES or "chunk" in path.name.lower():
                    continue
                try:
                    resolved = str(path.resolve())
                    target_resolved = str(target_path.resolve())
                except OSError:
                    resolved = str(path)
                    target_resolved = str(target_path)
                if resolved == target_resolved or resolved in seen:
                    continue
                seen.add(resolved)
                yield path


def _load_candidate_data(path: Path) -> tuple[dict[str, Any], str] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("pages"), list):
        return None
    file_name = str(payload.get("file_name") or path.name)
    normalized = normalize_document_label(file_name)
    if not normalized:
        normalized = normalize_document_label(path.stem.removesuffix("_ocr"))
    return payload, normalized


def _find_best_restore_source(
    entry: dict[str, str],
    ocr_output_dir: Path,
    archive_root: Path,
) -> tuple[Path, str] | None:
    target_path = Path(entry["output"])
    normalized_file_name = entry["normalized_file_name"]
    candidates: list[tuple[tuple[int, int, int, int, int, int, str], Path, str]] = []
    for path in _iter_candidate_paths(entry["source_pdf"], target_path, ocr_output_dir, archive_root):
        loaded = _load_candidate_data(path)
        if loaded is None:
            continue
        payload, normalized = loaded
        if normalized != normalized_file_name:
            continue
        is_live = 1 if _is_relative_to(path, ocr_output_dir) else 0
        score = (is_live, *build_ocr_source_candidate_score(path, payload, ocr_output_dir))
        candidates.append((score, path, "live" if is_live else "archive"))
    if not candidates:
        return None
    _, path, source_kind = max(candidates, key=lambda item: item[0])
    return path, source_kind


def reconcile_live_ocr_outputs(
    ocr_output_dir: Path = DEFAULT_OCR_OUTPUT_DIR,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
    dry_run: bool = False,
) -> list[dict[str, str]]:
    reports: list[dict[str, str]] = []
    for entry in list_missing_scan_state_outputs(ocr_output_dir):
        target_path = Path(entry["output"])
        candidate = _find_best_restore_source(entry, ocr_output_dir, archive_root)
        if candidate is None:
            reports.append(
                {
                    "status": "missing",
                    "output": str(target_path),
                    "source_pdf": entry["source_pdf"],
                }
            )
            continue
        source_path, source_kind = candidate
        status = "would_restore" if dry_run else "restored"
        if not dry_run:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
        reports.append(
            {
                "status": status,
                "output": str(target_path),
                "source": str(source_path),
                "source_kind": source_kind,
            }
        )
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore missing live OCR outputs referenced by _scan_state.json")
    parser.add_argument("--dry-run", action="store_true", help="Report missing/restorable files without copying")
    args = parser.parse_args()

    reports = reconcile_live_ocr_outputs(dry_run=args.dry_run)
    restored = [item for item in reports if item["status"] in {"restored", "would_restore"}]
    missing = [item for item in reports if item["status"] == "missing"]

    print(f"scan_state_missing={len(reports)} restored={len(restored)} unresolved={len(missing)}")
    for item in restored[:20]:
        print(f"{item['status']}: {item['output']} <= {item['source_kind']}:{item['source']}")
    for item in missing[:20]:
        print(f"missing: {item['output']} (source_pdf={item['source_pdf']})")

    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
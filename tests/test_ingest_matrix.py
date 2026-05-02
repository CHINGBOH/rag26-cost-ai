"""Issue #69 Phase B: ingest pipeline format matrix.

Generates fixtures on-the-fly and uploads each through /api/v1/pipeline/upload,
asserting the job reaches done with the expected extractor and chunk count.

Skips OCR-dependent paths if the OCR service is unreachable.
"""
import io
import json
import os
import socket
import sys
import time
import urllib.request
from pathlib import Path

ENDPOINT = "http://localhost:8002"
FIXTURE_DIR = Path("/tmp/ingest_fixtures")
FIXTURE_DIR.mkdir(parents=True, exist_ok=True)


def _ocr_up() -> bool:
    try:
        s = socket.create_connection(("localhost", 8001), timeout=1)
        s.close()
        return True
    except Exception:
        return False


def make_txt() -> Path:
    p = FIXTURE_DIR / "sample.txt"
    p.write_text("建筑工程脚手架费按人工费的15%计取。\n\n"
                 "本规则适用于2026年1月。市场价格波动以信息价为准。", encoding="utf-8")
    return p


def make_native_pdf() -> Path:
    p = FIXTURE_DIR / "native.pdf"
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), "Native PDF: scaffolding fee = 15% of labor.", fontsize=11)
    page.insert_text((50, 100), "This applies to 2026-01 quotations.", fontsize=11)
    page.insert_text((50, 130), "Reference: cost standard 2025 edition.", fontsize=11)
    doc.save(str(p))
    doc.close()
    return p


def make_csv() -> Path:
    p = FIXTURE_DIR / "prices.csv"
    p.write_text(
        "材料名称,规格,单位,2026-01价格\n"
        "中砂,粒径0.5mm,m³,180\n"
        "电线,BV2.5,m,5.6\n"
        "电缆,YJV3*16,m,42.5\n",
        encoding="utf-8",
    )
    return p


def make_xlsx() -> Path:
    p = FIXTURE_DIR / "rates.xlsx"
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "费率"
    ws.append(["项目", "费率%", "适用年版"])
    ws.append(["企业管理费", 5.5, "2025"])
    ws.append(["利润", 6.0, "2025"])
    ws.append(["规费", 4.2, "2025"])
    ws2 = wb.create_sheet("说明")
    ws2.append(["条款", "正文"])
    ws2.append(["1.1", "本费率适用于一般工业与民用建筑。"])
    wb.save(str(p))
    return p


def upload_and_wait(path: Path, timeout: int = 60) -> dict:
    body, ct = _multipart(path)
    req = urllib.request.Request(
        f"{ENDPOINT}/api/v1/pipeline/upload",
        data=body, headers={"Content-Type": ct}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
    job_id = resp["job_id"]
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        time.sleep(1.0)
        with urllib.request.urlopen(f"{ENDPOINT}/api/v1/pipeline/job/{job_id}", timeout=10) as r:
            last = json.loads(r.read())
        if last["status"] in ("done", "failed"):
            return last
    return last


def _multipart(path: Path) -> tuple[bytes, str]:
    boundary = "----ingest" + os.urandom(8).hex()
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode())
    body.write(b"Content-Type: application/octet-stream\r\n\r\n")
    body.write(path.read_bytes())
    body.write(f"\r\n--{boundary}--\r\n".encode())
    return body.getvalue(), f"multipart/form-data; boundary={boundary}"


def main() -> int:
    cases: list[tuple[str, Path, str, int]] = [
        # name, fixture, expected extractor, min chunks
        ("txt",   make_txt(),        "text",    1),
        ("pdf-native", make_native_pdf(), "pymupdf", 1),
        ("csv",   make_csv(),        "csv",     3),  # header + 3 rows
        ("xlsx",  make_xlsx(),       "xlsx",    4),  # 2 sheets, 3+1 rows
    ]
    if _ocr_up():
        # only attempt OCR test if service is reachable
        # (no fixture: caller should drop a real scan PDF in fixtures dir)
        pass

    results = []
    failed = 0
    for name, path, expect_extr, min_chunks in cases:
        print(f"\n[{name}] {path.name} ({path.stat().st_size}B)")
        j = upload_and_wait(path, timeout=60)
        ok = (
            j.get("status") == "done"
            and j.get("extractor") == expect_extr
            and (j.get("chunks_pg") or 0) >= min_chunks
        )
        print(f"  status={j.get('status')} extractor={j.get('extractor')} "
              f"blocks={j.get('blocks_total')} chunks={j.get('chunks_pg')} "
              f"ms={j.get('duration_ms')} err={j.get('error')}")
        results.append({"case": name, "ok": ok, "job": j})
        if not ok:
            failed += 1

    print(f"\nMatrix: {len(cases) - failed}/{len(cases)} passed")
    if failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

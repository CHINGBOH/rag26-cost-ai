"""Issue #69 Phase D: blindspot detection test.

Builds a PDF whose page 2 contains only an image (no text), uploads it,
and asserts ingest_blindspots has a chart/figure row for page 2 plus
the API surfaces it on the job response.
"""
import io
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

EP = "http://localhost:8002"
FIX = Path("/tmp/ingest_fixtures")
FIX.mkdir(parents=True, exist_ok=True)


def make_pdf_with_image_page() -> Path:
    import fitz
    p = FIX / "with_chart.pdf"
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((50, 72), "Page 1: this is normal text content for context.", fontsize=11)
    p1.insert_text((50, 100), "Reference figure on page 2 shows the trend.", fontsize=11)
    p1.insert_text((50, 130), "More than thirty characters of content on page one.", fontsize=11)

    p2 = doc.new_page()
    # Embed a synthetic PNG
    import struct
    import zlib
    w, h = 80, 80
    raw = b""
    for y in range(h):
        raw += b"\x00"
        for x in range(w):
            r = (x * 3) & 0xFF; g = (y * 3) & 0xFF; b = ((x + y) * 2) & 0xFF
            raw += bytes((r, g, b))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw))
    png += chunk(b"IEND", b"")

    p2.insert_image(fitz.Rect(50, 50, 250, 250), stream=png)
    # tiny text on p2 (< 80 chars) so it qualifies as blindspot
    p2.insert_text((50, 270), "fig.1", fontsize=8)
    doc.save(str(p))
    doc.close()
    return p


def upload(p: Path) -> str:
    boundary = "----b" + os.urandom(8).hex()
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="file"; filename="{p.name}"\r\n'.encode())
    body.write(b"Content-Type: application/pdf\r\n\r\n")
    body.write(p.read_bytes())
    body.write(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"{EP}/api/v1/pipeline/upload",
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    return json.loads(urllib.request.urlopen(req, timeout=120).read())["job_id"]


def main() -> int:
    pdf = make_pdf_with_image_page()
    print("[1] upload", pdf)
    jid = upload(pdf)
    print("    job:", jid)

    for _ in range(60):
        time.sleep(1)
        j = json.loads(urllib.request.urlopen(f"{EP}/api/v1/pipeline/job/{jid}", timeout=10).read())
        if j["status"] in ("done", "failed"):
            break
    if j["status"] != "done":
        print("    FAIL:", j); return 1
    print(f"    done: blocks={j['blocks_total']} chunks={j['chunks_pg']}")

    bs = j.get("blindspots") or []
    print(f"[2] job blindspots: {len(bs)}")
    for b in bs:
        print(f"    page={b['page']} kind={b['kind']} imgs={b['image_count']} "
              f"chars={b['text_chars']}  {b['reason']}")

    # Filter call
    r = json.loads(urllib.request.urlopen(
        f"{EP}/api/v1/pipeline/blindspots?doc_id={j['doc_id']}", timeout=10).read())
    print(f"[3] /blindspots count: {r['count']}")

    ok = (
        any(b["page"] == 2 and b["kind"] in ("chart", "figure") for b in bs)
        and r["count"] >= 1
    )
    print("\nBLINDSPOT", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

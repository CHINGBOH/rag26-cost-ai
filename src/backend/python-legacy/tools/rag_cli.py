#!/usr/bin/env python3
"""
RAG CLI — 精简入口
仅保留有自动化价值的命令：upload / chat / check
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

API_URL = os.environ.get("RAG_API", "http://localhost:8080")
OCR_URL = os.environ.get("OCR_API", "http://localhost:8001")


def _curl(method: str, url: str, data=None, headers=None, files=None, timeout=30):
    """简易 HTTP 客户端（避免依赖 requests）"""
    import urllib.request
    import urllib.error

    req = urllib.request.Request(url, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)

    body = None
    if data and isinstance(data, dict):
        req.add_header("Content-Type", "application/json")
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    elif data and isinstance(data, str):
        body = data.encode("utf-8")

    try:
        resp = urllib.request.urlopen(req, data=body, timeout=timeout)
        return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"error": str(e), "status_code": e.code}
    except Exception as e:
        return {"error": str(e)}


def cmd_upload(args):
    """PDF → OCR(async) → poll → import PG"""
    path = Path(args.path)
    if not path.exists():
        print(f"❌ File not found: {path}")
        return 1

    files = []
    if path.is_dir():
        files = sorted(path.glob("*.pdf"))
        print(f"📁 Found {len(files)} PDF files in {path}")
    else:
        files = [path]

    for pdf in files:
        print(f"\n📄 Uploading: {pdf.name}")
        # Step 1: async OCR
        import urllib.request
        boundary = "----RAGBoundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{pdf.name}"\r\n'
            f"Content-Type: application/pdf\r\n\r\n"
        ).encode("utf-8") + pdf.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")

        req = urllib.request.Request(
            f"{OCR_URL}/ocr/pdf/async",
            data=body,
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            resp = urllib.request.urlopen(req, timeout=60)
            job = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  ❌ OCR upload failed: {e}")
            continue

        job_id = job.get("job_id")
        if not job_id:
            print(f"  ❌ No job_id returned")
            continue
        print(f"  ⏳ OCR job: {job_id}")

        # Step 2: poll (max 3 min)
        result = None
        for i in range(60):
            time.sleep(3)
            status = _curl("GET", f"{OCR_URL}/ocr/pdf/async/{job_id}")
            st = status.get("status", "unknown")
            if st == "completed":
                result = status.get("result")
                print(f"  ✅ OCR completed")
                break
            elif st == "failed":
                print(f"  ❌ OCR failed: {status.get('error', 'unknown')}")
                break
            if i % 10 == 0:
                print(f"  ... polling ({i*3}s)")
        else:
            print(f"  ⚠️ OCR poll timeout")
            continue

        if not result:
            continue

        # Step 3: save JSON
        out_dir = project_root / "data" / "ocr_outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{pdf.stem}_ocr.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"  💾 Saved: {out_file.name}")

        # Step 4: auto import
        is_price = any(k in pdf.name for k in ["价格", "信息价", "造价"])
        if is_price:
            print(f"  📊 Detected price doc, importing to price_records...")
            script = project_root / "src" / "backend" / "python-legacy" / "tools" / "ocr_json_to_pg.py"
            # 直接调用函数而非子进程
            import subprocess
            r = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(project_root),
                capture_output=True, text=True, timeout=300
            )
            if r.returncode == 0:
                print(f"  ✅ Import done")
            else:
                print(f"  ⚠️ Import output: {r.stdout[-200:] if r.stdout else ''}")
        else:
            print(f"  📄 Detected text doc, importing to text_chunks...")
            script = project_root / "src" / "backend" / "python-legacy" / "tools" / "ocr_text_to_pg.py"
            import subprocess
            r = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(project_root),
                capture_output=True, text=True, timeout=300
            )
            if r.returncode == 0:
                print(f"  ✅ Import done")
            else:
                print(f"  ⚠️ Import output: {r.stdout[-200:] if r.stdout else ''}")

    print("\n🏁 Upload batch finished")
    return 0


def cmd_chat(args):
    """单次或交互式问答"""
    if args.query:
        res = _curl("POST", f"{API_URL}/api/v1/agent", {"query": args.query, "max_iterations": 3})
        print(res.get("answer", "无回答"))
        return 0

    print("🧠 RAG Chat (exit / Ctrl+D 退出)")
    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if q.lower() in ("exit", "quit", "q"):
            break
        if not q:
            continue
        res = _curl("POST", f"{API_URL}/api/v1/agent", {"query": q, "max_iterations": 3})
        print(res.get("answer", "无回答"))
        ev = res.get("evaluation", {})
        if ev:
            print(f"  [conf={ev.get('confidence',0):.2f} iter={res.get('iterations',1)} chunks={len(res.get('chunks',[]))}]")
        print()
    return 0


def cmd_check(args):
    """PG 自检 + 服务健康 + 数据统计"""
    import psycopg2

    print("═" * 50)
    print("RAG 系统自检")
    print("═" * 50)

    # 1. PG 连接
    pg_ok = False
    try:
        conn = psycopg2.connect(
            host=os.environ.get("PG_HOST", "localhost"),
            port=int(os.environ.get("PG_PORT", "5432")),
            database=os.environ.get("PG_DB", "rag_db"),
            user=os.environ.get("PG_USER", "rag_user"),
            password=os.environ.get("PG_PASSWORD", "rag_password"),
        )
        pg_ok = True
        print("✅ PostgreSQL: connected")
    except Exception as e:
        print(f"❌ PostgreSQL: {e}")

    if pg_ok:
        cur = conn.cursor()
        # pgvector
        cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        row = cur.fetchone()
        print(f"   pgvector: {row[0] if row else 'NOT INSTALLED'}")

        # 表行数
        cur.execute("SELECT count(*) FROM price_records")
        n_price = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM text_chunks")
        n_text = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM document_registry")
        n_reg = cur.fetchone()[0]

        print(f"   price_records: {n_price} rows")
        print(f"   text_chunks:   {n_text} rows")
        print(f"   document_registry: {n_reg} rows")

        # 按年月分布
        cur.execute("SELECT year_month, count(*) FROM price_records GROUP BY year_month ORDER BY year_month")
        print("\n   价格数据分布:")
        for ym, c in cur.fetchall():
            print(f"      {ym or 'N/A'}: {c} 条")

        conn.close()

    # 2. 服务健康
    print("\n服务健康:")
    services = {
        "retrieval": f"{API_URL}/health",
        "ocr": f"{OCR_URL}/health",
    }
    for name, url in services.items():
        try:
            r = _curl("GET", url)
            status = r.get("status", "unknown")
            print(f"   {name}: {status}")
        except Exception as e:
            print(f"   {name}: error ({e})")

    print("═" * 50)
    return 0


def main():
    parser = argparse.ArgumentParser(prog="rag", description="RAG CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # upload
    p_up = sub.add_parser("upload", help="PDF → OCR → import PG")
    p_up.add_argument("path", help="PDF file or directory")
    p_up.set_defaults(func=cmd_upload)

    # chat
    p_chat = sub.add_parser("chat", help="问答")
    p_chat.add_argument("-q", "--query", help="单次问答")
    p_chat.set_defaults(func=cmd_chat)

    # check
    p_check = sub.add_parser("check", help="系统自检")
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

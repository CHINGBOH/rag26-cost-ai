#!/usr/bin/env python3
"""
OCR Batch Scanner — 批量PDF扫描工具
调用 OCR 服务 (http://localhost:8001) 扫描 knowledge_base 目录下的所有 PDF，
输出 JSON 结果到 data/ocr_outputs/<category>/<filename>.json

用法:
    python3 ocr_tools/batch_scan.py                  # 扫描所有未处理的 PDF
    python3 ocr_tools/batch_scan.py --force           # 强制重新扫描已完成的
    python3 ocr_tools/batch_scan.py --status          # 查看当前进度
    python3 ocr_tools/batch_scan.py --pdf <path>      # 只扫描单个文件
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

# ── 配置 ────────────────────────────────────────────────────────────────────
OCR_SERVICE = "http://localhost:8001"
KB_ROOT     = Path(__file__).parent.parent / "data" / "knowledge_base"
OUT_ROOT    = Path(__file__).parent.parent / "data" / "ocr_outputs"
STATE_FILE  = OUT_ROOT / "_scan_state.json"

SYNC_PAGE_LIMIT   = 30          # ≤30页用同步接口
POLL_INTERVAL     = 15          # 秒，轮询间隔
MAX_POLL_ATTEMPTS = 600         # 最多等 600×15s = 150 分钟
UPLOAD_TIMEOUT    = 600         # 上传超时（大文件，900MB 需要较长时间）
SYNC_TIMEOUT      = 1800        # 同步接口超时


# ── 状态管理 ─────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def find_all_pdfs() -> list[Path]:
    return sorted(KB_ROOT.rglob("*.pdf"))


def output_path(pdf: Path) -> Path:
    """mirror knowledge_base folder structure under ocr_outputs"""
    rel = pdf.relative_to(KB_ROOT)
    out = OUT_ROOT / rel.parent / (rel.stem + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def page_count(pdf: Path) -> int:
    try:
        import fitz
        doc = fitz.open(str(pdf))
        n = len(doc)
        doc.close()
        return n
    except Exception:
        return -1


def health_check() -> bool:
    try:
        r = requests.get(f"{OCR_SERVICE}/health", timeout=5)
        return r.json().get("status") == "ok"
    except Exception:
        return False


# ── OCR 调用 ─────────────────────────────────────────────────────────────────

def ocr_sync(pdf: Path) -> dict:
    """小文件同步扫描"""
    with open(pdf, "rb") as f:
        r = requests.post(
            f"{OCR_SERVICE}/ocr/pdf",
            files={"file": (pdf.name, f, "application/pdf")},
            timeout=SYNC_TIMEOUT,
        )
    r.raise_for_status()
    return r.json()


def ocr_async(pdf: Path) -> dict:
    """大文件异步扫描，轮询至完成"""
    print(f"  上传中 ({pdf.stat().st_size // 1024 // 1024} MB)...")
    with open(pdf, "rb") as f:
        r = requests.post(
            f"{OCR_SERVICE}/ocr/pdf/async",
            files={"file": (pdf.name, f, "application/pdf")},
            timeout=UPLOAD_TIMEOUT,
        )
    r.raise_for_status()
    job_id = r.json()["job_id"]
    print(f"  Job ID: {job_id}")

    for attempt in range(MAX_POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL)
        status_r = requests.get(f"{OCR_SERVICE}/ocr/pdf/async/{job_id}", timeout=10)
        status_r.raise_for_status()
        job = status_r.json()
        pct = job.get("progress", {}).get("percent", 0)
        cur = job.get("progress", {}).get("current", 0)
        tot = job.get("progress", {}).get("total", 0)
        print(f"  [{attempt+1}] {job['status']} {pct}% ({cur}/{tot}页)", end="\r", flush=True)

        if job["status"] == "completed":
            print()
            return job["result"]
        if job["status"] == "failed":
            raise RuntimeError(f"Job failed: {job.get('error', 'unknown')}")

    raise TimeoutError(f"Job {job_id} did not finish within timeout")


def scan_pdf(pdf: Path, pages: int) -> dict:
    if 0 < pages <= SYNC_PAGE_LIMIT:
        return ocr_sync(pdf)
    return ocr_async(pdf)


# ── 主逻辑 ───────────────────────────────────────────────────────────────────

def cmd_status(state: dict, pdfs: list[Path]):
    done = [p for p in pdfs if str(p) in state and state[str(p)]["status"] == "done"]
    fail = [p for p in pdfs if str(p) in state and state[str(p)]["status"] == "error"]
    todo = [p for p in pdfs if str(p) not in state or state[str(p)]["status"] not in ("done",)]
    print(f"总计: {len(pdfs)} 个PDF")
    print(f"  ✅ 完成: {len(done)}")
    print(f"  ❌ 失败: {len(fail)}")
    print(f"  ⏳ 待处理: {len(todo)}")
    print()
    for p in done:
        s = state[str(p)]
        print(f"  ✅ {p.name}  ({s.get('pages','?')}页, {s.get('elapsed','?')}s)")
    for p in fail:
        s = state[str(p)]
        print(f"  ❌ {p.name}  {s.get('error','')}")
    for p in todo:
        pages = page_count(p)
        size = p.stat().st_size // 1024 // 1024
        print(f"  ⏳ {p.name}  ({pages}页, {size}MB)")


def run_scan(pdfs: list[Path], state: dict, force: bool):
    if not health_check():
        print("❌ OCR 服务未启动 (http://localhost:8001/health 无响应)")
        sys.exit(1)

    print(f"OCR 服务正常 ✅")
    to_scan = []
    for pdf in pdfs:
        key = str(pdf)
        if not force and key in state and state[key]["status"] == "done":
            out = output_path(pdf)
            if out.exists():
                continue
        to_scan.append(pdf)

    print(f"待扫描: {len(to_scan)} 个 (共 {len(pdfs)} 个)")
    print()

    for i, pdf in enumerate(to_scan, 1):
        pages = page_count(pdf)
        size_mb = pdf.stat().st_size // 1024 // 1024
        out = output_path(pdf)
        mode = "sync" if 0 < pages <= SYNC_PAGE_LIMIT else "async"
        print(f"[{i}/{len(to_scan)}] {pdf.name}  ({pages}页, {size_mb}MB, {mode})")

        t0 = time.time()
        try:
            result = scan_pdf(pdf, pages)
            elapsed = round(time.time() - t0)

            # 写入结果
            with open(out, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            # 统计
            total_blocks  = sum(len(p["text_blocks"]) for p in result.get("pages", []))
            total_tables  = sum(len(p.get("tables", [])) for p in result.get("pages", []))
            total_figures = sum(len(p.get("figures", [])) for p in result.get("pages", []))
            avg_conf      = (
                sum(p["confidence"] for p in result.get("pages", [])) / len(result["pages"])
                if result.get("pages") else 0
            )

            state[str(pdf)] = {
                "status": "done",
                "output": str(out),
                "pages": pages,
                "elapsed": elapsed,
                "text_blocks": total_blocks,
                "tables": total_tables,
                "figures": total_figures,
                "avg_confidence": round(avg_conf, 4),
            }
            save_state(state)

            print(f"  ✅ {elapsed}s | 文字块:{total_blocks} 表格:{total_tables} 图表:{total_figures} 置信度:{avg_conf:.2%}")
            print(f"  → {out}")

        except Exception as e:
            elapsed = round(time.time() - t0)
            state[str(pdf)] = {"status": "error", "error": str(e)[:300], "elapsed": elapsed}
            save_state(state)
            print(f"  ❌ 失败: {e}")

        print()


def main():
    parser = argparse.ArgumentParser(description="OCR Batch Scanner")
    parser.add_argument("--status", action="store_true", help="查看当前扫描进度")
    parser.add_argument("--force",  action="store_true", help="强制重新扫描已完成的文件")
    parser.add_argument("--pdf",    type=str,            help="只扫描指定PDF路径")
    args = parser.parse_args()

    state = load_state()

    if args.pdf:
        pdfs = [Path(args.pdf)]
    else:
        pdfs = find_all_pdfs()

    if not pdfs:
        print(f"未找到PDF文件 (搜索: {KB_ROOT})")
        sys.exit(0)

    if args.status:
        cmd_status(state, pdfs)
        return

    run_scan(pdfs, state, force=args.force)

    # 最终汇总
    state = load_state()
    done = sum(1 for v in state.values() if v.get("status") == "done")
    fail = sum(1 for v in state.values() if v.get("status") == "error")
    print(f"═══ 完成 ═══  ✅{done}  ❌{fail}  共{len(pdfs)}个")


if __name__ == "__main__":
    main()

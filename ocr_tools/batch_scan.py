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
SUMMARY_FILE = OUT_ROOT / "processing_summary.json"

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


def empty_route_metrics() -> dict:
    return {
        "native_pages": 0,
        "ocr_pages": 0,
        "hybrid_pages": 0,
        "second_pass_pages": 0,
        "total_ocr_attempts": 0,
        "total_pages": 0,
        "known_pages": 0,
    }


def extract_route_metrics(result: dict) -> dict:
    route_metrics = result.get("route_metrics")
    if isinstance(route_metrics, dict):
        metrics = empty_route_metrics()
        for key in metrics:
            if key == "known_pages":
                continue
            metrics[key] = int(route_metrics.get(key) or 0)
        metrics["known_pages"] = metrics["total_pages"]
        return metrics

    metrics = empty_route_metrics()
    pages = result.get("pages")
    if not isinstance(pages, list):
        return metrics

    metrics["total_pages"] = len(pages)
    for page in pages:
        route_info = page.get("route_info")
        if not isinstance(route_info, dict):
            continue

        metrics["known_pages"] += 1
        strategy = route_info.get("strategy")
        if strategy == "native":
            metrics["native_pages"] += 1
        elif strategy == "hybrid":
            metrics["hybrid_pages"] += 1
        elif strategy == "ocr":
            metrics["ocr_pages"] += 1

        metrics["total_ocr_attempts"] += int(route_info.get("ocr_attempts") or 0)
        if route_info.get("used_second_pass"):
            metrics["second_pass_pages"] += 1

    return metrics


def load_route_metrics_from_output(output_file: Path) -> dict:
    try:
        with open(output_file, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return empty_route_metrics()
    return extract_route_metrics(payload)


def backfill_state_route_metrics(state: dict, pdfs: list[Path]) -> bool:
    changed = False
    for pdf in pdfs:
        entry = state.get(str(pdf))
        if not isinstance(entry, dict) or entry.get("status") != "done":
            continue

        metrics = entry.get("route_metrics")
        if isinstance(metrics, dict) and int(metrics.get("known_pages") or 0) > 0:
            continue

        output_file = Path(entry.get("output") or output_path(pdf))
        loaded_metrics = load_route_metrics_from_output(output_file)
        if int(loaded_metrics.get("known_pages") or 0) <= 0:
            continue

        entry["route_metrics"] = loaded_metrics
        changed = True

    return changed


def summarize_state(state: dict, pdfs: list[Path]) -> dict:
    summary = {
        "files": {
            "total": len(pdfs),
            "done": 0,
            "error": 0,
            "todo": 0,
            "files_with_route_metrics": 0,
        },
        "route_metrics": empty_route_metrics(),
        "route_ratios": {
            "native_ratio": 0.0,
            "ocr_ratio": 0.0,
            "hybrid_ratio": 0.0,
        },
        "generated_at": int(time.time()),
    }

    for pdf in pdfs:
        entry = state.get(str(pdf))
        if not isinstance(entry, dict):
            summary["files"]["todo"] += 1
            continue

        status = entry.get("status")
        if status == "done":
            summary["files"]["done"] += 1
        elif status == "error":
            summary["files"]["error"] += 1
        else:
            summary["files"]["todo"] += 1
            continue

        metrics = entry.get("route_metrics") if status == "done" else None
        if not isinstance(metrics, dict):
            continue

        known_pages = int(metrics.get("known_pages") or 0)
        if known_pages <= 0:
            continue

        summary["files"]["files_with_route_metrics"] += 1
        for key in summary["route_metrics"]:
            summary["route_metrics"][key] += int(metrics.get(key) or 0)

    known_pages = summary["route_metrics"]["known_pages"]
    if known_pages > 0:
        summary["route_ratios"] = {
            "native_ratio": round(summary["route_metrics"]["native_pages"] / known_pages, 4),
            "ocr_ratio": round(summary["route_metrics"]["ocr_pages"] / known_pages, 4),
            "hybrid_ratio": round(summary["route_metrics"]["hybrid_pages"] / known_pages, 4),
        }

    return summary


def save_processing_summary(summary: dict):
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def print_route_summary(summary: dict):
    route_metrics = summary["route_metrics"]
    known_pages = route_metrics["known_pages"]
    if known_pages <= 0:
        print("  路由统计: 当前结果未提供 route metrics")
        return

    route_ratios = summary["route_ratios"]
    print(
        "  路由统计: "
        f"native={route_metrics['native_pages']} ({route_ratios['native_ratio']:.1%}) | "
        f"ocr={route_metrics['ocr_pages']} ({route_ratios['ocr_ratio']:.1%}) | "
        f"hybrid={route_metrics['hybrid_pages']} ({route_ratios['hybrid_ratio']:.1%})"
    )
    print(
        "            "
        f"second-pass={route_metrics['second_pass_pages']} | "
        f"ocr_attempts={route_metrics['total_ocr_attempts']} | "
        f"known_pages={known_pages}/{route_metrics['total_pages']}"
    )


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
    if backfill_state_route_metrics(state, pdfs):
        save_state(state)

    summary = summarize_state(state, pdfs)
    save_processing_summary(summary)

    done = [p for p in pdfs if str(p) in state and state[str(p)]["status"] == "done"]
    fail = [p for p in pdfs if str(p) in state and state[str(p)]["status"] == "error"]
    todo = [p for p in pdfs if str(p) not in state or state[str(p)]["status"] not in ("done",)]
    print(f"总计: {len(pdfs)} 个PDF")
    print(f"  ✅ 完成: {len(done)}")
    print(f"  ❌ 失败: {len(fail)}")
    print(f"  ⏳ 待处理: {len(todo)}")
    print_route_summary(summary)
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
            route_metrics = extract_route_metrics(result)

            state[str(pdf)] = {
                "status": "done",
                "output": str(out),
                "pages": pages,
                "elapsed": elapsed,
                "text_blocks": total_blocks,
                "tables": total_tables,
                "figures": total_figures,
                "avg_confidence": round(avg_conf, 4),
                "route_metrics": route_metrics,
            }
            save_state(state)
            save_processing_summary(summarize_state(state, pdfs))

            print(f"  ✅ {elapsed}s | 文字块:{total_blocks} 表格:{total_tables} 图表:{total_figures} 置信度:{avg_conf:.2%}")
            if route_metrics["known_pages"] > 0:
                print(
                    "     路由 | "
                    f"native:{route_metrics['native_pages']} "
                    f"ocr:{route_metrics['ocr_pages']} "
                    f"hybrid:{route_metrics['hybrid_pages']} "
                    f"second-pass:{route_metrics['second_pass_pages']}"
                )
            print(f"  → {out}")

        except Exception as e:
            elapsed = round(time.time() - t0)
            state[str(pdf)] = {"status": "error", "error": str(e)[:300], "elapsed": elapsed}
            save_state(state)
            save_processing_summary(summarize_state(state, pdfs))
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
    summary = summarize_state(state, pdfs)
    save_processing_summary(summary)
    done = summary["files"]["done"]
    fail = summary["files"]["error"]
    print(f"═══ 完成 ═══  ✅{done}  ❌{fail}  共{len(pdfs)}个")
    print_route_summary(summary)


if __name__ == "__main__":
    main()

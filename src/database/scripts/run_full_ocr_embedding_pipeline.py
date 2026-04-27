#!/usr/bin/env python3
"""
Run full OCR JSON -> pgvector embedding pipeline.

Pipeline:
1. Import OCR JSON into text chunks and structured tables.
2. Backfill chart page summaries and recovered prices.
3. Build parent/multi-vector views.
4. Build concept graph and concept-evidence links.
5. Backfill embeddings for all vector tables.
6. Run verification.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def run_step(step_name: str, cmd: list[str], env: dict[str, str]) -> None:
    print(f"\n=== {step_name} ===")
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full OCR embedding pipeline into pgvector.")
    parser.add_argument("--ocr-dir", default="", help="Override OCR_OUTPUT_DIR")
    parser.add_argument("--kb-dir", default="", help="Override KB_DIR for OCR JSON scanner")
    parser.add_argument(
        "--embedding-backend",
        default="sentence_transformers",
        choices=["sentence_transformers", "llama_cpp"],
        help="Embedding backend for backfill_embeddings.py",
    )
    parser.add_argument("--llama-url", default="", help="llama.cpp URL when embedding-backend=llama_cpp")
    parser.add_argument("--batch", type=int, default=64, help="Embedding backfill batch size")
    parser.add_argument("--skip-fee-import", action="store_true", help="Skip import_fee_rates.py")
    parser.add_argument("--skip-text-import", action="store_true", help="Skip ocr_text_to_pg.py")
    parser.add_argument("--skip-price-import", action="store_true", help="Skip ocr_json_to_pg.py")
    parser.add_argument("--skip-verify", action="store_true", help="Skip verify.py")
    parser.add_argument("--skip-metrics", action="store_true", help="Skip evaluate_retrieval_layers.py")
    parser.add_argument("--strict-metrics", action="store_true", help="Fail pipeline if metrics acceptance fails")
    args = parser.parse_args()

    env = os.environ.copy()
    env.setdefault("PG_HOST", "localhost")
    env.setdefault("PG_PORT", "5432")
    env.setdefault("PG_DB", "rag_db")
    env.setdefault("PG_USER", "rag_user")
    env.setdefault("PG_PASSWORD", "")
    env.setdefault("EMBEDDING_VECTOR_DIM", "1024")

    if args.ocr_dir:
        env["OCR_OUTPUT_DIR"] = args.ocr_dir
    if args.kb_dir:
        env["KB_DIR"] = args.kb_dir

    run_step(
        "Reconcile live OCR outputs",
        [sys.executable, "src/database/scripts/ocr_output_reconciliation.py"],
        env,
    )

    if not args.skip_fee_import:
        run_step(
            "Import fee rates",
            [sys.executable, "src/database/scripts/import_fee_rates.py"],
            env,
        )

    if not args.skip_text_import:
        run_step(
            "Import OCR text chunks into PostgreSQL",
            [sys.executable, "src/backend/python-legacy/tools/ocr_text_to_pg.py"],
            env,
        )

    if not args.skip_price_import:
        run_step(
            "Import OCR structured tables into PostgreSQL",
            [sys.executable, "src/backend/python-legacy/tools/ocr_json_to_pg.py"],
            env,
        )

    run_step(
        "Backfill chart summaries",
        [sys.executable, "src/database/scripts/backfill_chart_page_summaries.py"],
        env,
    )

    run_step(
        "Build chunk vector views",
        [sys.executable, "src/database/scripts/build_chunk_vector_views.py"],
        env,
    )

    run_step(
        "Build concept graph",
        [sys.executable, "src/database/scripts/build_concept_graph.py"],
        env,
    )

    embedding_backend = "sentence_transformers" if args.embedding_backend == "sentence_transformers" else "llama_cpp"
    backfill_cmds = [
        ["src/database/scripts/backfill_embeddings.py", "--table", "text_chunks"],
        ["src/database/scripts/backfill_embeddings.py", "--table", "price_records"],
        ["src/database/scripts/backfill_embeddings.py", "--table", "fee_rates"],
        ["src/database/scripts/backfill_embeddings.py", "--table", "canonical_concepts"],
        ["src/database/scripts/backfill_embeddings.py", "--table", "chunk_vector_views"],
    ]
    for cmd in backfill_cmds:
        full_cmd = [sys.executable, *cmd, "--backend", embedding_backend, "--batch", str(args.batch), "--limit", "0"]
        if embedding_backend == "llama_cpp" and args.llama_url:
            full_cmd.extend(["--llama-url", args.llama_url])
        run_step(f"Backfill embeddings for {cmd[2]}", full_cmd, env)

    if not args.skip_verify:
        run_step(
            "Verify database and retrieval infra",
            [sys.executable, "src/database/scripts/verify.py"],
            env,
        )

    if not args.skip_metrics:
        metrics_cmd = [sys.executable, "src/database/scripts/evaluate_retrieval_layers.py"]
        if args.strict_metrics:
            metrics_cmd.append("--strict")
        run_step("Evaluate retrieval acceptance metrics", metrics_cmd, env)

    print("\n✅ Full OCR embedding pipeline completed.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Backfill PostgreSQL pgvector embeddings for retrieval tables.

Usage:
    python src/database/scripts/backfill_embeddings.py --table fee_rates --backend auto --limit 0
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Sequence

import psycopg2
from psycopg2.extras import execute_batch


ROOT = Path(__file__).resolve().parents[3]

PG_CONFIG = {
    "host": os.environ.get("PG_HOST", "localhost"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "database": os.environ.get("PG_DB", "rag_db"),
    "user": os.environ.get("PG_USER", "rag_user"),
    "password": os.environ.get("PG_PASSWORD") or "",
}

_HF_MODEL_CANDIDATES = [
    ROOT / "models/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181",
    ROOT / "models/BAAI/bge-m3",
]

_GGUF_MODEL_CANDIDATES = [
    ROOT / "models/BAAI/bge-m3/bge-m3-q8_0.gguf",
    ROOT / "models/BAAI/bge-m3/bge-m3-f16.gguf",
    ROOT / "models/BAAI/bge-m3/ggml-model-q8_0.gguf",
    ROOT / "models/BAAI/bge-m3/ggml-model-f16.gguf",
]

_LLAMA_SERVER_CANDIDATES = [
    ROOT / "llama.cpp/build/bin/llama-server",
]

_LLAMA_LIBRARY_DIRS = [
    Path("/usr/local/lib/ollama/cuda_v12"),
    ROOT / "venv/lib/python3.13/site-packages/nvidia/cuda_runtime/lib",
    ROOT / "venv/lib/python3.13/site-packages/nvidia/cublas/lib",
    Path("/home/l/miniconda3/lib/python3.13/site-packages/nvidia/cuda_runtime/lib"),
    Path("/home/l/miniconda3/lib/python3.13/site-packages/nvidia/cublas/lib"),
]


def get_pg_conn():
    return psycopg2.connect(**PG_CONFIG)


def _first_existing(paths: Sequence[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _join_non_empty(parts: Sequence[object]) -> str:
    items = [str(part).strip() for part in parts if part not in (None, "", [])]
    return " | ".join(item for item in items if item)


def _format_rate(label: str, value: object) -> str:
    return f"{label}={value}" if value not in (None, "") else ""


def _build_price_record_text(row: tuple) -> str:
    return _join_non_empty((row[1], row[2]))


def _build_fee_rate_text(row: tuple) -> str:
    _, standard_year, fee_name, fee_category, base_formula, calc_base, scope, rate_min, rate_max, rate_recommended, source_text = row
    return _join_non_empty(
        (
            fee_name,
            fee_category,
            f"standard_year={standard_year}" if standard_year else "",
            f"base_formula={base_formula}" if base_formula else "",
            f"calc_base={calc_base}" if calc_base else "",
            f"applicable_scope={scope}" if scope else "",
            _format_rate("rate_min", rate_min),
            _format_rate("rate_max", rate_max),
            _format_rate("rate_recommended", rate_recommended),
            (source_text or "")[:400],
        )
    )


def _build_concept_text(row: tuple) -> str:
    _, concept_type, concept_name, aliases = row
    alias_text = ", ".join(aliases or [])
    return _join_non_empty((concept_type, concept_name, alias_text))


def _build_chunk_view_text(row: tuple) -> str:
    view_type = row[1]
    view_text = row[2]
    return _join_non_empty((view_type, (view_text or "")[:1200]))


def _default_update_params(row: tuple, embedding: list[float]) -> tuple[object, ...]:
    return (embedding, row[0])


def _default_row_units(row: tuple) -> int:
    return 1


TABLE_CONFIG: dict[str, dict[str, Any]] = {
    "text_chunks": {
        "select": "SELECT id, content FROM text_chunks WHERE embedding IS NULL ORDER BY id LIMIT %s",
        "update": "UPDATE text_chunks SET embedding = %s::vector WHERE id = %s",
        "text_fn": lambda row: (row[1] or "").strip(),
    },
    "price_records": {
        "select": (
            "SELECT id, material_name, specification "
            "FROM price_records WHERE embedding IS NULL ORDER BY id LIMIT %s"
        ),
        "update": "UPDATE price_records SET embedding = %s::vector WHERE id = %s",
        "text_fn": _build_price_record_text,
    },
    "fee_rates": {
        "select": (
            "SELECT id, standard_year, fee_name, fee_category, base_formula, calc_base, "
            "applicable_scope, rate_min, rate_max, rate_recommended, source_text "
            "FROM fee_rates WHERE embedding IS NULL ORDER BY id LIMIT %s"
        ),
        "update": "UPDATE fee_rates SET embedding = %s::vector WHERE id = %s",
        "text_fn": _build_fee_rate_text,
    },
    "canonical_concepts": {
        "select": (
            "SELECT id, concept_type, concept_name, aliases "
            "FROM canonical_concepts WHERE embedding IS NULL ORDER BY id LIMIT %s"
        ),
        "update": "UPDATE canonical_concepts SET embedding = %s::vector WHERE id = %s",
        "text_fn": _build_concept_text,
    },
    "chunk_vector_views": {
        "select": (
            "SELECT MIN(id) AS id, view_type, view_text, COUNT(*) AS group_size "
            "FROM chunk_vector_views WHERE embedding IS NULL "
            "GROUP BY view_type, view_text "
            "ORDER BY MIN(id) LIMIT %s"
        ),
        "update": (
            "UPDATE chunk_vector_views SET embedding = %s::vector "
            "WHERE embedding IS NULL AND view_type = %s AND view_text = %s"
        ),
        "text_fn": _build_chunk_view_text,
        "update_params_fn": lambda row, embedding: (embedding, row[1], row[2]),
        "row_units_fn": lambda row: int(row[3]),
    },
}

_ALLOWED_TABLES = frozenset(TABLE_CONFIG.keys())


class SentenceTransformerBackend:
    def __init__(self, model_path: Path | None = None):
        import torch
        from sentence_transformers import SentenceTransformer

        self._torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(
            f"使用设备: {self.device}"
            + (f" ({torch.cuda.get_device_name(0)})" if self.device == "cuda" else "")
        )

        resolved = model_path or _first_existing(_HF_MODEL_CANDIDATES)
        if resolved is None:
            raise FileNotFoundError("No local BAAI/bge-m3 model directory found for sentence-transformers.")

        self.model = SentenceTransformer(str(resolved), device=self.device)
        self.dimension = int(self.model.get_embedding_dimension())
        print(f"✓ sentence-transformers 模型加载成功 ({self.dimension}d): {resolved}")

    def encode(self, texts: list[str], batch_size: int) -> list[list[float]]:
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return embeddings.tolist()


class LlamaCppServerBackend:
    def __init__(
        self,
        model_path: Path | None = None,
        binary_path: Path | None = None,
        base_url: str | None = None,
        pooling: str | None = None,
    ):
        self.model_path = model_path or _first_existing(_GGUF_MODEL_CANDIDATES)
        self.binary_path = binary_path or _first_existing(_LLAMA_SERVER_CANDIDATES)
        self.pooling = pooling
        self.base_url = base_url.rstrip("/") if base_url else None
        self.process: subprocess.Popen[str] | None = None
        self.dimension: int | None = None

        if self.base_url is None:
            if self.model_path is None:
                raise FileNotFoundError(
                    "No GGUF embedding model found. Convert models/BAAI/bge-m3 to GGUF first."
                )
            if self.binary_path is None:
                raise FileNotFoundError("llama-server binary not found under llama.cpp/build/bin.")
            self.base_url = self._start_local_server()

        print(f"✓ llama.cpp embedding endpoint ready: {self.base_url}")

    def _start_local_server(self) -> str:
        port = _find_free_port()
        env = os.environ.copy()
        lib_dirs = [str(path) for path in _LLAMA_LIBRARY_DIRS if path.exists()]
        current_ld = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = ":".join([*lib_dirs, current_ld]).rstrip(":")

        cmd = [
            str(self.binary_path),
            "-m",
            str(self.model_path),
            "--embedding",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "-ub",
            "8192",
        ]
        if self.pooling:
            cmd.extend(["--pooling", self.pooling])

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            env=env,
        )
        atexit.register(self.close)

        base_url = f"http://127.0.0.1:{port}"
        self.base_url = base_url
        self._wait_until_ready(base_url)
        return base_url

    def _wait_until_ready(self, base_url: str, timeout_seconds: int = 180) -> None:
        deadline = time.time() + timeout_seconds
        last_error: Exception | None = None
        while time.time() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError("llama-server exited before becoming ready.")
            try:
                request = urllib.request.Request(url=f"{base_url}/health", method="GET")
                with urllib.request.urlopen(request, timeout=15) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if payload.get("status") == "ok":
                    return
            except urllib.error.HTTPError as exc:
                last_error = exc
            except Exception as exc:
                last_error = exc
            time.sleep(1.0)
        raise RuntimeError(f"Timed out waiting for llama-server at {base_url}: {last_error}")

    def _request_embeddings(self, base_url: str, texts: list[str]) -> list[list[float]]:
        body = {
            "input": texts,
            "model": self.model_path.name if self.model_path else "llama.cpp-embedding",
            "encoding_format": "float",
        }
        request = urllib.request.Request(
            url=f"{base_url}/v1/embeddings",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer no-key"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"llama.cpp embeddings request failed: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"llama.cpp embeddings endpoint unavailable: {exc}") from exc

        data = payload.get("data")
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected embeddings payload: {payload}")

        ordered = sorted(data, key=lambda item: item["index"])
        return [item["embedding"] for item in ordered]

    def encode(self, texts: list[str], batch_size: int) -> list[list[float]]:
        results: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            chunk = texts[start : start + batch_size]
            embeddings = self._request_embeddings(self.base_url, chunk)
            if embeddings:
                self.dimension = len(embeddings[0])
            results.extend(embeddings)
        return results

    def close(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None


def load_backend(
    backend_name: str,
    llama_model: str | None,
    llama_binary: str | None,
    llama_url: str | None,
    pooling: str | None,
):
    resolved_llama_model = Path(llama_model).expanduser() if llama_model else None
    resolved_llama_binary = Path(llama_binary).expanduser() if llama_binary else None

    if backend_name == "sentence_transformers":
        return SentenceTransformerBackend()

    if backend_name == "llama_cpp":
        return LlamaCppServerBackend(
            model_path=resolved_llama_model,
            binary_path=resolved_llama_binary,
            base_url=llama_url,
            pooling=pooling,
        )

    if llama_url or resolved_llama_model or _first_existing(_GGUF_MODEL_CANDIDATES):
        return LlamaCppServerBackend(
            model_path=resolved_llama_model,
            binary_path=resolved_llama_binary,
            base_url=llama_url,
            pooling=pooling,
        )

    return SentenceTransformerBackend()


def _check_table(table: str) -> None:
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Unknown table {table!r}. Allowed: {sorted(_ALLOWED_TABLES)}")


def count_missing(conn, table: str) -> tuple[int, int]:
    _check_table(table)
    from psycopg2 import sql as pgsql

    with conn.cursor() as cur:
        cur.execute(pgsql.SQL("SELECT COUNT(*) FROM {}").format(pgsql.Identifier(table)))
        total = cur.fetchone()[0]
        cur.execute(
            pgsql.SQL("SELECT COUNT(*) FROM {} WHERE embedding IS NULL").format(
                pgsql.Identifier(table)
            )
        )
        missing = cur.fetchone()[0]
    return total, missing


def backfill(
    table: str,
    batch_size: int,
    limit: int,
    dry_run: bool,
    backend_name: str,
    llama_model: str | None,
    llama_binary: str | None,
    llama_url: str | None,
    pooling: str | None,
) -> None:
    _check_table(table)
    cfg = TABLE_CONFIG[table]
    update_params_fn = cfg.get("update_params_fn", _default_update_params)
    row_units_fn = cfg.get("row_units_fn", _default_row_units)
    print(f"=== {table} embedding 补全 ===\n")

    conn = get_pg_conn()
    backend = None
    try:
        total, missing = count_missing(conn, table)
        pct_missing = (missing / total * 100) if total else 0.0
        print(f"总行数: {total:,}  缺 embedding: {missing:,}  ({pct_missing:.1f}%)\n")

        if missing == 0:
            print("✅ 无需补全，全部已有 embedding")
            return

        if dry_run:
            print("--dry-run 模式，退出")
            return

        backend = load_backend(backend_name, llama_model, llama_binary, llama_url, pooling)
        to_process = min(missing, limit) if limit > 0 else missing
        print(f"将补全 {to_process:,} 行，batch={batch_size}\n")

        done = 0
        errors = 0
        skipped_ids: list[int] = []
        t0 = time.time()

        adaptive_encode_batch_size = batch_size

        while done < to_process:
            fetch_n = min(batch_size, to_process - done)
            with conn.cursor() as cur:
                cur.execute(str(cfg["select"]), (fetch_n,))
                rows = cur.fetchall()

            if not rows:
                break

            ids = [row[0] for row in rows]
            row_units = [int(row_units_fn(row)) for row in rows]
            texts = [cfg["text_fn"](row) for row in rows]  # type: ignore[index]
            unique_texts: list[str] = []
            text_to_pos: dict[str, int] = {}
            text_positions: list[int] = []
            for text in texts:
                pos = text_to_pos.get(text)
                if pos is None:
                    pos = len(unique_texts)
                    text_to_pos[text] = pos
                    unique_texts.append(text)
                text_positions.append(pos)

            encode_batch_size = min(adaptive_encode_batch_size, len(unique_texts))
            while True:
                try:
                    unique_embeddings = backend.encode(unique_texts, batch_size=encode_batch_size)
                    adaptive_encode_batch_size = encode_batch_size
                    break
                except Exception as exc:
                    msg = str(exc).lower()
                    is_oom = "out of memory" in msg
                    if is_oom and encode_batch_size > 1:
                        encode_batch_size = max(1, encode_batch_size // 2)
                        adaptive_encode_batch_size = encode_batch_size
                        if hasattr(backend, "_torch") and getattr(backend, "device", "") == "cuda":
                            backend._torch.cuda.empty_cache()
                        print(
                            f"  ⚠ encode OOM (ids {ids[0]}~{ids[-1]}), retry batch_size={encode_batch_size}"
                        )
                        continue
                    print(f"  ✗ encode error (ids {ids[0]}~{ids[-1]}): {exc}")
                    errors += sum(row_units)
                    skipped_ids.extend(ids)
                    done += sum(row_units)
                    unique_embeddings = None
                    break

            if unique_embeddings is None:
                continue

            params = [
                update_params_fn(row, unique_embeddings[pos])
                for row, pos in zip(rows, text_positions)
            ]
            batch_units = sum(row_units)
            try:
                with conn.cursor() as cur:
                    execute_batch(
                        cur,
                        str(cfg["update"]),
                        params,
                        page_size=max(1, min(batch_size, len(params))),
                    )
                conn.commit()
                done += batch_units
            except Exception:
                conn.rollback()
                successful_units = 0
                with conn.cursor() as cur:
                    for row, param, row_unit in zip(rows, params, row_units):
                        try:
                            cur.execute(str(cfg["update"]), param)
                            successful_units += row_unit
                        except Exception as exc:
                            errors += row_unit
                            skipped_ids.append(row[0])
                            print(f"  ✗ update error id={row[0]}: {exc}")
                conn.commit()
                done += successful_units

            elapsed = time.time() - t0
            rate = done / elapsed if elapsed > 0 else 0.0
            eta = (to_process - done) / rate if rate > 0 else 0.0
            print(
                f"  {done:>6,}/{to_process:,}  {rate:.1f} rows/s  ETA {eta/60:.1f}min",
                end="\r",
                flush=True,
            )

        print()
        elapsed = time.time() - t0
        print(f"\n完成: {done:,} 行  错误: {errors}  耗时: {elapsed/60:.1f}min")
        if skipped_ids:
            preview = f"{skipped_ids[:10]}{'...' if len(skipped_ids) > 10 else ''}"
            print(f"  ⚠ 跳过 {len(skipped_ids)} 行 ids: {preview}")

        total2, missing2 = count_missing(conn, table)
        pct = (total2 - missing2) / total2 * 100 if total2 else 0.0
        print(f"embedding 覆盖率: {total2 - missing2:,}/{total2:,} = {pct:.1f}%")
    finally:
        conn.close()
        if backend is not None and hasattr(backend, "close"):
            backend.close()


def main():
    parser = argparse.ArgumentParser(description="Backfill table embeddings")
    parser.add_argument(
        "--table",
        default="text_chunks",
        choices=list(TABLE_CONFIG.keys()),
        help="Table to backfill",
    )
    parser.add_argument("--batch", type=int, default=32, help="Batch size (default 32)")
    parser.add_argument("--limit", type=int, default=0, help="Max rows (0=all)")
    parser.add_argument("--dry-run", action="store_true", help="Stats only, no DB writes")
    parser.add_argument(
        "--backend",
        default="auto",
        choices=["auto", "llama_cpp", "sentence_transformers"],
        help="Embedding backend",
    )
    parser.add_argument("--llama-model", help="Path to GGUF embedding model")
    parser.add_argument("--llama-binary", help="Path to llama-server binary")
    parser.add_argument("--llama-url", help="Existing llama.cpp server URL")
    parser.add_argument(
        "--pooling",
        choices=["auto", "mean", "cls", "last", "rank"],
        default="auto",
        help="Pooling strategy for llama.cpp embedding models; auto uses model metadata",
    )
    args = parser.parse_args()
    backfill(
        table=args.table,
        batch_size=args.batch,
        limit=args.limit,
        dry_run=args.dry_run,
        backend_name=args.backend,
        llama_model=args.llama_model,
        llama_binary=args.llama_binary,
        llama_url=args.llama_url,
        pooling=None if args.pooling == "auto" else args.pooling,
    )


if __name__ == "__main__":
    main()

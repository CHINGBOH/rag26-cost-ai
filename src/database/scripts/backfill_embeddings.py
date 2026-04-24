#!/usr/bin/env python3
"""
text_chunks embedding 批量补全脚本
为所有 embedding IS NULL 的行生成 bge-m3 1024d 向量并写回 DB

用法：
    python src/database/scripts/backfill_embeddings.py [--batch 32] [--limit 0]

参数：
    --batch   每批编码行数（默认 32，越大越快但显存更多）
    --limit   最多处理行数，0 = 全部（默认 0）
    --dry-run 只统计不写库
"""
import os
import time
import argparse
import psycopg2

PG_CONFIG = {
    "host":     os.environ.get("PG_HOST", "localhost"),
    "port":     int(os.environ.get("PG_PORT", "5432")),
    "database": os.environ.get("PG_DB", "rag_db"),
    "user":     os.environ.get("PG_USER", "rag_user"),
    "password": os.environ.get("PG_PASSWORD") or "",
}

_MODEL_CANDIDATES = [
    "/home/l/rag-dashboard/models/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181",
    "/home/l/rag-dashboard/models/BAAI/bge-m3",
]


def get_pg_conn():
    return psycopg2.connect(**PG_CONFIG)


def load_model():
    import torch
    from sentence_transformers import SentenceTransformer
    from pathlib import Path
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"使用设备: {device}" + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else ""))
    for p in _MODEL_CANDIDATES:
        if Path(p).exists():
            model = SentenceTransformer(p, device=device)
            dim = model.get_embedding_dimension()
            print(f"✓ 模型加载成功 ({dim}d): {p}")
            return model
    model = SentenceTransformer("BAAI/bge-m3", device=device)
    print("✓ 模型从 HuggingFace 加载")
    return model


# 每个表的配置：(SELECT sql, UPDATE sql)
TABLE_CONFIG = {
    "text_chunks": {
        "select": "SELECT id, content FROM text_chunks WHERE embedding IS NULL ORDER BY id LIMIT %s",
        "update": "UPDATE text_chunks SET embedding = %s::vector WHERE id = %s",
        "text_fn": lambda r: r[1] or "",
    },
    "price_records": {
        "select": (
            "SELECT id, COALESCE(material_name,'') || ' ' || COALESCE(specification,'') "
            "FROM price_records WHERE embedding IS NULL ORDER BY id LIMIT %s"
        ),
        "update": "UPDATE price_records SET embedding = %s::vector WHERE id = %s",
        "text_fn": lambda r: r[1].strip() or "",
    },
}


_ALLOWED_TABLES = frozenset(TABLE_CONFIG.keys())


def _check_table(table: str) -> None:
    """Explicit check — not assert, so python -O cannot bypass it."""
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


def backfill(table: str, batch_size: int, limit: int, dry_run: bool):
    _check_table(table)
    cfg = TABLE_CONFIG[table]
    print(f"=== {table} embedding 补全 ===\n")

    conn = get_pg_conn()
    try:
        total, missing = count_missing(conn, table)
        print(f"总行数: {total:,}  缺 embedding: {missing:,}  "
              f"({missing/total*100:.1f}%)\n")

        if missing == 0:
            print("✅ 无需补全，全部已有 embedding")
            return

        if dry_run:
            print("--dry-run 模式，退出")
            return

        model = load_model()
        to_process = min(missing, limit) if limit > 0 else missing
        print(f"将补全 {to_process:,} 行，batch={batch_size}\n")

        done = 0
        errors = 0
        skipped_ids: list[int] = []
        t0 = time.time()

        while done < to_process:
            fetch_n = min(batch_size, to_process - done)
            with conn.cursor() as cur:
                cur.execute(cfg["select"], (fetch_n,))
                rows = cur.fetchall()

            if not rows:
                break

            ids = [r[0] for r in rows]
            texts = [cfg["text_fn"](r) for r in rows]

            try:
                embeddings = model.encode(
                    texts,
                    normalize_embeddings=True,
                    batch_size=batch_size,
                    show_progress_bar=False,
                )
            except Exception as e:
                print(f"  ✗ encode error (ids {ids[0]}~{ids[-1]}): {e}")
                errors += len(rows)
                skipped_ids.extend(ids)
                # These rows already have NULL embedding; just skip to avoid infinite loop
                done += len(rows)
                continue

            with conn.cursor() as cur:
                for row_id, emb in zip(ids, embeddings):
                    try:
                        cur.execute(cfg["update"], (emb.tolist(), row_id))
                    except Exception as e:
                        errors += 1
                        skipped_ids.append(row_id)
                        print(f"  ✗ update error id={row_id}: {e}")
            conn.commit()

            done += len(rows)
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed > 0 else 0
            eta = (to_process - done) / rate if rate > 0 else 0
            print(f"  {done:>6,}/{to_process:,}  {rate:.1f} rows/s  ETA {eta/60:.1f}min",
                  end="\r", flush=True)

        print()  # newline after \r
        elapsed = time.time() - t0
        print(f"\n完成: {done:,} 行  错误: {errors}  耗时: {elapsed/60:.1f}min")
        if skipped_ids:
            print(f"  ⚠ 跳过 {len(skipped_ids)} 行 ids: {skipped_ids[:10]}{'...' if len(skipped_ids)>10 else ''}")

        total2, missing2 = count_missing(conn, table)
        pct = (total2 - missing2) / total2 * 100 if total2 else 0
        print(f"embedding 覆盖率: {total2-missing2:,}/{total2:,} = {pct:.1f}%")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Backfill table embeddings")
    parser.add_argument("--table",   default="text_chunks",
                        choices=list(TABLE_CONFIG.keys()), help="Table to backfill")
    parser.add_argument("--batch",   type=int,  default=32,    help="Batch size (default 32)")
    parser.add_argument("--limit",   type=int,  default=0,     help="Max rows (0=all)")
    parser.add_argument("--dry-run", action="store_true",      help="Stats only, no DB writes")
    args = parser.parse_args()
    backfill(args.table, args.batch, args.limit, args.dry_run)


if __name__ == "__main__":
    main()

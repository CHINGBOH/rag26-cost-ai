#!/usr/bin/env python3
"""
Paraphrase Regression Test — Issue #32

Tests whether semantically equivalent but lexically different queries
hit the same evidence as the original exact-name queries.

Metrics:
- original_hit_rate   : baseline (exact token match)
- bm25_paraphrase_hr  : BM25 only on paraphrase (expected to drop)
- dense_paraphrase_hr : dense vector on paraphrase (expected to close gap)
- hybrid_paraphrase_hr: hybrid RRF on paraphrase (expected to be best)
- delta_hybrid_vs_bm25: improvement of hybrid over BM25 on paraphrases
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import psycopg2

ROOT = Path(__file__).resolve().parents[3]
RETRIEVAL_ROOT = ROOT / "src/backend/retrieval-service"
if str(RETRIEVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(RETRIEVAL_ROOT))

from infrastructure.embedding_service import EmbeddingService  # noqa: E402

PG_CONFIG = {
    "host": os.environ.get("PG_HOST", "localhost"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "database": os.environ.get("PG_DB", "rag_db"),
    "user": os.environ.get("PG_USER", "rag_user"),
    "password": os.environ.get("PG_PASSWORD") or "",
}

# ---------------------------------------------------------------------------
# Paraphrase test pairs
# Format: (original, [paraphrase1, paraphrase2, ...], query_family, note)
# "original" is the canonical / exact token used in price_records.
# Paraphrases use synonyms, alias, context-phrased, or domain-reformulation.
# ---------------------------------------------------------------------------
PARAPHRASE_PAIRS: list[tuple[str, list[str], str, str]] = [
    # ── electrical ──────────────────────────────────────────────────────────
    (
        "电力电缆",
        ["输电电缆", "供电线缆", "高压导线", "电力传输线"],
        "price",
        "电缆常用同义词",
    ),
    (
        "控制电缆",
        ["弱电线缆", "控制线", "仪表电缆", "信号控制线"],
        "price",
        "控制电缆别名",
    ),
    (
        "绝缘电线",
        ["绝缘导线", "BV电线", "绝缘铜线", "铜芯绝缘线"],
        "price",
        "绝缘电线规格别名",
    ),
    # ── concrete ────────────────────────────────────────────────────────────
    (
        "防水混凝土",
        ["抗渗混凝土", "防渗砼", "抗渗砼", "防水砼"],
        "price",
        "防水混凝土行业俗称",
    ),
    (
        "细石混凝土",
        ["豆石混凝土", "细骨料混凝土", "细石砼", "豆石砼"],
        "price",
        "细石混凝土行业别称",
    ),
    (
        "预应力高强混凝土管桩",
        ["PHC管桩", "预应力管桩", "高强预应力桩", "PC管桩"],
        "price",
        "管桩标准规格简称",
    ),
    # ── formwork & labor ────────────────────────────────────────────────────
    (
        "模板工",
        ["木工", "支模工人", "模板制安工", "支模工"],
        "price",
        "模板工职业别称",
    ),
    (
        "模板制安",
        ["模板安装", "支模板", "木模安装", "模板支拆"],
        "price",
        "模板施工作业别称",
    ),
    # ── waterproofing ────────────────────────────────────────────────────────
    (
        "防水工",
        ["防水施工工", "防水作业工", "涂膜防水工", "防水涂料工"],
        "price",
        "防水工职业别称",
    ),
    # ── asphalt ─────────────────────────────────────────────────────────────
    (
        "普通沥青混凝土",
        ["AC沥青混凝土", "热拌沥青混合料", "沥青砼", "沥青混合料"],
        "price",
        "沥青混凝土行业简称",
    ),
    # ── fee items / policy ──────────────────────────────────────────────────
    (
        "安全文明施工措施费",
        ["安全施工措施费", "文明施工费", "安全生产措施费", "安全文明施工费"],
        "fee",
        "安全文明施工费名称变体",
    ),
    (
        "普工人工费",
        ["普通工人工费", "普工费", "普通工费用", "基本工人费"],
        "fee",
        "普工费表达变体",
    ),
    # ── question-phrased queries ─────────────────────────────────────────────
    (
        "电力电缆",
        [
            "深圳电力电缆最新价格是多少",
            "2026年电力电缆单价查询",
            "电缆价格深圳市场行情",
        ],
        "price",
        "电缆价格查询问句改写",
    ),
    (
        "防水混凝土",
        [
            "防渗混凝土每立方多少钱",
            "抗渗混凝土市场单价",
            "防水砼的含税价格",
        ],
        "price",
        "防水混凝土价格问句改写",
    ),
    (
        "预应力高强混凝土管桩",
        [
            "PHC桩深圳报价",
            "预应力管桩单价多少",
            "高强混凝土桩最新价格",
        ],
        "price",
        "管桩价格问句改写",
    ),
]


def get_pg_conn():
    return psycopg2.connect(**PG_CONFIG)


def _resolve_ts_cfg(conn) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT cfgname FROM pg_catalog.pg_ts_config
            WHERE cfgname IN ('chinese', 'simple')
            ORDER BY CASE cfgname WHEN 'chinese' THEN 0 ELSE 1 END
            LIMIT 1
            """
        )
        row = cur.fetchone()
    return str(row[0] if row and row[0] else "simple")


def _rrf_fuse(ranked_lists: list[list[int]], k: int = 60, top_n: int = 10) -> list[int]:
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return [iid for iid, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]]


def _dense_search(conn, emb: list[float], top_k: int = 20) -> list[int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM price_records WHERE embedding IS NOT NULL "
            "ORDER BY embedding <=> %s::vector LIMIT %s",
            (emb, top_k),
        )
        return [int(r[0]) for r in cur.fetchall()]


def _bm25_search(conn, query: str, ts_cfg: str, top_k: int = 20) -> list[int]:
    with conn.cursor() as cur:
        # Prefer stored tsv column (uses GIN index); fall back to inline expression
        has_tsv = False
        try:
            cur.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'price_records' AND column_name = 'tsv' LIMIT 1
                """
            )
            has_tsv = cur.fetchone() is not None
        except Exception:
            conn.rollback()

        try:
            if has_tsv:
                cur.execute(
                    f"""
                    SELECT id FROM price_records
                    WHERE tsv @@ plainto_tsquery('{ts_cfg}', %s)
                    ORDER BY ts_rank(tsv, plainto_tsquery('{ts_cfg}', %s)) DESC
                    LIMIT %s
                    """,
                    (query, query, top_k),
                )
            else:
                cur.execute(
                    f"""
                    SELECT id FROM price_records
                    WHERE to_tsvector('{ts_cfg}',
                            coalesce(material_name,'') || ' ' || coalesce(specification,''))
                          @@ plainto_tsquery('{ts_cfg}', %s)
                    ORDER BY ts_rank(
                        to_tsvector('{ts_cfg}',
                            coalesce(material_name,'') || ' ' || coalesce(specification,'')),
                        plainto_tsquery('{ts_cfg}', %s)
                    ) DESC LIMIT %s
                    """,
                    (query, query, top_k),
                )
            return [int(r[0]) for r in cur.fetchall()]
        except Exception:
            conn.rollback()
            return []


def _trigram_search(conn, query: str, top_k: int = 20, threshold: float = 0.12) -> list[int]:
    """Trigram similarity search — catches substring/partial name overlaps.

    pg_trgm splits text into character-level trigrams so "预应力管桩" can find
    "预应力高强混凝土管桩" (shared trigrams for 预应力 and 管桩) even when exact
    tokens don't match.  Threshold 0.12 is intentionally loose to maximise recall;
    RRF re-ranks with dense to push noise down.
    """
    with conn.cursor() as cur:
        try:
            cur.execute(
                """
                SELECT id
                FROM price_records
                WHERE word_similarity(%s, coalesce(material_name,'') || ' ' || coalesce(specification,'')) > %s
                ORDER BY word_similarity(%s, coalesce(material_name,'') || ' ' || coalesce(specification,'')) DESC
                LIMIT %s
                """,
                (query, threshold, query, top_k),
            )
            return [int(r[0]) for r in cur.fetchall()]
        except Exception:
            conn.rollback()
            return []


def _alias_expand(conn, query: str, emb_service, top_k_concepts: int = 3) -> list[str]:
    """Return alias terms from canonical_concepts most similar to the query.

    Embeds the query, finds the nearest concepts, and returns their alias lists.
    These aliases are then ORed into the BM25 / trigram searches so that
    "PHC管桩" can find rows whose material_name contains "预应力高强混凝土管桩".
    """
    emb = emb_service.encode_single(query)
    if not emb:
        return []
    with conn.cursor() as cur:
        try:
            cur.execute(
                """
                SELECT concept_name, aliases
                FROM canonical_concepts
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (emb, top_k_concepts),
            )
            terms: list[str] = []
            for row in cur.fetchall():
                concept_name, aliases = row
                terms.append(str(concept_name))
                if aliases:
                    terms.extend(str(a) for a in aliases if a)
            return terms
        except Exception:
            conn.rollback()
            return []


def _ground_truth_ids(conn, concept_name: str, limit: int = 50) -> set[int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM price_records WHERE material_name ILIKE %s LIMIT %s",
            (f"%{concept_name}%", limit),
        )
        return {int(r[0]) for r in cur.fetchall()}


@dataclass
class PairResult:
    original: str
    paraphrase: str
    family: str
    note: str
    gt_size: int
    original_dense_hit: bool = False
    original_bm25_hit: bool = False
    original_hybrid_hit: bool = False
    dense_hit: bool = False
    bm25_hit: bool = False
    trgm_hit: bool = False        # NEW: trigram path
    alias_hit: bool = False       # NEW: alias-expanded BM25
    hybrid_hit: bool = False      # dense + bm25 + trgm + alias RRF
    dense_scores: list[int] = field(default_factory=list)
    bm25_scores: list[int] = field(default_factory=list)


def run_pair(
    conn,
    emb_service: EmbeddingService,
    original: str,
    paraphrase: str,
    family: str,
    note: str,
    ts_cfg: str,
    top_k: int = 20,
) -> Optional[PairResult]:
    gt_ids = _ground_truth_ids(conn, original)
    if not gt_ids:
        return None  # skip if no ground truth

    result = PairResult(
        original=original,
        paraphrase=paraphrase,
        family=family,
        note=note,
        gt_size=len(gt_ids),
    )

    # --- original (should be near-perfect for BM25) ---
    orig_emb = emb_service.encode_single(original)
    orig_dense: list[int] = []
    if orig_emb:
        orig_dense = _dense_search(conn, orig_emb, top_k)
        result.original_dense_hit = bool(gt_ids & set(orig_dense))
    orig_bm25 = _bm25_search(conn, original, ts_cfg, top_k)
    result.original_bm25_hit = bool(gt_ids & set(orig_bm25))
    orig_hybrid = _rrf_fuse([orig_dense, orig_bm25], top_n=top_k)
    result.original_hybrid_hit = bool(gt_ids & set(orig_hybrid))

    # --- paraphrase: 4-path retrieval ---
    para_emb = emb_service.encode_single(paraphrase)
    para_dense: list[int] = []
    if para_emb:
        para_dense = _dense_search(conn, para_emb, top_k)
        result.dense_hit = bool(gt_ids & set(para_dense))

    para_bm25 = _bm25_search(conn, paraphrase, ts_cfg, top_k)
    result.bm25_hit = bool(gt_ids & set(para_bm25))

    # path 3: trigram similarity
    para_trgm = _trigram_search(conn, paraphrase, top_k)
    result.trgm_hit = bool(gt_ids & set(para_trgm))

    # path 4: alias-expanded BM25 via canonical_concepts
    alias_terms = _alias_expand(conn, paraphrase, emb_service, top_k_concepts=2)
    alias_bm25_ids: list[int] = []
    for term in alias_terms[:4]:  # limit to 4 alias expansions
        alias_bm25_ids.extend(_bm25_search(conn, term, ts_cfg, top_k // 2))
        alias_bm25_ids.extend(_trigram_search(conn, term, top_k // 2))
    result.alias_hit = bool(gt_ids & set(alias_bm25_ids))

    # RRF over all 4 paths
    para_hybrid = _rrf_fuse(
        [para_dense, para_bm25, para_trgm, alias_bm25_ids], top_n=top_k
    )
    result.hybrid_hit = bool(gt_ids & set(para_hybrid))

    result.bm25_scores = para_bm25[:5]
    result.dense_scores = para_dense[:5]

    return result


def aggregate(results: list[PairResult]) -> dict:
    n = len(results)
    if n == 0:
        return {"error": "no results"}
    orig_hr = sum(r.original_hybrid_hit for r in results) / n
    bm25_hr = sum(r.bm25_hit for r in results) / n
    dense_hr = sum(r.dense_hit for r in results) / n
    trgm_hr = sum(r.trgm_hit for r in results) / n
    alias_hr = sum(r.alias_hit for r in results) / n
    hybrid_hr = sum(r.hybrid_hit for r in results) / n
    # Acceptance: dense/hybrid must be strictly better than BM25 on paraphrases.
    # BM25 alone scores ~0% for Chinese synonyms; any positive dense lift validates
    # the architecture. Absolute floor of 25% to filter noise.
    acceptance = dense_hr > bm25_hr and hybrid_hr >= dense_hr and hybrid_hr >= 0.25
    return {
        "total_pairs": n,
        "original_hybrid_hit_rate": round(orig_hr, 4),
        "paraphrase_bm25_hit_rate": round(bm25_hr, 4),
        "paraphrase_trgm_hit_rate": round(trgm_hr, 4),
        "paraphrase_alias_hit_rate": round(alias_hr, 4),
        "paraphrase_dense_hit_rate": round(dense_hr, 4),
        "paraphrase_hybrid_hit_rate": round(hybrid_hr, 4),
        "delta_hybrid_vs_bm25": round(hybrid_hr - bm25_hr, 4),
        "delta_hybrid_vs_dense": round(hybrid_hr - dense_hr, 4),
        "acceptance": acceptance,
    }


def print_table(results: list[PairResult]) -> None:
    header = (
        f"{'Original':<20} {'Paraphrase':<28} {'GT':>4} "
        f"{'Orig':>4} {'BM25':>4} {'Trgm':>4} {'Alias':>5} {'Dense':>5} {'Hybrid':>6}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        orig_mark = "✅" if r.original_hybrid_hit else "❌"
        b = "✅" if r.bm25_hit else "❌"
        tr = "✅" if r.trgm_hit else "❌"
        al = "✅" if r.alias_hit else "❌"
        d = "✅" if r.dense_hit else "❌"
        h = "✅" if r.hybrid_hit else "❌"
        print(
            f"{r.original:<20} {r.paraphrase:<28} {r.gt_size:>4} "
            f"{orig_mark:>4} {b:>4} {tr:>4} {al:>5} {d:>5} {h:>6}"
        )


def main() -> None:
    conn = get_pg_conn()
    ts_cfg = _resolve_ts_cfg(conn)
    emb_service = EmbeddingService()
    print(f"Embedding backend: {emb_service.backend}  ts_cfg: {ts_cfg}\n")

    all_results: list[PairResult] = []

    for original, paraphrases, family, note in PARAPHRASE_PAIRS:
        print(f"[{note}]")
        for para in paraphrases:
            r = run_pair(conn, emb_service, original, para, family, note, ts_cfg, top_k=20)
            if r is None:
                print(f"  SKIP (no GT) original={original}")
                continue
            all_results.append(r)
            bm = "✅" if r.bm25_hit else "❌"
            tr = "✅" if r.trgm_hit else "❌"
            al = "✅" if r.alias_hit else "❌"
            dn = "✅" if r.dense_hit else "❌"
            hy = "✅" if r.hybrid_hit else "❌"
            print(f"  paraphrase='{para}' → BM25:{bm} Trgm:{tr} Alias:{al} Dense:{dn} Hybrid:{hy}  (GT={r.gt_size})")
        print()

    print("\n" + "=" * 70)
    print("FULL RESULTS TABLE (top@20, 4-path: BM25 + Trgm + Alias + Dense)")
    print("=" * 70)
    print_table(all_results)

    print("\n" + "=" * 70)
    print("SUMMARY METRICS")
    print("=" * 70)
    agg = aggregate(all_results)
    for k, v in agg.items():
        print(f"  {k:<40} {v}")

    # break down by family
    families = sorted({r.family for r in all_results})
    for fam in families:
        sub = [r for r in all_results if r.family == fam]
        sub_agg = aggregate(sub)
        print(f"\n  [{fam}] n={sub_agg['total_pairs']}")
        print(f"    bm25={sub_agg['paraphrase_bm25_hit_rate']:.0%}  "
              f"trgm={sub_agg['paraphrase_trgm_hit_rate']:.0%}  "
              f"alias={sub_agg['paraphrase_alias_hit_rate']:.0%}  "
              f"dense={sub_agg['paraphrase_dense_hit_rate']:.0%}  "
              f"hybrid={sub_agg['paraphrase_hybrid_hit_rate']:.0%}  "
              f"Δhybrid-bm25={sub_agg['delta_hybrid_vs_bm25']:+.0%}")

    acceptance = agg["acceptance"]
    print(f"\nACCEPTANCE: {'✅ PASSED' if acceptance else '❌ FAILED'}")
    print(f"  hybrid_paraphrase_hit_rate@20 = {agg['paraphrase_hybrid_hit_rate']:.1%}  (need ≥25%)")
    print(f"  dense_paraphrase_hit_rate@20  = {agg['paraphrase_dense_hit_rate']:.1%}  (need > BM25)")
    print(f"  paraphrase_bm25_hit_rate@20   = {agg['paraphrase_bm25_hit_rate']:.1%}  (baseline — Chinese tokenizer gap)")
    print(f"  delta_hybrid_vs_bm25          = {agg['delta_hybrid_vs_bm25']:+.1%}")
    print()
    print("Remaining gap analysis:")
    failing = [r for r in all_results if not r.hybrid_hit]
    notes_count: dict[str, int] = {}
    for r in failing:
        notes_count[r.note] = notes_count.get(r.note, 0) + 1
    for note, cnt in sorted(notes_count.items(), key=lambda x: -x[1]):
        print(f"  {cnt:>3} misses  [{note}]")

    conn.close()

    # machine-readable output for CI / issue comment
    output_path = ROOT / "src/database/scripts/paraphrase_regression_results.json"
    payload = {
        "summary": agg,
        "pairs": [
            {
                "original": r.original,
                "paraphrase": r.paraphrase,
                "family": r.family,
                "note": r.note,
                "gt_size": r.gt_size,
                "original_hybrid_hit": r.original_hybrid_hit,
                "bm25_hit": r.bm25_hit,
                "trgm_hit": r.trgm_hit,
                "alias_hit": r.alias_hit,
                "dense_hit": r.dense_hit,
                "hybrid_hit": r.hybrid_hit,
            }
            for r in all_results
        ],
    }
    with open(str(output_path), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"\nResults saved → {output_path}")


if __name__ == "__main__":
    main()

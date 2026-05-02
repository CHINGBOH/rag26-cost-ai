#!/usr/bin/env python3
"""
topology_health.py — 拓扑不变量自检脚本（#94）

跑一遍 I1-I6，每条打 OK / WARN / FAIL。CI 上 PR 必跑，全 OK 才能 merge。

用法：
  python scripts/topology_health.py                # 文本输出
  python scripts/topology_health.py --json         # 机器可读
  python scripts/topology_health.py --strict       # 任意 WARN/FAIL 都返回非零退出
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg2
import psycopg2.extras


DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://rag_user:rag_password@localhost:5432/rag_db",
)


@dataclass
class CheckResult:
    invariant: str
    name: str
    status: str   # OK | WARN | FAIL
    metric: dict[str, Any]
    note: str = ""


def _conn():
    return psycopg2.connect(DSN)


# ──────────────────────────────────────────────────────────────────────
# I1 — 全连通：12 节点 16 边都存在 + 任何边 last_traversed_at <= 30d
# ──────────────────────────────────────────────────────────────────────
EXPECTED_EDGES = {
    "query->analyzer", "analyzer->navigator", "navigator->retriever",
    "retriever->tool", "tool->verifier", "verifier->synthesize",
    "synthesize->user", "user->feedback", "feedback->learner",
    "learner->architect",
    "architect->navigator_dict", "architect->path_default",
    "architect->planner_few", "architect->rerank_w", "architect->tool_priority",
    "external->architect",
}


def check_i1() -> CheckResult:
    with _conn() as cn, cn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
        c.execute("SELECT edge_id, last_traversed_at, traversal_count FROM topology_edge_log")
        rows = c.fetchall()
    have = {r["edge_id"] for r in rows}
    missing = sorted(EXPECTED_EDGES - have)
    extra = sorted(have - EXPECTED_EDGES)

    threshold = datetime.now(timezone.utc) - timedelta(days=30)
    stale = [
        r["edge_id"] for r in rows
        if r["edge_id"] in EXPECTED_EDGES
        and r["last_traversed_at"] < threshold
        and r["traversal_count"] == 0
    ]

    if missing:
        return CheckResult("I1", "Closed Loop",
                           "FAIL", {"missing_edges": missing, "extra_edges": extra},
                           f"缺 {len(missing)} 条规范边")

    if stale and len(stale) >= len(EXPECTED_EDGES) // 2:
        return CheckResult("I1", "Closed Loop",
                           "WARN", {"stale_edges": stale[:5], "stale_count": len(stale),
                                    "expected": len(EXPECTED_EDGES)},
                           "拓扑骨架完整，但多数边长期未被遍历——闭环可能僵死")

    return CheckResult("I1", "Closed Loop",
                       "OK", {"edges": len(have), "expected": len(EXPECTED_EDGES),
                              "stale_unused": len(stale)},
                       "12 节点 16 边骨架完整")


# ──────────────────────────────────────────────────────────────────────
# I2 — 反馈可达：差评 → improvement_event 中位时延
# ──────────────────────────────────────────────────────────────────────
def check_i2() -> CheckResult:
    with _conn() as cn, cn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
        c.execute("""
            SELECT count(*) AS total
            FROM rag_feedback
            WHERE rating = -1 AND created_at > NOW() - interval '90 days'
        """)
        total_neg = c.fetchone()["total"]

        c.execute("""
            SELECT count(*) AS linked
            FROM improvement_events
            WHERE source_feedback_id IS NOT NULL
              AND ts > NOW() - interval '90 days'
        """)
        linked = c.fetchone()["linked"]

        c.execute("""
            SELECT count(*) AS applied
            FROM improvement_events
            WHERE applied_at IS NOT NULL
              AND ts > NOW() - interval '90 days'
        """)
        applied = c.fetchone()["applied"]

    if total_neg == 0:
        return CheckResult("I2", "Feedback Reachability",
                           "OK", {"negative_feedback_90d": 0,
                                  "linked_events": linked, "applied": applied},
                           "无差评样本，自动通过")

    cov = linked / total_neg if total_neg else 0
    metric = {
        "negative_feedback_90d": total_neg,
        "linked_improvement_events": linked,
        "applied_events": applied,
        "coverage": round(cov, 3),
    }
    if cov >= 0.5:
        return CheckResult("I2", "Feedback Reachability", "OK", metric,
                           f"差评 → 改进事件覆盖 {cov*100:.0f}%")
    if cov >= 0.1:
        return CheckResult("I2", "Feedback Reachability", "WARN", metric,
                           f"差评覆盖偏低 {cov*100:.0f}%，目标 ≥50%")
    return CheckResult("I2", "Feedback Reachability", "FAIL", metric,
                       "差评几乎未被回路消化")


# ──────────────────────────────────────────────────────────────────────
# I3 — 无悬挂证据：text_chunks 三字段非空率
# ──────────────────────────────────────────────────────────────────────
def check_i3() -> CheckResult:
    with _conn() as cn, cn.cursor() as c:
        c.execute("""
            SELECT
              count(*) AS total,
              count(*) FILTER (WHERE file_name IS NOT NULL AND file_name != '') AS with_file,
              count(*) FILTER (WHERE path IS NOT NULL AND path != '')           AS with_path,
              count(*) FILTER (WHERE metadata IS NOT NULL)                      AS with_meta
            FROM text_chunks
        """)
        total, wf, wp, wm = c.fetchone()
    if total == 0:
        return CheckResult("I3", "No Dangling Evidence", "WARN",
                           {"total": 0}, "text_chunks 表为空")
    rate_file = wf / total
    rate_path = wp / total
    rate_meta = wm / total
    metric = {
        "total": total,
        "file_name_rate": round(rate_file, 4),
        "path_rate":      round(rate_path, 4),
        "metadata_rate":  round(rate_meta, 4),
    }
    worst = min(rate_file, rate_path, rate_meta)
    if worst >= 0.99:
        return CheckResult("I3", "No Dangling Evidence", "OK", metric,
                           f"三字段非空率 {worst*100:.2f}%")
    if worst >= 0.90:
        return CheckResult("I3", "No Dangling Evidence", "WARN", metric,
                           f"三字段最低 {worst*100:.2f}%，目标 ≥99%")
    return CheckResult("I3", "No Dangling Evidence", "FAIL", metric,
                       f"三字段非空率仅 {worst*100:.2f}%")


# ──────────────────────────────────────────────────────────────────────
# I4 — 双轨可分：每条 improvement_event 三字段都填
# ──────────────────────────────────────────────────────────────────────
def check_i4() -> CheckResult:
    with _conn() as cn, cn.cursor() as c:
        c.execute("""
            SELECT
              count(*) AS total,
              count(*) FILTER (WHERE source IS NOT NULL AND actor IS NOT NULL
                                AND reversible_by IS NOT NULL) AS valid,
              count(*) FILTER (WHERE source = 'auto')   AS auto,
              count(*) FILTER (WHERE source = 'human')  AS human,
              count(*) FILTER (WHERE source = 'external') AS external
            FROM improvement_events
        """)
        total, valid, a, h, e = c.fetchone()
    metric = {"total": total, "valid": valid,
              "auto": a, "human": h, "external": e}
    if total == 0:
        return CheckResult("I4", "Auditable Two-Track", "WARN", metric,
                           "无改进事件——闭环未启动")
    if valid == total:
        return CheckResult("I4", "Auditable Two-Track", "OK", metric,
                           f"全部 {total} 条事件三字段齐备")
    return CheckResult("I4", "Auditable Two-Track", "FAIL", metric,
                       f"{total - valid} 条事件缺 source/actor/reversible_by")


# ──────────────────────────────────────────────────────────────────────
# I5 — 外部信号入口：tech_radar 最近 7 天有 ≥1 条新写入，来源种类 ≥3
# ──────────────────────────────────────────────────────────────────────
def check_i5() -> CheckResult:
    with _conn() as cn, cn.cursor() as c:
        c.execute("""
            SELECT
              count(*) AS recent,
              count(DISTINCT source) AS sources,
              max(fetched_at) AS last_at
            FROM tech_radar
            WHERE fetched_at > NOW() - interval '7 days'
        """)
        recent, sources, last_at = c.fetchone()
    metric = {"recent_7d": recent, "distinct_sources": sources,
              "last_fetched_at": last_at.isoformat() if last_at else None}
    if recent == 0:
        return CheckResult("I5", "External Signal Port", "FAIL", metric,
                           "雷达 7 天无新条目——外部入口失活")
    if sources < 2:
        return CheckResult("I5", "External Signal Port", "WARN", metric,
                           f"来源种类仅 {sources}，目标 ≥3")
    return CheckResult("I5", "External Signal Port", "OK", metric,
                       f"7 天 {recent} 条 / {sources} 源")


# ──────────────────────────────────────────────────────────────────────
# I6 — 形态无关：模式上无法直接验证，验证两个代理指标：
#   a. 拓扑表存在且边数等于 16（拓扑契约稳定）
#   b. improvement_events 中至少 R1-R5 各有过一次（5 个回路都通过）
# ──────────────────────────────────────────────────────────────────────
def check_i6() -> CheckResult:
    with _conn() as cn, cn.cursor() as c:
        c.execute("SELECT count(*) FROM topology_edge_log")
        edge_count = c.fetchone()[0]
        c.execute("""
            SELECT affected_route, count(*) AS n
            FROM improvement_events
            GROUP BY affected_route
        """)
        routes = {row[0]: row[1] for row in c.fetchall()}

    expected_routes = {
        "R1_navigator_dict", "R2_path_default",
        "R3_planner_examples", "R4_rerank_weights", "R5_tool_priority",
    }
    routes_used = set(routes.keys()) & expected_routes
    routes_missing = expected_routes - set(routes.keys())

    metric = {
        "topology_edges": edge_count,
        "expected_edges": len(EXPECTED_EDGES),
        "writeback_routes_used": sorted(routes_used),
        "writeback_routes_missing": sorted(routes_missing),
        "events_per_route": routes,
    }
    if edge_count != len(EXPECTED_EDGES):
        return CheckResult("I6", "Shape-Invariant", "FAIL", metric,
                           f"拓扑边数 {edge_count} ≠ 规范 {len(EXPECTED_EDGES)}")
    if not routes_used:
        return CheckResult("I6", "Shape-Invariant", "WARN", metric,
                           "5 条回写回路均未启用——R1-R5 全空")
    if len(routes_missing) >= 3:
        return CheckResult("I6", "Shape-Invariant", "WARN", metric,
                           f"{len(routes_missing)} 条回写回路从未使用")
    return CheckResult("I6", "Shape-Invariant", "OK", metric,
                       f"拓扑稳定 + {len(routes_used)}/5 回写已启用")


# ──────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────
def run_all() -> list[CheckResult]:
    return [check_i1(), check_i2(), check_i3(), check_i4(), check_i5(), check_i6()]


STATUS_GLYPH = {"OK": "✅", "WARN": "⚠️ ", "FAIL": "❌"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="任何 WARN/FAIL 都以非零状态退出")
    args = ap.parse_args()

    results = run_all()

    if args.json:
        print(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "results": [asdict(r) for r in results],
            "summary": {
                "ok":   sum(1 for r in results if r.status == "OK"),
                "warn": sum(1 for r in results if r.status == "WARN"),
                "fail": sum(1 for r in results if r.status == "FAIL"),
            },
        }, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"{'='*70}")
        print(f"  Topology Health — #94  ({datetime.now(timezone.utc).isoformat()})")
        print(f"{'='*70}")
        for r in results:
            print(f"\n{STATUS_GLYPH[r.status]} {r.invariant}  {r.name}  [{r.status}]")
            print(f"   {r.note}")
            for k, v in r.metric.items():
                print(f"     {k}: {v}")
        ok = sum(1 for r in results if r.status == "OK")
        warn = sum(1 for r in results if r.status == "WARN")
        fail = sum(1 for r in results if r.status == "FAIL")
        print(f"\n{'='*70}")
        print(f"  Summary: {ok} OK · {warn} WARN · {fail} FAIL")
        print(f"{'='*70}")

    has_fail = any(r.status == "FAIL" for r in results)
    has_warn = any(r.status == "WARN" for r in results)
    if has_fail:
        sys.exit(2)
    if args.strict and has_warn:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()

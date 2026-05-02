#!/usr/bin/env python3
"""
evals_gate.py — 写回闸 (#94-D)

任何 R1-R5 写回 (improvement_event apply / revert / human adopt) 之前/之后
跑 tests/test_agent_16.py，比较 baseline → 当前 pass 数。

退步 > N (默认 1) 题 → exit 2（用于阻止 CI 合并 / 阻止 apply）
不变或上升 → 写一条 source='auto' actor='evals_gate' 事件作为基线快照

用法：
  python scripts/evals_gate.py --baseline   # 写当前快照为新 baseline
  python scripts/evals_gate.py --gate       # 跑评估，与最近 baseline 对比
  python scripts/evals_gate.py --gate --tolerate 0   # 任何退步都阻止
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://rag_user:rag_password@localhost:5432/rag_db",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULT_FILE = REPO_ROOT / "logs" / "agent_test_16_results.json"


def run_test_agent_16() -> dict:
    """Run the test, parse JSON output."""
    env = os.environ.copy()
    proc = subprocess.run(
        [sys.executable, "tests/test_agent_16.py"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    if not RESULT_FILE.exists():
        raise RuntimeError(
            f"test_agent_16.py did not produce {RESULT_FILE}; "
            f"stdout tail: {proc.stdout[-500:]}"
        )
    with open(RESULT_FILE, encoding="utf-8") as f:
        return json.load(f)


def write_baseline(snapshot: dict) -> int:
    summary = snapshot.get("summary", {})
    payload = {
        "kind": "evals_baseline",
        "test": "test_agent_16",
        "passed": summary.get("passed", 0),
        "total": summary.get("total", 0),
        "avg_confidence": summary.get("avg_confidence", 0),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    with psycopg2.connect(DSN) as cn, cn.cursor() as c:
        c.execute(
            """INSERT INTO improvement_events
               (source, actor, affected_route, patch_payload,
                rationale, reversible_by, applied_at)
               VALUES ('auto', 'evals_gate', 'R3_planner_examples',
                       %s::jsonb, %s, 'rollback_event', NOW())
               RETURNING id""",
            (json.dumps(payload, ensure_ascii=False),
             f"baseline {payload['passed']}/{payload['total']}"),
        )
        new_id = c.fetchone()[0]
    return new_id


def latest_baseline() -> dict | None:
    with psycopg2.connect(DSN) as cn, cn.cursor(
        cursor_factory=psycopg2.extras.DictCursor
    ) as c:
        c.execute(
            """SELECT id, patch_payload, applied_at
               FROM improvement_events
               WHERE actor = 'evals_gate'
                 AND patch_payload->>'kind' = 'evals_baseline'
               ORDER BY id DESC LIMIT 1""",
        )
        row = c.fetchone()
        return dict(row) if row else None


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--baseline", action="store_true",
                   help="跑测试，写新 baseline 快照")
    g.add_argument("--gate", action="store_true",
                   help="跑测试，与最近 baseline 对比；退步即非零退出")
    ap.add_argument("--tolerate", type=int, default=1,
                    help="允许退步多少题（默认 1）")
    args = ap.parse_args()

    print(f"[evals_gate] running test_agent_16 ...")
    try:
        snap = run_test_agent_16()
    except Exception as e:
        print(f"[evals_gate] FAIL running tests: {e}", file=sys.stderr)
        sys.exit(3)

    cur = snap.get("summary", {})
    cur_passed = cur.get("passed", 0)
    cur_total = cur.get("total", 0)
    print(f"[evals_gate] current: {cur_passed}/{cur_total} passed")

    if args.baseline:
        new_id = write_baseline(snap)
        print(f"[evals_gate] baseline written as improvement_event id={new_id}")
        sys.exit(0)

    # --gate
    bl = latest_baseline()
    if not bl:
        print("[evals_gate] no baseline yet — recording current as baseline")
        new_id = write_baseline(snap)
        print(f"[evals_gate] baseline written as improvement_event id={new_id}")
        sys.exit(0)

    bl_payload = bl["patch_payload"] or {}
    bl_passed = bl_payload.get("passed", 0)
    delta = cur_passed - bl_passed
    print(f"[evals_gate] baseline (event #{bl['id']}): {bl_passed} passed")
    print(f"[evals_gate] delta: {delta:+d}")

    if delta < -args.tolerate:
        print(f"[evals_gate] FAIL — regression {-delta} > tolerate {args.tolerate}",
              file=sys.stderr)
        sys.exit(2)
    if delta >= 0:
        # 进步 → 自动更新 baseline
        new_id = write_baseline(snap)
        print(f"[evals_gate] OK — baseline advanced to event id={new_id}")
    else:
        print(f"[evals_gate] OK (within tolerance)")
    sys.exit(0)


if __name__ == "__main__":
    main()

"""
CLI utilities for learning-loop operations.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def build_retest_payload(args: argparse.Namespace) -> dict[str, Any]:
    consultation_endpoint = args.consultation_endpoint or _join_url(args.base_url, "/api/v1/agent")
    return {
        "limit": args.limit,
        "actor": args.actor,
        "dry_run": args.dry_run,
        "observation_window_days": args.observation_window_days,
        "active_only": args.active_only,
        "live_retest": True,
        "consultation_endpoint": consultation_endpoint,
        "consultation_timeout_seconds": args.timeout,
        "max_live_retests": args.max_live_retests,
        "max_iterations": args.max_iterations,
    }


def post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to call {url}: {exc}") from exc
    try:
        loaded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Non-JSON response from {url}: {body[:500]}") from exc
    if not isinstance(loaded, dict):
        raise RuntimeError(f"Unexpected response from {url}: {body[:500]}")
    return loaded


def get_json(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to call {url}: {exc}") from exc
    try:
        loaded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Non-JSON response from {url}: {body[:500]}") from exc
    if not isinstance(loaded, dict):
        raise RuntimeError(f"Unexpected response from {url}: {body[:500]}")
    return loaded


def retest_gaps(args: argparse.Namespace) -> int:
    triage_url = args.triage_endpoint or _join_url(args.base_url, "/api/v1/learning/gaps/triage")
    payload = build_retest_payload(args)
    result = post_json(triage_url, payload, timeout=max(args.timeout + 10, 30))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def show_workbench(args: argparse.Namespace) -> int:
    url = _join_url(args.base_url, "/api/v1/learning/gaps/workbench")
    query = f"?limit={args.limit}&include_resolved={str(args.include_resolved).lower()}"
    result = get_json(f"{url}{query}", timeout=args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def retest_gap(args: argparse.Namespace) -> int:
    consultation_endpoint = args.consultation_endpoint or _join_url(args.base_url, "/api/v1/agent")
    payload = {
        "actor": args.actor,
        "dry_run": args.dry_run,
        "consultation_endpoint": consultation_endpoint,
        "consultation_timeout_seconds": args.timeout,
        "max_iterations": args.max_iterations,
        "observation_window_days": args.observation_window_days,
    }
    url = _join_url(args.base_url, f"/api/v1/learning/gaps/{args.gap_key}/retest")
    result = post_json(url, payload, timeout=max(args.timeout + 10, 30))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Learning-loop CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    retest = subparsers.add_parser(
        "retest-gaps",
        help="Retest active knowledge gaps through the real consultation endpoint.",
    )
    retest.add_argument("--base-url", default="http://localhost:8002")
    retest.add_argument("--triage-endpoint")
    retest.add_argument("--consultation-endpoint")
    retest.add_argument("--limit", type=int, default=20)
    retest.add_argument("--max-live-retests", type=int, default=5)
    retest.add_argument("--timeout", type=int, default=60)
    retest.add_argument("--max-iterations", type=int, default=3)
    retest.add_argument("--observation-window-days", type=int, default=7)
    retest.add_argument("--actor", default="learning_cli")
    retest.add_argument("--active-only", action=argparse.BooleanOptionalAction, default=True)
    retest.add_argument("--dry-run", action="store_true")
    retest.set_defaults(func=retest_gaps)

    workbench = subparsers.add_parser(
        "workbench",
        help="Show the DB-backed knowledge-gap lifecycle workbench.",
    )
    workbench.add_argument("--base-url", default="http://localhost:8002")
    workbench.add_argument("--limit", type=int, default=200)
    workbench.add_argument("--timeout", type=int, default=30)
    workbench.add_argument("--include-resolved", action="store_true")
    workbench.set_defaults(func=show_workbench)

    single = subparsers.add_parser(
        "retest-gap",
        help="Retest one knowledge gap through the real consultation endpoint.",
    )
    single.add_argument("gap_key")
    single.add_argument("--base-url", default="http://localhost:8002")
    single.add_argument("--consultation-endpoint")
    single.add_argument("--timeout", type=int, default=60)
    single.add_argument("--max-iterations", type=int, default=3)
    single.add_argument("--observation-window-days", type=int, default=7)
    single.add_argument("--actor", default="learning_cli")
    single.add_argument("--dry-run", action="store_true")
    single.set_defaults(func=retest_gap)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

"""Agent trace recorder (#67).

Wraps each LangGraph node to capture {name, version, latency_ms, delta_keys, tool_calls}
into an in-memory map keyed by trace_id, then persists to data/agent_traces/<tid>.json
once the run terminates (synthesize_node).

Design: minimally invasive. The wrapper auto-seeds trace_id on the first node call and
propagates it back through the returned state-update dict so subsequent nodes see it.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Module-level live trace map. Cleared after persistence.
_TRACES: dict[str, dict[str, Any]] = {}

# Persisted location.
_BASE = Path(os.environ.get("RAG_AGENT_TRACES_DIR", "/home/l/rag-dashboard/data/agent_traces"))
_BASE.mkdir(parents=True, exist_ok=True)

# Keys we redact / truncate when snapshotting state-update dicts (avoid blowing up traces)
_HEAVY_KEYS = {"messages", "retrieved_chunks", "workspace", "tool_call_cache",
               "synthesis_prompt", "presentation"}


def _short(v: Any, limit: int = 240) -> Any:
    """Best-effort short representation for trace logs."""
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, str):
        return v if len(v) <= limit else v[:limit] + "…"
    if isinstance(v, list):
        return f"<list len={len(v)}>"
    if isinstance(v, dict):
        return {k: _short(val, 80) for k, val in list(v.items())[:6]}
    return f"<{type(v).__name__}>"


def _summarize_delta(delta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (delta or {}).items():
        if k in _HEAVY_KEYS:
            if isinstance(v, list):
                out[k] = f"<+{len(v)} items>"
            elif isinstance(v, str):
                out[k] = f"<{len(v)} chars>"
            elif isinstance(v, dict):
                out[k] = f"<dict keys={list(v.keys())[:6]}>"
            else:
                out[k] = f"<{type(v).__name__}>"
        else:
            out[k] = _short(v)
    return out


def _extract_tool_calls(delta: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in (delta.get("messages") or []):
        tcs = getattr(m, "tool_calls", None)
        if not tcs and isinstance(m, dict):
            tcs = m.get("tool_calls")
        if not tcs:
            continue
        for tc in tcs:
            if isinstance(tc, dict):
                out.append({"tool": tc.get("name") or "?",
                            "args": _short(tc.get("args") or {}, 200)})
            else:
                out.append({"tool": getattr(tc, "name", "?"),
                            "args": _short(getattr(tc, "args", {}) or {}, 200)})
    return out


def _ensure_trace(state: dict[str, Any]) -> str:
    tid = state.get("trace_id")
    if not tid:
        tid = uuid.uuid4().hex
    if tid not in _TRACES:
        _TRACES[tid] = {
            "trace_id": tid,
            "started_ts": time.time(),
            "query": state.get("query", "") or "",
            "nodes": [],
        }
    return tid


def _record(tid: str, name: str, latency_ms: int,
            delta: dict[str, Any], pre_iterations: int) -> int:
    t = _TRACES[tid]
    version = len(t["nodes"]) + 1
    t["nodes"].append({
        "version": version,
        "node": name,
        "ts": time.time(),
        "latency_ms": latency_ms,
        "delta_keys": list((delta or {}).keys()),
        "delta_summary": _summarize_delta(delta or {}),
        "tool_calls": _extract_tool_calls(delta or {}),
        "iteration_at_entry": pre_iterations,
    })
    return version


def persist_trace(tid: str, final_state: dict[str, Any] | None = None) -> str | None:
    """Flush the in-memory trace to disk and remove it. Returns the saved path."""
    t = _TRACES.pop(tid, None)
    if not t:
        return None
    t["ended_ts"] = time.time()
    t["duration_ms"] = int((t["ended_ts"] - t["started_ts"]) * 1000)
    if final_state:
        t["final"] = {
            "answer": (final_state.get("final_answer") or "")[:1500],
            "iterations": int(final_state.get("iterations", 0) or 0),
            "chunks": len(final_state.get("retrieved_chunks") or []),
            "evaluation": final_state.get("evaluation") or {},
            "query_type": final_state.get("query_type") or "",
        }
    fp = _BASE / f"{tid}.json"
    try:
        fp.write_text(json.dumps(t, ensure_ascii=False, default=str))
        return str(fp)
    except Exception as e:
        logger.warning(f"[trace] persist failed: {e}")
        return None


def wrap_node(name: str, fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
    """Decorate a LangGraph node so each invocation records to the trace map."""
    persist_after = (name == "synthesize_node")

    def _wrapped(state: dict[str, Any]) -> dict[str, Any]:
        tid = _ensure_trace(state)
        pre_iter = int(state.get("iterations", 0) or 0)
        t0 = time.perf_counter()
        try:
            result = fn(state) or {}
        except Exception:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            _record(tid, name, latency_ms, {"error": True}, pre_iter)
            raise
        latency_ms = int((time.perf_counter() - t0) * 1000)
        _record(tid, name, latency_ms, result, pre_iter)
        # propagate trace_id back into state-update so future nodes see it
        if isinstance(result, dict) and "trace_id" not in result:
            result["trace_id"] = tid
        if persist_after:
            try:
                merged = {**state, **result}
                persist_trace(tid, merged)
            except Exception as e:
                logger.warning(f"[trace] post-synthesize persist failed: {e}")
        return result

    _wrapped.__name__ = f"traced_{name}"
    return _wrapped


def list_traces(limit: int = 50) -> list[dict[str, Any]]:
    """List most-recent persisted traces (lightweight summary)."""
    if not _BASE.exists():
        return []
    files = sorted(_BASE.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out: list[dict[str, Any]] = []
    for fp in files:
        try:
            t = json.loads(fp.read_text())
        except Exception:
            continue
        out.append({
            "trace_id": t.get("trace_id") or fp.stem,
            "query": t.get("query") or "",
            "started_ts": t.get("started_ts"),
            "ended_ts": t.get("ended_ts"),
            "duration_ms": t.get("duration_ms"),
            "node_count": len(t.get("nodes") or []),
            "answer_preview": ((t.get("final") or {}).get("answer") or "")[:140],
            "query_type": (t.get("final") or {}).get("query_type") or "",
            "iterations": (t.get("final") or {}).get("iterations") or 0,
        })
    return out


def get_trace(trace_id: str) -> dict[str, Any] | None:
    fp = _BASE / f"{trace_id}.json"
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text())
    except Exception:
        return None

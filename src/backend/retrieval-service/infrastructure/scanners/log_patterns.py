"""
PostScanner pattern library for CodeExecutionPipeline.

Scans sandbox stdout/stderr/exit_code and produces a structured
LogAnalysisResult consumed by #166 (ERRORS.md) and #167 (Tool Guardrails).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PatternHit:
    category: str
    severity: str           # "hard_fail" | "soft_fail" | "info"
    pattern: str
    source: str             # "stdout" | "stderr" | "exit_code"
    excerpt: str = ""


@dataclass
class LogAnalysisResult:
    verdict: str            # "clean" | "soft_fail" | "hard_fail"
    matched_patterns: List[PatternHit] = field(default_factory=list)
    inferred_failure_kind: Optional[str] = None
    short_circuit_success: bool = False
    tail_excerpt: str = ""


# ── Pattern definitions ──────────────────────────────────────────────────────

_PATTERNS: list[tuple[str, str, str, str]] = [
    # (category, severity, regex, source_hint)
    # OOM
    ("oom",          "hard_fail", r"MemoryError",                     "stderr"),
    ("oom",          "hard_fail", r"Out of memory",                   "stderr"),
    # stack overflow
    ("stack_overflow","hard_fail", r"RecursionError",                 "stderr"),
    ("stack_overflow","hard_fail", r"maximum recursion depth",        "stderr"),
    ("stack_overflow","hard_fail", r"stack overflow",                 "stderr"),
    # segfault
    ("segfault",     "hard_fail", r"Segmentation fault",              "stderr"),
    # network
    ("network_attempt","hard_fail", r"socket\.gaierror",              "stderr"),
    ("network_attempt","hard_fail", r"Connection refused",            "stderr"),
    ("network_attempt","hard_fail", r"socket",                        "stderr"),
    # test failures
    ("test_failure", "soft_fail", r"AssertionError",                  "stdout"),
    ("test_failure", "soft_fail", r"pytest FAILED",                   "stdout"),
    ("test_failure", "soft_fail", r"expected .* got",                 "stdout"),
    ("test_failure", "soft_fail", r"\bFAILED\b",                      "stdout"),
    # test success (informational — used for short_circuit_success)
    ("test_pass",    "info",      r"OK \(test",                       "stdout"),
    ("test_pass",    "info",      r"\d+ passed",                      "stdout"),
    # secrets
    ("secret_exfil", "hard_fail", r"BEGIN RSA PRIVATE KEY",           "stdout"),
    ("secret_exfil", "hard_fail", r"AKIA[0-9A-Z]{16}",               "stdout"),
    # implicit failure: exit=0 but Traceback present
    ("implicit_fail","soft_fail", r"Traceback \(most recent call last\)", "stdout"),
]

_COMPILED = [
    (cat, sev, re.compile(pat, re.MULTILINE | re.IGNORECASE), src)
    for cat, sev, pat, src in _PATTERNS
]


# ── Verdict calculation ──────────────────────────────────────────────────────

def _infer_kind(hits: List[PatternHit]) -> Optional[str]:
    """Return the most specific inferred failure kind from the hit list."""
    for hit in hits:
        if hit.severity == "hard_fail":
            return hit.category
    for hit in hits:
        if hit.severity == "soft_fail":
            return hit.category
    return None


def scan_outcome(
    stdout: str,
    stderr: str,
    exit_code: int,
) -> LogAnalysisResult:
    """
    Scan sandbox output and return a structured LogAnalysisResult.

    Short-circuit success: exit_code == 0, verdict == "clean", stderr is empty.
    """
    hits: List[PatternHit] = []
    combined = {"stdout": stdout, "stderr": stderr}

    # Exit-code based hard fails
    if exit_code == 137:
        hits.append(PatternHit(
            category="oom", severity="hard_fail",
            pattern="exit_code=137", source="exit_code",
            excerpt=f"Process killed (OOM) exit_code={exit_code}",
        ))
    elif exit_code == 139:
        hits.append(PatternHit(
            category="segfault", severity="hard_fail",
            pattern="exit_code=139", source="exit_code",
            excerpt=f"Segmentation fault exit_code={exit_code}",
        ))

    # Pattern scan across stdout and stderr
    for cat, sev, compiled, src_hint in _COMPILED:
        for src_name, text in combined.items():
            if not text:
                continue
            m = compiled.search(text)
            if m:
                start = max(0, m.start() - 60)
                end = min(len(text), m.end() + 60)
                hits.append(PatternHit(
                    category=cat, severity=sev,
                    pattern=compiled.pattern, source=src_name,
                    excerpt=text[start:end].strip(),
                ))
                break  # one hit per pattern is enough

    # Implicit failure: exit_code=0 but Traceback in stdout
    if exit_code == 0 and re.search(r"Traceback \(most recent call last\)", stdout, re.MULTILINE):
        hits.append(PatternHit(
            category="implicit_fail", severity="soft_fail",
            pattern="Traceback (implicit)", source="stdout",
            excerpt=(stdout[-200:]).strip(),
        ))

    verdict: str
    if any(h.severity == "hard_fail" for h in hits):
        verdict = "hard_fail"
    elif any(h.severity == "soft_fail" for h in hits):
        verdict = "soft_fail"
    else:
        verdict = "clean"

    tail_excerpt = (stderr or stdout)[-300:].strip()

    short_circuit_success = (
        exit_code == 0
        and verdict == "clean"
        and not (stderr or "").strip()
    )

    return LogAnalysisResult(
        verdict=verdict,
        matched_patterns=hits,
        inferred_failure_kind=_infer_kind(hits),
        short_circuit_success=short_circuit_success,
        tail_excerpt=tail_excerpt,
    )

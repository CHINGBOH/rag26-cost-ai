#!/usr/bin/env python3
"""Run repository static analysis tools from one stable entrypoint."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


TOOL_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOL_DIR.parents[1]
REPORT_DIR = TOOL_DIR / "reports"
DEFAULT_PYCG_PYTHON = Path("/home/l/miniconda3/envs/rag-pycg310/bin/python")


@dataclass(frozen=True)
class AnalysisCommand:
    name: str
    group: str
    argv: list[str]
    output: Path | None = None
    required_binary: str | None = None


def resolve_pycg_python() -> str:
    env_python = os.environ.get("PYCG_PYTHON")
    if env_python:
        return env_python
    if DEFAULT_PYCG_PYTHON.exists():
        return str(DEFAULT_PYCG_PYTHON)
    discovered = shutil.which("python3.10")
    return discovered or "python3.10"


def command_groups() -> dict[str, list[AnalysisCommand]]:
    pycg_python = resolve_pycg_python()
    return {
        "deps": [
            AnalysisCommand(
                name="dependency-cruiser-json",
                group="deps",
                argv=[
                    str(TOOL_DIR / "node_modules" / ".bin" / "depcruise"),
                    "--no-config",
                    "--include-only",
                    "^(src|packages)",
                    "--output-type",
                    "json",
                    "src",
                    "packages",
                ],
                output=REPORT_DIR / "dependency-cruiser.json",
                required_binary=str(TOOL_DIR / "node_modules" / ".bin" / "depcruise"),
            ),
            AnalysisCommand(
                name="frontend-circular-deps",
                group="deps",
                argv=[
                    str(TOOL_DIR / "node_modules" / ".bin" / "madge"),
                    "--extensions",
                    "ts,tsx",
                    "--circular",
                    "src/frontend/web/src",
                ],
                output=REPORT_DIR / "frontend-madge-circular.txt",
                required_binary=str(TOOL_DIR / "node_modules" / ".bin" / "madge"),
            ),
            AnalysisCommand(
                name="server-circular-deps",
                group="deps",
                argv=[
                    str(TOOL_DIR / "node_modules" / ".bin" / "madge"),
                    "--extensions",
                    "ts",
                    "--circular",
                    "src/backend/server/src",
                ],
                output=REPORT_DIR / "server-madge-circular.txt",
                required_binary=str(TOOL_DIR / "node_modules" / ".bin" / "madge"),
            ),
            AnalysisCommand(
                name="retrieval-pydeps-json",
                group="deps",
                argv=[
                    "python3",
                    "-m",
                    "pydeps",
                    "src/backend/retrieval-service/main.py",
                    "--noshow",
                    "--nodot",
                    "--no-output",
                    "--show-deps",
                    "--deps-output",
                    str(REPORT_DIR / "retrieval-pydeps.json"),
                    "--max-bacon",
                    "2",
                ],
                required_binary="python3",
            ),
        ],
        "flows": [
            AnalysisCommand(
                name="python-code2flow-dot",
                group="flows",
                argv=[
                    "code2flow",
                    "src/backend/python-legacy",
                    "src/backend/retrieval-service",
                    "-o",
                    str(REPORT_DIR / "python-code2flow.dot"),
                ],
                required_binary="code2flow",
            ),
            AnalysisCommand(
                name="retrieval-pyan3-dot",
                group="flows",
                argv=[
                    "pyan3",
                    "src/backend/retrieval-service/main.py",
                    "src/backend/retrieval-service/app",
                    "--dot",
                    "--colored",
                ],
                output=REPORT_DIR / "retrieval-pyan3.dot",
                required_binary="pyan3",
            ),
            AnalysisCommand(
                name="retrieval-pycg-json",
                group="flows",
                argv=[
                    pycg_python,
                    "-m",
                    "PyCG",
                    "--package",
                    "src/backend/retrieval-service",
                    "src/backend/retrieval-service/main.py",
                    "-o",
                    str(REPORT_DIR / "retrieval-pycg.json"),
                ],
                required_binary=pycg_python,
            ),
        ],
        "security": [
            AnalysisCommand(
                name="semgrep-rag-dashboard-rules",
                group="security",
                argv=[
                    "semgrep",
                    "scan",
                    "--config",
                    str(TOOL_DIR / "semgrep-rules"),
                    "--json",
                    "-o",
                    str(REPORT_DIR / "semgrep.json"),
                    "src",
                    "packages",
                    "config",
                ],
                required_binary="semgrep",
            ),
        ],
    }


def flatten(groups: dict[str, list[AnalysisCommand]]) -> list[AnalysisCommand]:
    commands: list[AnalysisCommand] = []
    for group_commands in groups.values():
        commands.extend(group_commands)
    return commands


def is_available(command: AnalysisCommand) -> bool:
    if command.required_binary is None:
        return True
    return shutil.which(command.required_binary) is not None


def run_command(command: AnalysisCommand) -> dict[str, object]:
    if not is_available(command):
        return {
            "name": command.name,
            "group": command.group,
            "status": "skipped",
            "reason": f"missing binary: {command.required_binary}",
        }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stdout_target = None
    try:
        if command.output is not None:
            command.output.parent.mkdir(parents=True, exist_ok=True)
            stdout_target = command.output.open("w", encoding="utf-8")

        env = dict(**os.environ)
        env["PYTHONPATH"] = (
            f"{TOOL_DIR}:{env['PYTHONPATH']}" if env.get("PYTHONPATH") else str(TOOL_DIR)
        )
        local_bin = TOOL_DIR / "node_modules" / ".bin"
        env["PATH"] = f"{local_bin}:{env['PATH']}"

        completed = subprocess.run(
            command.argv,
            cwd=REPO_ROOT,
            check=False,
            text=True,
            stdout=stdout_target or subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    finally:
        if stdout_target is not None:
            stdout_target.close()

    return {
        "name": command.name,
        "group": command.group,
        "status": "ok" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "command": command.argv,
        "output": str(command.output.relative_to(TOOL_DIR)) if command.output else None,
        "stderr": completed.stderr[-4000:],
    }


def write_manifest(results: list[dict[str, object]]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "repo": str(REPO_ROOT),
        "tool_dir": str(TOOL_DIR),
        "results": results,
    }
    (REPORT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "group",
        choices=["all", "deps", "flows", "security", "list"],
        help="Analysis group to run.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Continue after tool failures and return success if the runner itself worked.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    groups = command_groups()
    commands = flatten(groups) if args.group == "all" else groups.get(args.group, [])

    if args.group == "list":
        for command in flatten(groups):
            print(f"{command.group}\t{command.name}\t{' '.join(command.argv)}")
        return 0

    results = [run_command(command) for command in commands]
    write_manifest(results)

    for result in results:
        print(f"{result['status']}: {result['group']}/{result['name']}")

    if args.keep_going:
        return 0
    return 1 if any(result["status"] == "failed" for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())

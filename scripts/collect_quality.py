#!/usr/bin/env python3
"""Collect quality metrics and append to metrics/quality.jsonl.

Runs the existing check scripts and standard tools, counts results, and
writes a single JSON line with a timestamp and git commit hash. This is
the accumulation step that turns point-in-time snapshots into a trend.

Usage:
    python collect_quality.py                    # default paths
    python collect_quality.py --out metrics/quality.jsonl
    python collect_quality.py --dry-run          # print to stdout, don't append

Exit codes:
    0 — always (this is a measurement, not a gate)
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a command, return completed process. Never raises on failure."""
    try:
        return subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(
            cmd, returncode=2, stdout="", stderr=str(exc),
        )


def git_sha(cwd: Path) -> str:
    result = _run(["git", "rev-parse", "--short", "HEAD"], cwd)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def count_todos(cwd: Path) -> int:
    result = _run(
        [sys.executable, "scripts/check_todos.py", "--json"], cwd,
    )
    if result.returncode != 0:
        return -1
    return sum(1 for line in result.stdout.splitlines() if line.strip())


def count_stale_docs(cwd: Path) -> int:
    result = _run(
        [sys.executable, "scripts/check_doc_freshness.py", "--json"], cwd,
    )
    if result.returncode != 0:
        return -1
    return sum(1 for line in result.stdout.splitlines() if line.strip())


def count_arch_violations(cwd: Path) -> int:
    result = _run(
        [sys.executable, "scripts/check_layers.py"], cwd,
    )
    if result.returncode == 0:
        return 0
    if result.returncode == 2:
        return -1  # config error, not measurable
    # Count violation lines from stderr
    return sum(
        1 for line in result.stderr.splitlines()
        if line.strip() and "violation" not in line.lower()
        and line.startswith("  ")
    )


def count_lint_errors(cwd: Path) -> int:
    result = _run(["uv", "run", "ruff", "check", ".", "--quiet"], cwd)
    if result.returncode == 0:
        return 0
    # ruff --quiet outputs one line per error
    return sum(1 for line in result.stdout.splitlines() if line.strip())


def count_tests(cwd: Path) -> int:
    result = _run(
        ["uv", "run", "pytest", "--co", "-q"], cwd,
    )
    if result.returncode != 0:
        return -1
    # Last non-empty line is "N tests collected" or "N test/N tests collected"
    for line in reversed(result.stdout.splitlines()):
        line = line.strip()
        if "selected" in line or "collected" in line:
            # e.g. "416 tests collected"
            parts = line.split()
            if parts and parts[0].isdigit():
                return int(parts[0])
    return -1


def collect(cwd: Path) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": git_sha(cwd),
        "todo_count": count_todos(cwd),
        "stale_doc_count": count_stale_docs(cwd),
        "arch_violations": count_arch_violations(cwd),
        "lint_errors": count_lint_errors(cwd),
        "test_count": count_tests(cwd),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Collect quality metrics into JSONL.",
    )
    parser.add_argument(
        "--out",
        default="metrics/quality.jsonl",
        help="Output file (default: metrics/quality.jsonl)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print to stdout instead of appending to file",
    )
    args = parser.parse_args()

    cwd = Path.cwd()
    record = collect(cwd)
    line = json.dumps(record, separators=(",", ":"))

    if args.dry_run:
        print(line)
        return

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

    print(f"Appended to {out_path}: {line}")


if __name__ == "__main__":
    main()

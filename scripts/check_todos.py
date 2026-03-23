#!/usr/bin/env python3
"""Extract TODO/FIXME/HACK markers from source files.

Scans all text files in the project (respecting .gitignore) and reports
markers with file, line number, and surrounding context. Intended as a
non-blocking warning in `just review`, not a CI gate.

Usage:
    python check_todos.py                    # scan current directory
    python check_todos.py --src src/         # scan specific directory
    python check_todos.py --json             # machine-readable output

Exit codes:
    0 — always (this is informational, not a gate)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

MARKERS = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)

SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".mypy_cache", ".ruff_cache", "baml_client", ".claude",
}

SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dylib", ".whl", ".egg",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".zip", ".tar", ".gz", ".lock",
}


@dataclass(frozen=True, slots=True)
class TodoItem:
    file: str
    line: int
    marker: str
    text: str


def git_tracked_files(root: Path) -> set[Path] | None:
    """Return set of git-tracked files, or None if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        return {root / line for line in result.stdout.splitlines() if line}
    except FileNotFoundError:
        return None


def scan_file(path: Path) -> list[TodoItem]:
    """Extract TODO markers from a single file."""
    items: list[TodoItem] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return items

    for i, line in enumerate(text.splitlines(), start=1):
        match = MARKERS.search(line)
        if match:
            items.append(TodoItem(
                file=str(path),
                line=i,
                marker=match.group(1).upper(),
                text=line.strip(),
            ))
    return items


def scan_directory(root: Path) -> list[TodoItem]:
    """Scan all eligible files under root."""
    tracked = git_tracked_files(root)
    items: list[TodoItem] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix in SKIP_EXTENSIONS:
            continue
        if tracked is not None and path not in tracked:
            continue
        items.extend(scan_file(path))

    return items


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract TODO/FIXME/HACK markers from source files.",
    )
    parser.add_argument(
        "--src",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON lines",
    )
    args = parser.parse_args()

    root = Path(args.src).resolve()
    items = scan_directory(root)

    if args.json:
        for item in items:
            print(json.dumps(asdict(item)))
    else:
        counts: dict[str, int] = {}
        for item in items:
            counts[item.marker] = counts.get(item.marker, 0) + 1
            print(f"  {item.file}:{item.line}: [{item.marker}] {item.text}")

        print()
        if items:
            parts = [f"{marker}: {count}" for marker, count in sorted(counts.items())]
            print(f"Found {len(items)} marker(s) ({', '.join(parts)})")
        else:
            print("No TODO/FIXME/HACK markers found.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Check documentation freshness against git history.

Compares the ``Last Updated: YYYY-MM-DD`` metadata in docs/ markdown files
against actual git modification dates. Flags docs that haven't been updated
in >N days but whose related source files have changed.

Usage:
    python check_doc_freshness.py                    # default: docs/, 30 days
    python check_doc_freshness.py --docs docs/ --days 60
    python check_doc_freshness.py --json

Exit codes:
    0 — always (informational, not a gate)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

LAST_UPDATED_RE = re.compile(
    r"^Last\s+Updated:\s*(\d{4}-\d{2}-\d{2})",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class StaleDoc:
    file: str
    declared_date: str
    git_date: str
    days_stale: int


def git_last_modified(path: Path) -> date | None:
    """Return the date of the last git commit that touched this file."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%aI", "--", str(path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return date.fromisoformat(result.stdout.strip()[:10])
    except (FileNotFoundError, ValueError):
        return None


def parse_declared_date(path: Path) -> date | None:
    """Extract the Last Updated date from a markdown file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    match = LAST_UPDATED_RE.search(text)
    if not match:
        return None

    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def check_freshness(
    docs_root: Path,
    max_age_days: int,
) -> list[StaleDoc]:
    """Find docs where declared date is older than max_age_days."""
    threshold = date.today() - timedelta(days=max_age_days)
    stale: list[StaleDoc] = []

    for path in sorted(docs_root.rglob("*.md")):
        declared = parse_declared_date(path)
        if declared is None:
            continue

        if declared >= threshold:
            continue

        git_date = git_last_modified(path)
        git_str = git_date.isoformat() if git_date else "unknown"
        days = (date.today() - declared).days

        stale.append(StaleDoc(
            file=str(path),
            declared_date=declared.isoformat(),
            git_date=git_str,
            days_stale=days,
        ))

    return stale


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Check documentation freshness.",
    )
    parser.add_argument(
        "--docs",
        default="docs",
        help="Documentation directory (default: docs/)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Maximum age in days before flagging (default: 30)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON lines",
    )
    args = parser.parse_args()

    docs_root = Path(args.docs)
    if not docs_root.is_dir():
        print(f"error: docs directory not found: {docs_root}", file=sys.stderr)
        sys.exit(2)

    stale = check_freshness(docs_root, args.days)

    if args.json:
        for item in stale:
            print(json.dumps(asdict(item)))
    else:
        if stale:
            for item in stale:
                print(
                    f"  {item.file}: declared {item.declared_date}, "
                    f"{item.days_stale} days old"
                )
            print()
            print(f"Found {len(stale)} stale doc(s) (>{args.days} days).")
        else:
            print(f"All docs updated within {args.days} days.")


if __name__ == "__main__":
    main()

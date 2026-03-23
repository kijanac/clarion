#!/usr/bin/env python3
"""Validate browser/UI evidence against manifest.

Reads evidence-manifest.toml for required evidence keys, checks that
corresponding evidence/<key>.json files exist, and validates that each
is fresh (matches current git SHA and within staleness window).

Usage:
    python check_evidence.py                    # validate evidence/
    python check_evidence.py --json             # machine-readable output
    python check_evidence.py --max-age 48       # staleness window in hours

Exit codes:
    0 — all evidence present and fresh
    1 — missing or stale evidence
    2 — configuration error
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceIssue:
    """A single problem with an evidence file."""

    key: str
    problem: str
    detail: str


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_manifest(config_path: Path) -> dict[str, str]:
    """Parse evidence-manifest.toml and return {key: description}."""
    text = config_path.read_text(encoding="utf-8")
    cfg = tomllib.loads(text)

    requirements = cfg.get("requirements", {})
    if not isinstance(requirements, dict):
        print("error: [requirements] must be a table", file=sys.stderr)
        sys.exit(2)

    return requirements


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def current_sha() -> str:
    """Return the short SHA of HEAD."""
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_evidence(
    requirements: dict[str, str],
    evidence_dir: Path,
    max_age_hours: int,
) -> list[EvidenceIssue]:
    """Validate evidence files against manifest requirements."""
    issues: list[EvidenceIssue] = []
    sha = current_sha()
    now = datetime.now(tz=timezone.utc)
    max_age = timedelta(hours=max_age_hours)

    for key, description in requirements.items():
        evidence_path = evidence_dir / f"{key}.json"

        if not evidence_path.exists():
            issues.append(EvidenceIssue(
                key=key,
                problem="missing",
                detail=f"Expected {evidence_path}. "
                       f"Requirement: {description}",
            ))
            continue

        try:
            data = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            issues.append(EvidenceIssue(
                key=key,
                problem="invalid",
                detail=f"Cannot parse {evidence_path}: {exc}",
            ))
            continue

        # Check SHA matches current HEAD
        evidence_sha = data.get("sha", "")
        if sha and evidence_sha and not sha.startswith(evidence_sha) and not evidence_sha.startswith(sha):
            issues.append(EvidenceIssue(
                key=key,
                problem="stale_sha",
                detail=f"Evidence SHA ({evidence_sha}) does not match HEAD ({sha}). "
                       f"Re-run evidence collection on current commit.",
            ))
            continue

        # Check timestamp freshness
        timestamp_str = data.get("timestamp", "")
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                age = now - timestamp
                if age > max_age:
                    hours = int(age.total_seconds() / 3600)
                    issues.append(EvidenceIssue(
                        key=key,
                        problem="stale_time",
                        detail=f"Evidence is {hours}h old (max {max_age_hours}h). "
                               f"Re-run evidence collection.",
                    ))
            except ValueError:
                issues.append(EvidenceIssue(
                    key=key,
                    problem="invalid_timestamp",
                    detail=f"Cannot parse timestamp: {timestamp_str}",
                ))

        # Check result field
        result = data.get("result", "")
        if result and result != "pass":
            issues.append(EvidenceIssue(
                key=key,
                problem="failed",
                detail=f"Evidence result is '{result}', expected 'pass'.",
            ))

    return issues


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate browser/UI evidence against manifest.",
    )
    parser.add_argument(
        "--config",
        default="evidence-manifest.toml",
        help="Path to evidence-manifest.toml (default: evidence-manifest.toml)",
    )
    parser.add_argument(
        "--evidence-dir",
        default="evidence",
        help="Directory containing evidence JSON files (default: evidence/)",
    )
    parser.add_argument(
        "--max-age",
        type=int,
        default=24,
        help="Maximum evidence age in hours (default: 24)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON lines",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"error: config not found: {config_path}", file=sys.stderr)
        sys.exit(2)

    requirements = load_manifest(config_path)

    if not requirements:
        print("No evidence requirements defined in manifest.")
        sys.exit(0)

    evidence_dir = Path(args.evidence_dir)
    issues = validate_evidence(requirements, evidence_dir, args.max_age)

    if args.json:
        for issue in issues:
            print(json.dumps(asdict(issue)))
    else:
        if issues:
            print(f"Found {len(issues)} evidence issue(s):\n")
            for issue in issues:
                print(f"  [{issue.problem}] {issue.key}: {issue.detail}")
            print()
            print(
                "Fix: produce evidence files in evidence/<key>.json "
                "matching current HEAD."
            )
        else:
            print(
                f"OK — {len(requirements)} evidence requirement(s) satisfied."
            )

    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()

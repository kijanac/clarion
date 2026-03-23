#!/usr/bin/env python3
"""Classify the current git diff by risk tier.

Reads risk-tiers.toml, runs ``git diff --name-only`` against the merge base,
matches changed files against tier patterns, and returns the highest tier.

Usage:
    python check_risk.py                        # diff against main
    python check_risk.py --base origin/main     # explicit base branch
    python check_risk.py --json                 # machine-readable output
    python check_risk.py --tier-only            # print just the tier name

Exit codes:
    0 — normal risk
    1 — high risk
    2 — critical risk
    3 — configuration error
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from fnmatch import fnmatch
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

TIER_RANK = {"normal": 0, "high": 1, "critical": 2}
TIER_EXIT = {"normal": 0, "high": 1, "critical": 2}


@dataclass(frozen=True, slots=True)
class RiskResult:
    """Result of a risk classification."""

    tier: str
    changed_files: list[str]
    matched_files: dict[str, list[str]]  # tier -> files that matched
    policy: list[str]  # required checks for this tier


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_config(config_path: Path) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Parse risk-tiers.toml and return (tiers, policy)."""
    text = config_path.read_text(encoding="utf-8")
    cfg = tomllib.loads(text)

    tiers = cfg.get("tiers")
    if not tiers:
        print("error: [tiers] section missing in config", file=sys.stderr)
        sys.exit(3)

    for tier_name, patterns in tiers.items():
        if tier_name not in TIER_RANK:
            print(
                f"error: unknown tier '{tier_name}'. "
                f"Valid tiers: {', '.join(TIER_RANK)}",
                file=sys.stderr,
            )
            sys.exit(3)
        if not isinstance(patterns, list):
            print(
                f"error: tier '{tier_name}' must be a list of glob patterns",
                file=sys.stderr,
            )
            sys.exit(3)

    policy = cfg.get("policy", {})
    return tiers, policy


# ---------------------------------------------------------------------------
# Git diff
# ---------------------------------------------------------------------------


def changed_files(base: str) -> list[str]:
    """Return files changed between base and HEAD."""
    # Find merge base to get accurate diff
    merge_base_result = subprocess.run(
        ["git", "merge-base", base, "HEAD"],
        capture_output=True,
        text=True,
    )

    if merge_base_result.returncode != 0:
        # Fall back to direct diff (e.g. no common ancestor)
        ref = base
    else:
        ref = merge_base_result.stdout.strip()

    result = subprocess.run(
        ["git", "diff", "--name-only", ref],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        # Try diffing against HEAD directly (maybe uncommitted changes)
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True,
            text=True,
        )

    return [f for f in result.stdout.splitlines() if f.strip()]


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify(
    files: list[str],
    tiers: dict[str, list[str]],
    policy: dict[str, list[str]],
) -> RiskResult:
    """Classify changed files by risk tier, return the highest."""
    matched: dict[str, list[str]] = {"critical": [], "high": [], "normal": []}

    for filepath in files:
        file_tier = "normal"
        # Check tiers in priority order (critical first, then high)
        for tier_name in ("critical", "high"):
            patterns = tiers.get(tier_name, [])
            if any(fnmatch(filepath, pat) for pat in patterns):
                file_tier = tier_name
                break
        matched[file_tier].append(filepath)

    # Highest tier wins
    if matched["critical"]:
        highest = "critical"
    elif matched["high"]:
        highest = "high"
    else:
        highest = "normal"

    return RiskResult(
        tier=highest,
        changed_files=files,
        matched_files={k: v for k, v in matched.items() if v},
        policy=policy.get(highest, []),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Classify the current git diff by risk tier.",
    )
    parser.add_argument(
        "--config",
        default="risk-tiers.toml",
        help="Path to risk-tiers.toml (default: risk-tiers.toml)",
    )
    parser.add_argument(
        "--base",
        default="main",
        help="Base branch for diff (default: main)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--tier-only",
        action="store_true",
        help="Print just the tier name (for CI scripts)",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"error: config not found: {config_path}", file=sys.stderr)
        sys.exit(3)

    tiers, policy = load_config(config_path)
    files = changed_files(args.base)
    result = classify(files, tiers, policy)

    if args.tier_only:
        print(result.tier)
    elif args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        tier_upper = result.tier.upper()
        print(f"Risk tier: {tier_upper}")
        print(f"Changed files: {len(result.changed_files)}")

        for tier_name in ("critical", "high", "normal"):
            tier_files = result.matched_files.get(tier_name, [])
            if tier_files:
                print(f"\n  {tier_name} ({len(tier_files)}):")
                for f in tier_files:
                    print(f"    {f}")

        if result.policy:
            print(f"\nRequired checks: {', '.join(result.policy)}")

        if not result.changed_files:
            print("\nNo changed files detected.")

    sys.exit(TIER_EXIT[result.tier])


if __name__ == "__main__":
    main()

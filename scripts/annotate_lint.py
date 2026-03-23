#!/usr/bin/env python3
"""Post-process lint tool output with project-specific remediation guidance.

Reads lint output from stdin, matches error codes against lint-remediation.toml,
and appends context lines. Passes through all original output unchanged —
annotations are additive.

Usage:
    uv run ruff check . 2>&1 | python scripts/annotate_lint.py --tool ruff
    uv run ty check 2>&1 | python scripts/annotate_lint.py --tool ty

Or run a tool directly:
    python scripts/annotate_lint.py --tool ruff --run "uv run ruff check ."
    python scripts/annotate_lint.py --tool ty --run "uv run ty check"

Exit codes:
    Mirrors the exit code of the piped/run tool (0 = clean, nonzero = errors).
    If used in pipe mode, exits 1 if any input was received (assumes errors),
    0 if stdin was empty.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]


def load_remediation(config_path: Path) -> dict[str, dict[str, str]]:
    """Load lint-remediation.toml and return {tool: {code: message}}."""
    if not config_path.exists():
        return {}
    text = config_path.read_text(encoding="utf-8")
    return tomllib.loads(text)


# Patterns for extracting error codes from tool output.
# Each pattern should have a named group 'code'.
TOOL_PATTERNS: dict[str, re.Pattern[str]] = {
    # ruff: "path/file.py:10:5: BLE001 Do not catch blind exception"
    "ruff": re.compile(r":\s*(?P<code>[A-Z]+\d+)\s"),
    # ty: "error[unresolved-import]: ..." or "warning[invalid-argument-type]: ..."
    "ty": re.compile(r"\[(?P<code>[a-z][a-z0-9-]+)\]"),
}


def annotate(lines: list[str], tool: str, remediation: dict[str, str]) -> list[str]:
    """Annotate lines with remediation messages. Returns new list."""
    if not remediation:
        return lines

    pattern = TOOL_PATTERNS.get(tool)
    if pattern is None:
        return lines

    output: list[str] = []
    seen_codes: set[str] = set()

    for line in lines:
        output.append(line)
        match = pattern.search(line)
        if not match:
            continue

        code = match.group("code")
        if code in seen_codes:
            continue

        message = remediation.get(code)
        if message:
            seen_codes.add(code)
            output.append(f"  ↳ {message}")

    return output


def find_config() -> Path:
    """Walk up from cwd to find lint-remediation.toml."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        candidate = parent / "lint-remediation.toml"
        if candidate.exists():
            return candidate
    return current / "lint-remediation.toml"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Annotate lint output with project-specific remediation.",
    )
    parser.add_argument(
        "--tool",
        required=True,
        help="Tool name (must match a section in lint-remediation.toml)",
    )
    parser.add_argument(
        "--run",
        default=None,
        help="Command to run (alternative to piping stdin)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to lint-remediation.toml (default: auto-detect)",
    )
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else find_config()
    all_remediation = load_remediation(config_path)
    tool_remediation = all_remediation.get(args.tool, {})

    if args.run:
        result = subprocess.run(
            shlex.split(args.run),
            capture_output=True,
            text=True,
        )
        raw = result.stdout + result.stderr
        lines = raw.splitlines()
        annotated = annotate(lines, args.tool, tool_remediation)
        print("\n".join(annotated))
        sys.exit(result.returncode)
    else:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        lines = raw.splitlines()
        annotated = annotate(lines, args.tool, tool_remediation)
        print("\n".join(annotated))
        sys.exit(1)


if __name__ == "__main__":
    main()

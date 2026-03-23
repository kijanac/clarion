#!/usr/bin/env python3
"""Create a failing test skeleton from an incident description.

Mechanical harness-gap loop: every incident becomes a test that starts red.
The test lives in tests/incidents/ with an @pytest.mark.incident marker,
ensuring the reproduction is tracked and eventually turns green.

Usage:
    python scripts/incident_to_test.py "user saw 500 on /api/orders when cart is empty"
    python scripts/incident_to_test.py "login page crashes for SSO users" --json

Exit codes:
    0 — test file created
    1 — test file already exists
"""

from __future__ import annotations

import json
import re
import sys
import textwrap
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IncidentTestResult:
    """Result of creating an incident test skeleton."""

    test_file: str
    test_function: str
    description: str
    created: bool


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------


def slugify(description: str) -> str:
    """Convert an incident description to a valid Python identifier slug."""
    # Lowercase and replace non-alphanumeric with underscores
    slug = re.sub(r"[^a-z0-9]+", "_", description.lower())
    # Strip leading/trailing underscores
    slug = slug.strip("_")
    # Truncate to a reasonable length
    if len(slug) > 60:
        slug = slug[:60].rstrip("_")
    # Ensure it starts with a letter
    if slug and not slug[0].isalpha():
        slug = f"incident_{slug}"
    return slug or "incident_unnamed"


# ---------------------------------------------------------------------------
# Test generation
# ---------------------------------------------------------------------------


def generate_test(description: str, slug: str) -> str:
    """Generate the content of a failing test skeleton."""
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return textwrap.dedent(f'''\
        """Incident reproduction: {description}

        Created: {timestamp}
        Status: RED — awaiting implementation
        """

        import pytest


        @pytest.mark.incident
        def test_{slug}():
            """Reproduce: {description}"""
            pytest.fail("TODO: implement reproduction for this incident")
    ''')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Create a failing test skeleton from an incident description.",
    )
    parser.add_argument(
        "description",
        help="Human-readable description of the incident",
    )
    parser.add_argument(
        "--output-dir",
        default="tests/incidents",
        help="Directory for incident tests (default: tests/incidents/)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    slug = slugify(args.description)
    test_func = f"test_{slug}"
    output_dir = Path(args.output_dir)
    test_file = output_dir / f"test_{slug}.py"

    result = IncidentTestResult(
        test_file=str(test_file),
        test_function=test_func,
        description=args.description,
        created=False,
    )

    if test_file.exists():
        if args.json:
            print(json.dumps(asdict(result)))
        else:
            print(f"error: test file already exists: {test_file}", file=sys.stderr)
            print("Edit the existing test or use a different description.")
        sys.exit(1)

    # Create directory and test file
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create __init__.py if missing
    init_file = output_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text("")

    # Write test file
    content = generate_test(args.description, slug)
    test_file.write_text(content, encoding="utf-8")

    result = IncidentTestResult(
        test_file=str(test_file),
        test_function=test_func,
        description=args.description,
        created=True,
    )

    if args.json:
        print(json.dumps(asdict(result)))
    else:
        print(f"Created: {test_file}")
        print(f"Function: {test_func}")
        print()
        print("Next steps:")
        print(f"  1. Open {test_file}")
        print("  2. Replace pytest.fail() with reproduction logic")
        print("  3. Run: just test -- -m incident")


if __name__ == "__main__":
    main()

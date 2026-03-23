# Harness-standard justfile.
#
# Standard targets every project must have:
#   lint, format, types, test, arch, ci, review
#
# Naming conventions:
#   Plain name = read-only check (lint, format, types, test, arch)
#   -fix suffix = mutates files (lint-fix, format-fix)
#   All commands use `uv run` — no `uvx`.
#
# Adapt the commands (paths, tools) to your project.
# Keep the target names stable across all repos.

set dotenv-load := false

annotate := "uv run python scripts/annotate_lint.py"

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

# List available recipes
default:
    @just --list

# ---------------------------------------------------------------------------
# Quality — individual checks (all read-only)
# ---------------------------------------------------------------------------

# Lint with ruff (annotated with project-specific remediation)
lint:
    {{annotate}} --tool ruff --run "uv run ruff check ."

# Check formatting (read-only)
format:
    uv run ruff format --check .

# Type-check (annotated with project-specific remediation)
types:
    {{annotate}} --tool ty --run "uv run ty check"

# Run tests
test *args='':
    uv run pytest {{ args }}

# Run tests, stop on first failure
test-fast:
    uv run pytest -x -q

# Check architecture layer boundaries
arch:
    uv run python scripts/check_layers.py

# ---------------------------------------------------------------------------
# Compound checks
# ---------------------------------------------------------------------------

# Run all CI checks (same gates as GitHub Actions)
ci: lint format types test arch

# Pre-push review: CI + risk assessment + entropy warnings.
# This is the "one command before you push" gate.
# CI checks are blocking; risk + entropy checks are informational.
review: ci
    @echo ""
    @echo "--- Risk assessment ---"
    -uv run python scripts/check_risk.py
    @echo ""
    @echo "--- Entropy warnings (non-blocking) ---"
    -uv run python scripts/check_todos.py
    -uv run python scripts/check_doc_freshness.py
    @echo ""
    @echo "Review: PASSED"

# Collect quality metrics and append to metrics/quality.jsonl.
# Run after review, after deploys, or on a schedule.
quality:
    uv run python scripts/collect_quality.py

# ---------------------------------------------------------------------------
# Risk & Evidence
# ---------------------------------------------------------------------------

# Classify risk tier of current changes
risk:
    uv run python scripts/check_risk.py

# Validate browser/UI evidence against manifest
evidence:
    uv run python scripts/check_evidence.py

# Create a failing test skeleton from an incident description
incident description:
    uv run python scripts/incident_to_test.py "{{ description }}"

# ---------------------------------------------------------------------------
# Fix — mutates files
# ---------------------------------------------------------------------------

# Auto-fix lint issues
lint-fix:
    uv run ruff check --fix .

# Auto-format
format-fix:
    uv run ruff format .

# Fix everything auto-fixable (lint + format)
fix: lint-fix format-fix

# Fix, verify tests, show what changed
fix-check: fix test-fast
    git diff --stat

# ---------------------------------------------------------------------------
# Run (adapt to your project's entrypoints)
# ---------------------------------------------------------------------------

# Run an agent
run *args='':
    uv run clarion run {{ args }}

# Validate agent config
register *args='':
    uv run clarion register {{ args }}

# Environment health check
health:
    uv run clarion health

# ---------------------------------------------------------------------------
# Deploy (adapt or remove)
# ---------------------------------------------------------------------------

# deploy *args:
#     cd deploy && ansible-playbook playbook.yml {{ args }}

# deploy-check *args:
#     cd deploy && ansible-playbook playbook.yml --check --diff {{ args }}

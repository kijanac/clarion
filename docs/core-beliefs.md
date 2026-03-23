# Core Beliefs

Non-negotiable rules for this codebase. Each belief has an enforcement
mechanism — if it can't be checked, it's an aspiration, not a rule.

Owner: TBD
Status: Active
Last Updated: 2026-03-22

## 1. Typed Boundaries, Not Raw Dicts
All external data parsed into dataclasses/Pydantic models at the boundary.
No raw dicts past the adapter layer.
Enforcement: code review + type checker.

## 2. Correlation IDs on Every Entry Point
Every inbound event gets a correlation ID via contextvars.
Enforcement: `log_event()` includes correlation_id automatically.

## 3. Module Boundaries Are Walls
One client module per external service. No cross-client imports.
Enforcement: `check_layers.py` in CI.

## 4. No Over-Engineering
Three similar lines of code is better than a premature abstraction.
Enforcement: code review.

## 5. Narrow Exception Handling
Catch specific exceptions, not bare `Exception`.
Enforcement: ruff rule (BLE001).

## 6. Red/Green TDD
Write the test first. Confirm it fails (red). Implement until it passes (green).
Skipping the red phase risks tests that pass without exercising new code.
Enforcement: `just test` in `just review`; core-beliefs.md read by agents at session start.

## 7. Risk-Proportional Review
Higher-risk changes require proportionally more verification. Core system
files (models, auth, migrations) demand browser evidence; routine changes
need only standard CI.
Enforcement: `risk-tiers.toml` + CI preflight gate.

<!-- Add project-specific beliefs below. Aim for 6-10 total. -->

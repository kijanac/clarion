# Harness Engineering Audit Rubric

Canonical source: [Harness Engineering (OpenAI, Feb 2026)](https://archive.is/aj5J0)

## Scoring Table

| Pillar | Score | Evidence |
|--------|------:|----------|
| 1. Agent Operating Contract | /3 | |
| 2. Repo Knowledge System of Record | /3 | |
| 3. Progressive Disclosure + Doc Hygiene | /3 | |
| 4. Mechanical Architecture Enforcement | /3 | |
| 5. Boundary Validation + Taste Invariants | /3 | |
| 6. Agent-Legible Runtime | /3 | |
| 7. Agent-Legible Observability | /3 | |
| 8. End-to-End Evaluation Harness | /3 | |
| 9. Agent-Centric Delivery Loop | /3 | |
| 10. Entropy Control / Garbage Collection | /3 | |
| **Total** | **/30** | |

## Scoring Scale

- **0**: Missing.
- **1**: Partial / ad hoc. Template or plan exists, no enforcement.
- **2**: Implemented but incomplete or weakly enforced.
- **3**: Strongly implemented and mechanically enforced.

## Pillar Details

### 1. Agent Operating Contract

Check for:
- Short `AGENTS.md` acting as map / table of contents
- Clear links to deeper docs
- Minimal inlined policy bloat

Harness tools: `scaffold/AGENTS.md`

### 2. Repository Knowledge System of Record

Check for:
- Structured `docs/` tree with owned artifacts
- Architecture, reliability, security, quality docs with owner/status/date metadata
- Versioned execution plans and decision records (ADRs)

Harness tools: `scaffold/docs/` skeleton

### 3. Progressive Disclosure + Documentation Hygiene

Check for:
- AGENTS.md -> docs/ -> source code layering
- Cross-linking and freshness checks
- Automated doc gardening or stale-doc detection

Harness tools: `check_doc_freshness.py`

### 4. Mechanical Architecture Enforcement

Check for:
- Explicit domain/layer model
- Structural tests or custom linters enforcing dependency direction
- Clear allowed/disallowed edges

Harness tools: `check_layers.py` + `architecture.toml`

### 5. Boundary Validation + Taste Invariants

Check for:
- Parsing/validation at external boundaries (dataclasses, Pydantic)
- Enforced schema/type conventions
- Custom lints for logging, naming, file size, platform constraints
- Lint error messages that include remediation instructions
- Risk tier classification (`risk-tiers.toml` + `check_risk.py`)
- CI gates proportional to risk level

Evidence examples: runtime schema validation, custom lint rules with fix guidance

### 6. Agent-Legible Runtime

Check for:
- App bootable per-task/per-worktree
- Deterministic demo/test mode
- Reproducible bug validation loops

Evidence examples: local spin-up scripts, fake backends, `just run`

### 7. Agent-Legible Observability

Check for:
- Structured JSON logging with correlation IDs
- `log_event()` as the only logging API
- Wide events for request-scoped accumulation
- Logs queryable by agents

Harness tools: `logging_config.py`

### 8. End-to-End Evaluation Harness

Check for:
- Deterministic tests for core user journeys
- Fixture-driven scenarios with in-memory fakes
- Ability to reproduce failure, fix, and verify in one run
- Browser/UI evidence with manifest assertions (`evidence-manifest.toml` + `check_evidence.py`)
- Incident-to-test mechanical loop (`incident_to_test.py`)

Evidence examples: JSON fixture runner, FakeLlm/FakeSignal patterns

### 9. Agent-Centric Delivery Loop

Check for:
- Agent can run local review, resolve feedback, and iterate
- Single pre-push command that mirrors CI
- Clear escalation path when human judgment is required
- Risk-aware preflight gate in CI (cheap checks first, fan out expensive checks by tier)

Harness tools: `just review`

### 10. Entropy Control / Garbage Collection

Check for:
- Recurring cleanup/refactor automation
- Golden principles codified into lints/docs/scripts
- TODO extraction and doc freshness monitoring
- Continuous quality scoring

Harness tools: `check_todos.py`, `check_doc_freshness.py`, quality scorecard in `docs/quality/`

## Anti-Patterns to Flag

- Monolithic AGENTS manual instead of a short map + linked sources of truth
- Rules documented but not mechanically enforced
- Tests present but flaky/noisy without follow-up automation
- Hidden knowledge in chat/docs outside the repository
- Architectural boundaries described but not validated

## Priority Mapping

When ranking implementation priorities, use severity = `impact x foundation x detectability`:
- **impact**: effect on reliability and velocity
- **foundation**: how much it unlocks other capabilities
- **detectability**: ability to catch regressions automatically

Default leverage ordering:
1. Map docs + system of record
2. Mechanical enforcement (CI, architecture, boundary lints)
3. Reproducible eval harness + test reliability
4. Agent-observable runtime signals (logs/metrics/traces)
5. Continuous entropy control (doc gardening + cleanup automation)

## How to Use

1. Score your project honestly. Fill in the table above.
2. Pick the lowest-scoring pillar.
3. Raise it by one point.
4. Repeat.

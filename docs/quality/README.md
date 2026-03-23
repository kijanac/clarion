# Quality Baseline

Owner: TBD
Status: Draft
Last Updated: 2026-03-22

## Quality Gates
All enforced in CI via `just ci`:

| Gate | Command | Status |
|------|---------|--------|
| Lint | `just lint` | |
| Format | `just format` | |
| Types | `just types` | |
| Tests | `just test` | |
| Architecture | `just arch` | |

## Quality Scorecard

Grade scale: A (solid) | B (good, minor gaps) | C (functional, needs work) | D (fragile)

### Product Domains
| Domain | Grade | Notes |
|--------|-------|-------|
<!-- Fill in per your product areas -->

### Architectural Layers
| Layer | Grade | Notes |
|-------|-------|-------|
<!-- Fill in per your architecture.toml layers -->

### Cross-Cutting Concerns
| Concern | Grade | Notes |
|---------|-------|-------|
| Test coverage | | |
| Type safety | | |
| Error handling | | |
| Logging/observability | | |
| Documentation | | |
| Security | | |

## Metrics
<!-- Track over time in metrics/quality.jsonl if desired -->
- Test count:
- Lint errors:
- Architecture violations:
- TODO/FIXME count:

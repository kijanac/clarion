# System Overview

Owner: TBD
Status: Draft
Last Updated: 2026-03-22

## Purpose
What does this system do? One paragraph.

## Architecture Layers

<!-- Define your layer DAG here. Must match architecture.toml. -->

| Layer | Rank | Modules | Responsibility |
|-------|------|---------|----------------|
| Foundation | 0 | models, logging_config | Data types, logging, config |
| Algorithms | 1 | | Business logic |
| Orchestration | 2 | | Coordination |
| Adapters | 3 | | External service clients |
| Entrypoints | 4 | | CLI, API, workers |

## Key Constraints
- List architectural invariants here.
- e.g. "Adapters cannot import from Orchestration."
- e.g. "One process per user."

## Implementation Evidence
- Architecture enforcement: `scripts/check_layers.py`
- Layer config: `architecture.toml`
- CI gate: `.github/workflows/ci.yml`

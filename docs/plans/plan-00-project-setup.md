# Plan 00 — Project Setup

## Goal

Scaffold the Clarion project: directory structure, pyproject.toml,
tooling config, architecture.toml, example agent config, and example
template. After this plan is complete, `uv sync` works and the project
is ready for layer-by-layer implementation.

---

## Directory Structure

Create this exact tree. Empty `__init__.py` files where noted.

```
clarion/
├── src/
│   └── clarion/
│       ├── __init__.py               # version string only
│       ├── models.py                 # layer 0 — plan-01
│       ├── logging.py                # layer 0 — plan-01
│       ├── cancellation.py           # layer 0 — plan-01
│       ├── boundary_validation.py    # layer 0 — plan-01
│       ├── secret_store.py           # layer 0 — plan-01
│       ├── cron_state.py             # layer 0 — plan-01
│       ├── cron_scheduler.py         # layer 0 — plan-01
│       ├── agent_state.py            # layer 0 — plan-01
│       ├── agent_config.py           # layer 0 — plan-01
│       ├── tool_registry.py          # layer 1 — plan-02
│       ├── llm_client.py             # layer 1 — plan-02
│       ├── background_tasks.py       # layer 1 — plan-02
│       ├── agent_runner.py           # layer 2 — plan-03
│       ├── prompt_assembly.py        # layer 2 — plan-03
│       ├── cli.py                    # layer 5 — plan-05
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── search.py             # layer 1 — plan-02
│       │   ├── fetch.py              # layer 1 — plan-02
│       │   ├── fetch_cache.py        # layer 1 — plan-02
│       │   ├── research.py           # layer 1 — plan-02
│       │   ├── sql.py                # layer 1 — plan-02
│       │   ├── cron.py               # layer 1 — plan-02
│       │   ├── workspace.py          # layer 1 — plan-02
│       │   ├── deliver_output.py     # layer 1 — plan-02
│       │   └── executor.py           # layer 1 — plan-02
│       └── adapters/
│           ├── __init__.py
│           └── telegram.py           # layer 4 — plan-04
├── templates/
│   └── research.yaml
├── agents/
│   └── example-research/
│       └── agent.yaml
├── tests/
│   ├── __init__.py
│   └── conftest.py
├── data/                             # runtime data, gitignored
│   └── agents/
│       └── example-research/
│           └── mission.md            # example mission for testing
├── docs/
│   └── plans/                        # these plan documents
├── architecture.toml
├── pyproject.toml
├── .gitignore
└── .python-version
```

---

## pyproject.toml

```toml
[project]
name = "clarion"
version = "0.1.0"
description = "A self-hosted team intelligence platform"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.0,<3",
    "structlog>=24.0",
    "httpx>=0.27,<1",
    "typer>=0.12",
    "rich>=13.0",
    "croniter>=3.0,<4",
    "duckduckgo-search>=7.0",
    "readability-lxml>=0.8.4",
    "markdownify>=1.2",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-mock>=3.14",
    "ruff>=0.8",
    "ty>=0.1",
]

[project.scripts]
clarion = "clarion.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/clarion"]

[tool.ruff]
target-version = "py311"
line-length = 100
src = ["src"]

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM"]

[tool.ruff.lint.isort]
known-first-party = ["clarion"]

[tool.ty.environment]
python-version = "3.11"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]
```

### Notes on dependencies

- `duckduckgo-search` — the package was renamed from `ddgs`. Check redclaw's
  pyproject.toml for the exact version pin they use and match it. The import
  is still `from duckduckgo_search import DDGS`.
- `scrapling` — listed in redclaw for stealth/browser fetch modes. Add it
  only if those modes are needed for Phase 1. Omit for now to keep deps
  lighter; the fetch tool has a fallback path when scrapling is unavailable.
- `readability-lxml` — depends on `lxml` which has C compilation. Ensure
  the dev machine has `libxml2-dev` / `libxslt-dev` or use a prebuilt wheel.

---

## .python-version

```
3.11
```

---

## .gitignore

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/

# Runtime data — agent databases, cron state, run history, missions
data/

# IDE
.idea/
.vscode/
*.swp

# OS
.DS_Store

# Secrets
.secrets/
*.env
```

---

## architecture.toml

```toml
# Clarion Architecture Layer Definitions
#
# Modules in lower layers cannot import from higher layers.
# Modules in the same layer can import from each other.
# Higher layers can import from any lower layer.

package = "clarion"

[layers]
foundation = 0      # models, logging, validation, state, secrets
algorithms = 1      # tools, llm client, background tasks
runtime = 2         # agent loop, prompt assembly
scheduler = 3       # daemon, agent registry (Phase 2)
adapters = 4        # telegram, email, webhook delivery
entrypoints = 5     # CLI, daemon main

[modules]
# foundation
models = "foundation"
logging = "foundation"
boundary_validation = "foundation"
secret_store = "foundation"
agent_state = "foundation"
cron_state = "foundation"
cron_scheduler = "foundation"
cancellation = "foundation"
agent_config = "foundation"

# algorithms
tools = "algorithms"
tool_registry = "algorithms"
llm_client = "algorithms"
background_tasks = "algorithms"

# runtime
agent_runner = "runtime"
prompt_assembly = "runtime"

# scheduler (Phase 2)
agent_registry = "scheduler"
daemon = "scheduler"

# adapters
telegram_adapter = "adapters"

# entrypoints
cli = "entrypoints"
```

---

## templates/research.yaml

```yaml
# research.yaml — Research Agent Template
#
# Defined by the tech team. Agents using this template inherit these
# tools, limits, and base prompt. Individual agent configs can override
# resource values downward only.

name: research
description: >
  Long-running research and synthesis agent. Searches the web, fetches
  sources, builds a persistent knowledge base, and produces structured
  briefings on cadence.

tools:
  - current_datetime
  - web_search
  - web_fetch
  - web_extract
  - deep_research
  - execute_sql
  - list_databases
  - cron
  - write_file
  - deliver_output

model: claude-sonnet-4-6
max_tokens: 8192

resources:
  max_runs_per_day: 12
  max_search_calls_per_run: 30
  max_fetch_calls_per_run: 15
  max_deep_research_calls_per_run: 3
  max_sql_calls_per_run: 50
  run_timeout_seconds: 600
  max_database_mb: 1000
  max_self_scheduled_runs_per_day: 6

system_prompt: |
  You are a research agent running as part of the Clarion intelligence
  platform. You run on a schedule, unattended. No human is watching
  you work.

  ## Your mission

  Your specific domain, goals, and output requirements are in your
  mission below. Read it carefully at the start of every run.

  ## Your database

  You have a persistent SQLite database scoped to your agent. Use it
  to build knowledge over time — create tables that make sense for
  your domain, store what you find, query what you know before
  searching for what you don't. Your database is your memory.

  On your first run, design a schema that fits your mission. On
  subsequent runs, query first, then search for what's genuinely new.
  Always check your existing schema with a query against sqlite_master
  before creating tables.

  ## Your scheduler

  You can reschedule yourself using the cron tool. If you find
  something developing quickly, schedule a follow-up run sooner
  than your default. If nothing significant is happening, let the
  default schedule stand. Use this judgment deliberately — don't
  reschedule reflexively.

  ## Your outputs

  Your output definitions are provided in your run context. Produce
  each output when its trigger condition is met. For scheduled outputs,
  produce them on the run where the schedule fires. For agent_decides
  outputs, use your judgment — only trigger them when genuinely
  warranted.

  ## How to run

  1. Read your mission
  2. Check your database schema (query sqlite_master)
  3. Query your database — what do you already know?
  4. Search for what's new since your last run
  5. Store significant findings in your database
  6. Decide which outputs are due and produce them
  7. Decide if you need to reschedule

  ## What you are not

  You are not a chatbot. You do not explain your reasoning unless
  an output format asks for it. You do not ask for clarification —
  work with what you have and note uncertainty in your outputs.
  You do not pad outputs. Say what matters, stop.
```

---

## agents/example-research/agent.yaml

The agent_id is always derived from the directory name (here: `example-research`).
`meta.name` is a human-readable display name — it does not need to be a slug
and does not need to match the directory name.

The config loader supports `${ENV_VAR}` substitution in string values
(like Docker Compose). This keeps secrets out of version-controlled files.

```yaml
# Example research agent configuration.
# This file is parsed by the platform. The agent (LLM) never sees it.

meta:
  name: Semiconductor Supply Chain Research
  description: Semiconductor supply chain intelligence
  owner: policy-team
  version: 1

template: research

schedule:
  default: "0 6 * * 1"          # every Monday at 06:00
  timezone: America/New_York

database:
  enabled: true

outputs:
  - name: weekly-briefing
    description: Weekly intelligence briefing on semiconductor supply chain
    trigger: scheduled
    type: telegram
    destination: "${TELEGRAM_CHAT_ID}"
    format: |
      Produce a concise briefing covering:
      1. Top developments since last briefing (max 5)
      2. What changed vs what was expected
      3. One-paragraph outlook

      Lead with implications, not events. Your audience is senior
      policy staff — they don't need things explained from scratch.

  - name: breaking-alert
    description: Urgent development that warrants immediate attention
    trigger: agent_decides
    type: telegram
    destination: "${TELEGRAM_CHAT_ID}"
    format: |
      One paragraph: what happened, why it matters, what to watch.
      Only trigger this for genuinely significant developments.

resources:
  max_search_calls_per_run: 20    # override template default downward
```

---

## data/agents/example-research/mission.md

This is a runtime file (gitignored). Create it manually for testing.

```markdown
# Semiconductor Supply Chain Research

I work on semiconductor policy for a DC think tank. This agent should
keep me ahead of developments in the areas below.

## What I care about

- US-China chip trade restrictions and export controls — especially
  anything that changes the enforcement picture or adds new entities
  to restricted lists
- Fab construction timelines: TSMC Arizona, Intel Ohio, Samsung Texas,
  and any new announcements from ASML or applied materials
- CHIPS Act implementation — funding decisions, delays, eligibility
  disputes, anything that signals how the policy is actually landing
- Geopolitical signals that would change a policymaker's assumptions
  about supply chain resilience

## What I don't care about

- Consumer electronics products and release cycles
- Earnings calls and stock price movements unless they signal something
  structural
- Think pieces that rehash known positions without new information

## My audience

Senior policy staff and external fellows. Lead with the implication,
not the event. "The Arizona delay suggests CHIPS Act incentive structure
isn't moving fast enough to change private investment timelines" is
more useful than "TSMC delayed Arizona Phase 2 by 18 months."

## How to handle uncertainty

If you're not sure whether something is significant, err toward
including it with a note about uncertainty. Reserve breaking alerts
for things you're confident about.
```

---

## tests/conftest.py

```python
"""Shared fixtures for Clarion tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a temporary agent workspace directory."""
    workspace = tmp_path / "data" / "agents" / "test-agent"
    workspace.mkdir(parents=True)
    (workspace / "databases").mkdir()
    (workspace / "cron").mkdir()
    (workspace / "runs").mkdir()
    (workspace / "cache").mkdir()
    return workspace


@pytest.fixture
def tmp_agent_dir(tmp_path: Path) -> Path:
    """Create a temporary agent config directory with a minimal agent.yaml."""
    agent_dir = tmp_path / "agents" / "test-agent"
    agent_dir.mkdir(parents=True)
    return agent_dir


@pytest.fixture
def templates_dir(tmp_path: Path) -> Path:
    """Create a temporary templates directory with a minimal research template."""
    tpl_dir = tmp_path / "templates"
    tpl_dir.mkdir()
    (tpl_dir / "research.yaml").write_text(
        "name: research\n"
        "description: test template\n"
        "tools:\n"
        "  - web_search\n"
        "  - execute_sql\n"
        "model: test-model\n"
        "max_tokens: 1024\n"
        "resources:\n"
        "  max_search_calls_per_run: 10\n"
        "  max_fetch_calls_per_run: 5\n"
        "  max_sql_calls_per_run: 20\n"
        "system_prompt: You are a test agent.\n"
    )
    return tpl_dir
```

---

## src/clarion/__init__.py

```python
"""Clarion — a self-hosted team intelligence platform."""

__version__ = "0.1.0"
```

## src/clarion/tools/__init__.py

```python
"""Tool implementations for Clarion agents."""
```

## src/clarion/adapters/__init__.py

```python
"""Delivery adapters for Clarion outputs."""
```

## tests/__init__.py

Empty file.

---

## Verification

After creating all files:

```bash
cd /path/to/clarion
uv sync
uv run python -c "import clarion; print(clarion.__version__)"
# Should print: 0.1.0

uv run pytest tests/ -x
# Should pass (no tests yet beyond importability)

uv run ruff check src/
# Should pass with no errors
```

---

## What comes next

Implement layers in order:
1. **Plan 01** — Foundation (layer 0): models, logging, validation, state, config
2. **Plan 02** — Algorithms (layer 1): tools, LLM client, executor, registry
3. **Plan 03** — Runtime (layer 2): agent runner, prompt assembly
4. **Plan 04** — Adapters (layer 4): Telegram delivery
5. **Plan 05** — Entrypoints (layer 5): CLI

Each layer depends only on layers below it.

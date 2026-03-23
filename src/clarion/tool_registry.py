"""Tool registry — layer 1.

Single source of truth for every tool.  Each tool is defined once as a
``ToolSpec`` that co-locates its OpenAI JSON schema, execution policy,
and LLM prompt hint.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ToolExecutionPolicy(BaseModel):
    """Execution-time behaviour flags for a tool."""

    model_config = ConfigDict(frozen=True)

    memoize_duplicate_calls_within_turn: bool = True
    side_effecting: bool = False


class ToolSpec(BaseModel):
    """Everything the system needs to know about one tool."""

    model_config = ConfigDict(frozen=True)

    name: str
    tool_schema: dict
    policy: ToolExecutionPolicy
    prompt_hint: str


_DEFAULT_POLICY = ToolExecutionPolicy()


# ---------------------------------------------------------------------------
# Individual tool definitions
# ---------------------------------------------------------------------------

_CURRENT_DATETIME = ToolSpec(
    name="current_datetime",
    tool_schema={
        "type": "function",
        "function": {
            "name": "current_datetime",
            "description": "Get the current date and time.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    policy=ToolExecutionPolicy(),
    prompt_hint="Use current_datetime to check the actual date and time when needed.",
)

_WEB_SEARCH = ToolSpec(
    name="web_search",
    tool_schema={
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search terms",
                        "maxLength": 400,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    policy=ToolExecutionPolicy(),
    prompt_hint="When you need current information, use web_search.",
)

_WEB_FETCH = ToolSpec(
    name="web_fetch",
    tool_schema={
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Fetch and extract content from a URL."
                " Set mode to 'stealth' for sites with"
                " anti-bot protection (e.g. Cloudflare)"
                " or 'browser' for JavaScript-rendered"
                " pages. Default 'fast' mode works for"
                " most sites."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to fetch and extract content from",
                        "maxLength": 2000,
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["browser", "fast", "stealth"],
                        "description": (
                            "fast: standard HTTP (default)."
                            " stealth: anti-bot bypass."
                            " browser: full JS rendering."
                        ),
                    },
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    policy=ToolExecutionPolicy(),
    prompt_hint=(
        "When the user asks about a specific URL or you need to read a"
        " webpage, use web_fetch with the URL."
    ),
)

_WEB_EXTRACT = ToolSpec(
    name="web_extract",
    tool_schema={
        "type": "function",
        "function": {
            "name": "web_extract",
            "description": (
                "Extract specific content from a web page"
                " using CSS or XPath selectors. Returns"
                " targeted sections (tables, lists, specific"
                " divs) instead of the full article. Useful"
                " when you need structured data from a known"
                " page layout."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to fetch and extract from",
                        "maxLength": 2000,
                    },
                    "selector": {
                        "type": "string",
                        "description": (
                            "CSS or XPath selector expression (e.g. 'table.data', '//ul/li')"
                        ),
                        "maxLength": 500,
                    },
                    "selector_type": {
                        "type": "string",
                        "enum": ["css", "xpath"],
                        "description": "css (default) or xpath.",
                    },
                },
                "required": ["url", "selector"],
                "additionalProperties": False,
            },
        },
    },
    policy=ToolExecutionPolicy(),
    prompt_hint=(
        "When you need specific content from a known page layout (tables,"
        " lists, specific divs), use web_extract with a CSS or XPath selector"
        " instead of fetching the full page."
    ),
)

_DEEP_RESEARCH = ToolSpec(
    name="deep_research",
    tool_schema={
        "type": "function",
        "function": {
            "name": "deep_research",
            "description": (
                "Research a question by searching the web"
                " and fetching multiple sources in parallel."
                " Returns a structured report with content"
                " from each source and citations. Use this"
                " instead of manual web_search + web_fetch"
                " loops when you need to gather information"
                " from several pages."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The research question",
                        "maxLength": 1000,
                    },
                    "max_sources": {
                        "type": "integer",
                        "description": "Max web pages to fetch (default 5, max 10)",
                    },
                },
                "required": ["question"],
                "additionalProperties": False,
            },
        },
    },
    policy=ToolExecutionPolicy(),
    prompt_hint=(
        "When you need to research a topic across multiple sources, use"
        " deep_research with a clear question. It searches the web, fetches"
        " the top results in parallel, and returns a structured report with"
        " citations. Prefer this over manual web_search + web_fetch loops."
    ),
)

_EXECUTE_SQL = ToolSpec(
    name="execute_sql",
    tool_schema={
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": (
                "Run a SQL statement against a named"
                " SQLite database in your workspace."
                " The database is created automatically"
                " on first use. Returns rows as JSON"
                " for SELECT queries, or rows-affected"
                " for INSERT/UPDATE/DELETE. Use"
                " parameterized queries with the params"
                " array to safely interpolate values."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Logical database name (e.g. 'news_tracker')",
                        "maxLength": 64,
                    },
                    "sql": {
                        "type": "string",
                        "description": "SQL statement",
                        "maxLength": 4000,
                    },
                    "params": {
                        "type": "array",
                        "items": {},
                        "description": "Positional parameters for ? placeholders",
                    },
                },
                "required": ["name", "sql"],
                "additionalProperties": False,
            },
        },
    },
    policy=ToolExecutionPolicy(
        memoize_duplicate_calls_within_turn=False,
        side_effecting=True,
    ),
    prompt_hint="",
)

_LIST_DATABASES = ToolSpec(
    name="list_databases",
    tool_schema={
        "type": "function",
        "function": {
            "name": "list_databases",
            "description": "List all SQLite databases in your workspace.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    policy=ToolExecutionPolicy(),
    prompt_hint="",
)

_CRON = ToolSpec(
    name="cron",
    tool_schema={
        "type": "function",
        "function": {
            "name": "cron",
            "description": "Manage scheduled jobs and reminders.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "list", "remove", "edit"],
                        "description": "Cron operation: add, list, remove, or edit",
                    },
                    "name": {
                        "type": "string",
                        "description": "Human-readable job name (required for add)",
                        "maxLength": 500,
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["at", "every", "cron"],
                        "description": (
                            "Schedule kind: at (one-time), every (interval), cron (expression)"
                        ),
                    },
                    "at": {
                        "type": "string",
                        "description": "ISO 8601 timestamp for one-time schedule (kind=at)",
                        "maxLength": 100,
                    },
                    "every_ms": {
                        "type": "integer",
                        "description": "Interval in milliseconds (kind=every)",
                    },
                    "cron": {
                        "type": "string",
                        "description": "5-field cron expression (kind=cron)",
                        "maxLength": 100,
                    },
                    "job_id": {
                        "type": "string",
                        "description": "Job ID (required for remove/edit)",
                        "maxLength": 50,
                    },
                    "enabled": {
                        "type": "boolean",
                        "description": "Set to false to pause, true to resume (edit only)",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
    policy=ToolExecutionPolicy(side_effecting=True),
    prompt_hint=(
        "Use the cron tool to manage scheduled jobs and reminders. Set action"
        " to one of:\n"
        '- action "add": Create a new job. Provide name and schedule. Choose'
        " the right schedule kind:\n"
        '  - kind "at" with an ISO 8601 timestamp for one-time events'
        ' (e.g. "2026-02-24T15:00:00-05:00")\n'
        '  - kind "every" with every_ms in milliseconds for recurring'
        " intervals (e.g. 3600000 for hourly)\n"
        '  - kind "cron" with a 5-field cron expression for calendar-based'
        ' recurrence (e.g. "0 9 * * *" for daily 9am UTC)\n'
        '- action "list": Show the user\'s active scheduled jobs.\n'
        '- action "remove": Delete a job by its job_id.\n'
        '- action "edit": Modify a job by its job_id. Can change name,'
        " schedule, or enabled (false to pause, true to resume).\n"
        "When scheduling a reminder, write the name so it reads naturally"
        " when it fires. Include enough context from the current conversation"
        " that the reminder is self-contained \u2014 it will fire without access"
        " to this conversation history."
    ),
)

_WRITE_FILE = ToolSpec(
    name="write_file",
    tool_schema={
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write content to a file in your workspace. "
                "Creates the file if it doesn't exist. Use for "
                "saving reports, data exports, or intermediate "
                "results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path within your workspace",
                        "maxLength": 256,
                    },
                    "content": {
                        "type": "string",
                        "description": "File content to write",
                        "maxLength": 50000,
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    policy=ToolExecutionPolicy(side_effecting=True),
    prompt_hint=(
        "Use write_file to save reports, data exports, or intermediate "
        "results to your workspace. Provide a relative path and content."
    ),
)

_DELIVER_OUTPUT = ToolSpec(
    name="deliver_output",
    tool_schema={
        "type": "function",
        "function": {
            "name": "deliver_output",
            "description": (
                "Deliver a named output to its configured channel. "
                "The output name must match one of the outputs "
                "defined in your run context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "output_name": {
                        "type": "string",
                        "description": ("Name of the output to deliver (must match run context)"),
                        "maxLength": 64,
                    },
                    "content": {
                        "type": "string",
                        "description": "The output content to deliver",
                        "maxLength": 50000,
                    },
                },
                "required": ["output_name", "content"],
                "additionalProperties": False,
            },
        },
    },
    policy=ToolExecutionPolicy(
        memoize_duplicate_calls_within_turn=False,
        side_effecting=True,
    ),
    prompt_hint=(
        "Use deliver_output to send a named output to its configured "
        "delivery channel. The output_name must match one of the outputs "
        "listed in your run context. The platform handles routing \u2014 you "
        "don't need to know the delivery channel."
    ),
)


# ---------------------------------------------------------------------------
# The registry: ordered list of all tool specs
# ---------------------------------------------------------------------------

TOOL_REGISTRY: tuple[ToolSpec, ...] = (
    _CURRENT_DATETIME,
    _WEB_SEARCH,
    _WEB_FETCH,
    _WEB_EXTRACT,
    _DEEP_RESEARCH,
    _EXECUTE_SQL,
    _LIST_DATABASES,
    _CRON,
    _WRITE_FILE,
    _DELIVER_OUTPUT,
)

_SPEC_BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in TOOL_REGISTRY}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_spec(name: str) -> ToolSpec | None:
    """Look up a tool spec by name, or ``None`` if unknown."""
    return _SPEC_BY_NAME.get(name)


def get_tool_schemas(tool_names: list[str]) -> list[dict]:
    """Return OpenAI-format tool schemas for the requested tools only."""
    return [_SPEC_BY_NAME[n].tool_schema for n in tool_names if n in _SPEC_BY_NAME]


def get_execution_policy(name: str) -> ToolExecutionPolicy:
    """Return the execution policy for a tool, or the default for unknowns."""
    spec = _SPEC_BY_NAME.get(name)
    if spec is not None:
        return spec.policy
    return _DEFAULT_POLICY


_RESPONSE_BEHAVIOUR = """\
Response behavior for tool loops:
- If you need tools, put a short acknowledgment in your response \
and include tool calls.
- You may include multiple tool calls when they are clearly needed \
in the same turn.
- Tool calls are executed sequentially in listed order.
- Keep acknowledgments brief and avoid claiming success before \
the tool result.
- After receiving tool results, do not narrate every internal step. \
Either call the next tool or provide the final user-facing answer.

Otherwise, respond directly."""


def build_tool_instructions(tool_names: list[str]) -> str:
    """Assemble LLM tool-usage instructions for the requested tools only."""
    parts: list[str] = []
    for name in tool_names:
        spec = _SPEC_BY_NAME.get(name)
        if spec is not None:
            hint = spec.prompt_hint.strip()
            if hint:
                parts.append(hint)
    parts.append(_RESPONSE_BEHAVIOUR)
    return "\n\n".join(parts)

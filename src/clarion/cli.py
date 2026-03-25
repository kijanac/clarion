"""Clarion CLI — the main entry point for the platform."""

from __future__ import annotations

import asyncio
import os
import signal
from datetime import UTC, datetime
from pathlib import Path

import structlog
import typer
import uvicorn
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from clarion.adapters.telegram import TelegramAdapter
from clarion.agent_config import ConfigValidationError, load_agent_config
from clarion.agent_runner import new_run_id, run_agent
from clarion.agent_state import ensure_workspace
from clarion.api import create_app
from clarion.daemon import Daemon
from clarion.llm_client import OpenAIStreamingClient
from clarion.logging import configure_logging
from clarion.models import OutputType, RunContext
from clarion.tools.executor import ToolExecutor

load_dotenv()

log = structlog.get_logger()

app = typer.Typer(
    name="clarion",
    help="Clarion — a self-hosted team intelligence platform",
    no_args_is_help=True,
)
console = Console()


def _find_repo_root() -> Path:
    """Walk up from CWD to find the repo root (contains pyproject.toml)."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return current


def _data_root() -> Path:
    """Return the data directory root. Defaults to <repo>/data/."""
    env = os.environ.get("CLARION_DATA_DIR", "").strip()
    if env:
        return Path(env)
    return _find_repo_root() / "data"


# ── clarion run ─────────────────────────────────────────────────────────


@app.command()
def run(
    agent: str = typer.Option(
        ...,
        "--agent",
        "-a",
        help="Agent ID (directory name under agents/)",
    ),
    json_logs: bool = typer.Option(
        False,
        "--json-logs",
        help="Output logs as JSON lines (default: human-readable)",
    ),
) -> None:
    """Execute a single agent run."""
    configure_logging(json=json_logs, level="INFO")

    try:
        result = asyncio.run(_run_agent(agent))
    except Exception as exc:
        console.print(f"[red]Fatal error: {exc}[/red]")
        raise typer.Exit(1)

    _print_run_summary(result)

    if result.status.value != "success":
        raise typer.Exit(1)


async def _run_agent(agent_id: str):
    """Load config, assemble context, run the agent."""
    repo_root = _find_repo_root()

    agent_dir = repo_root / "agents" / agent_id
    if not agent_dir.exists():
        raise FileNotFoundError(f"Agent directory not found: {agent_dir}")

    try:
        config = load_agent_config(
            agent_dir=agent_dir,
            agent_id=agent_id,
            templates_dir=repo_root / "templates",
        )
    except ConfigValidationError as exc:
        raise RuntimeError(f"Invalid agent config: {exc}") from exc

    console.print(f"Agent: [bold]{config.name}[/bold] ({agent_id})")
    console.print(f"Template: {config.template}")
    console.print(f"Model: {config.model}")

    data_root = _data_root()
    workspace = ensure_workspace(data_root / "agents" / agent_id)

    mission_path = workspace / "mission.md"
    if not mission_path.exists():
        raise FileNotFoundError(
            f"Mission file not found: {mission_path}\n"
            f"Create it at: {mission_path}"
        )
    mission_md = mission_path.read_text()
    console.print(f"Mission: {mission_path}")

    adapters = {}
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if bot_token:
        adapters[OutputType.TELEGRAM] = TelegramAdapter(bot_token)
        console.print("Telegram: [green]configured[/green]")
    else:
        console.print("Telegram: [yellow]not configured (TELEGRAM_BOT_TOKEN not set)[/yellow]")

    llm_client = OpenAIStreamingClient()
    executor = ToolExecutor(
        agent_id=agent_id,
        agent_config=config,
        workspace_root=workspace,
        delivery_adapters=adapters,
    )

    run_id = new_run_id()
    context = RunContext(
        agent_id=agent_id,
        run_id=run_id,
        config=config,
        mission_md=mission_md,
        workspace_root=str(workspace),
        trigger="manual",
        current_datetime=datetime.now(UTC),
    )

    console.print(f"Run ID: {run_id}")
    console.print("---")

    result = await run_agent(context, llm_client, executor)
    return result


def _print_run_summary(run) -> None:
    """Print a summary of the completed run."""
    status_colors = {
        "success": "green",
        "failed": "red",
        "timeout": "yellow",
        "cancelled": "yellow",
    }
    color = status_colors.get(run.status.value, "white")

    console.print("---")
    console.print(f"Status: [{color}]{run.status.value}[/{color}]")

    if run.completed_at and run.started_at:
        duration = (run.completed_at - run.started_at).total_seconds()
        console.print(f"Duration: {duration:.1f}s")

    if run.error:
        console.print(f"Error: [red]{run.error}[/red]")

    if run.outputs_produced:
        console.print(f"Outputs: {', '.join(run.outputs_produced)}")

    if run.tool_call_counts:
        table = Table(title="Tool Calls")
        table.add_column("Tool")
        table.add_column("Count", justify="right")
        for tool, count in sorted(run.tool_call_counts.items()):
            table.add_row(tool, str(count))
        console.print(table)


# ── clarion daemon ──────────────────────────────────────────────────────


@app.command()
def daemon(
    max_concurrent: int = typer.Option(
        5,
        "--max-concurrent",
        help="Maximum concurrent agent runs",
    ),
    web_port: int = typer.Option(
        0,
        "--web-port",
        help="Start embedded web UI on this port (0 = disabled)",
    ),
    json_logs: bool = typer.Option(
        True,
        "--json-logs/--no-json-logs",
        help="JSON log output (default for daemon)",
    ),
) -> None:
    """Start the Clarion daemon. Runs until interrupted."""
    configure_logging(json=json_logs, level="INFO")

    repo_root = _find_repo_root()
    d = Daemon(
        agents_dir=repo_root / "agents",
        templates_dir=repo_root / "templates",
        data_root=_data_root(),
        max_concurrent_runs=max_concurrent,
    )

    loop = asyncio.new_event_loop()

    if web_port:
        api_app = create_app(
            agents_dir=repo_root / "agents",
            templates_dir=repo_root / "templates",
            data_root=_data_root(),
            daemon=d,
            static_dir=Path(__file__).parent / "static",
        )
        uvi_config = uvicorn.Config(
            api_app, host="0.0.0.0", port=web_port, log_level="warning"
        )
        uvi_server = uvicorn.Server(uvi_config)
        loop.create_task(uvi_server.serve())
        console.print(f"Web UI: [green]http://0.0.0.0:{web_port}[/green]")

    def _handle_signal() -> None:
        loop.create_task(d.shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    try:
        loop.run_until_complete(d.start())
    finally:
        loop.close()


# ── clarion web ─────────────────────────────────────────────────────────


@app.command()
def web(
    port: int = typer.Option(8100, "--port", "-p", help="API server port"),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address"),
    dev: bool = typer.Option(False, "--dev", help="Enable CORS for local Vite dev server"),
    json_logs: bool = typer.Option(
        True,
        "--json-logs/--no-json-logs",
        help="JSON log output",
    ),
) -> None:
    """Start the Clarion web API server (no daemon)."""
    configure_logging(json=json_logs, level="INFO")

    repo_root = _find_repo_root()
    api_app = create_app(
        agents_dir=repo_root / "agents",
        templates_dir=repo_root / "templates",
        data_root=_data_root(),
        static_dir=Path(__file__).parent / "static",
        dev=dev,
    )

    console.print(f"Clarion API: [green]http://{host}:{port}[/green]")
    if dev:
        console.print("[yellow]CORS enabled for localhost:5173[/yellow]")

    uvicorn.run(api_app, host=host, port=port, log_level="warning")


# ── clarion register ────────────────────────────────────────────────────


@app.command()
def register(
    agent_dir: Path = typer.Argument(
        ...,
        help="Path to agent directory containing agent.yaml",
    ),
) -> None:
    """Validate an agent config and confirm it's ready to run."""
    repo_root = _find_repo_root()
    agent_id = agent_dir.name

    try:
        config = load_agent_config(
            agent_dir=agent_dir,
            agent_id=agent_id,
            templates_dir=repo_root / "templates",
        )
    except ConfigValidationError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] agent.yaml valid")
    console.print(f"[green]✓[/green] template: {config.template}")
    trigger_strs = []
    for t in config.triggers:
        if t.type.value == "cron":
            trigger_strs.append(f"cron({t.expression})")
        elif t.type.value == "agent_output":
            trigger_strs.append(f"agent_output({t.source_agent}:{t.output_name})")
    console.print(f"[green]✓[/green] triggers: {', '.join(trigger_strs) or 'none'}")
    console.print(f"[green]✓[/green] tools: {', '.join(config.tools)}")
    console.print(f"[green]✓[/green] outputs: {len(config.outputs)} defined")

    workspace = _data_root() / "agents" / agent_id
    mission = workspace / "mission.md"
    if mission.exists():
        console.print(f"[green]✓[/green] mission: {mission}")
    else:
        console.print(f"[yellow]![/yellow] mission not found: {mission}")
        console.print("  Create it before running the agent.")

    console.print(f"\n[bold]Agent '{agent_id}' is valid and ready.[/bold]")


# ── clarion health ──────────────────────────────────────────────────────


@app.command()
def health() -> None:
    """Check that the Clarion environment is properly configured."""
    all_ok = True

    base_url = os.environ.get("LLM_BASE_URL", "")
    api_key = os.environ.get("LLM_API_KEY", "")
    if base_url and api_key:
        console.print(f"[green]✓[/green] LLM: {base_url}")
    else:
        console.print("[red]✗[/red] LLM: LLM_BASE_URL and/or LLM_API_KEY not set")
        all_ok = False

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if bot_token:
        console.print("[green]✓[/green] Telegram: configured")
    else:
        console.print("[yellow]![/yellow] Telegram: TELEGRAM_BOT_TOKEN not set (optional)")

    data = _data_root()
    if data.exists():
        console.print(f"[green]✓[/green] Data dir: {data}")
    else:
        console.print(f"[yellow]![/yellow] Data dir not found: {data}")

    templates = _find_repo_root() / "templates"
    if templates.exists():
        template_names = [p.stem for p in templates.glob("*.yaml")]
        console.print(f"[green]✓[/green] Templates: {', '.join(template_names)}")
    else:
        console.print("[red]✗[/red] Templates directory not found")
        all_ok = False

    agents_dir = _find_repo_root() / "agents"
    if agents_dir.exists():
        agent_names = [p.name for p in agents_dir.iterdir() if p.is_dir()]
        console.print(f"[green]✓[/green] Agents: {', '.join(agent_names) or 'none'}")
    else:
        console.print("[yellow]![/yellow] No agents directory found")

    if all_ok:
        console.print("\n[bold green]Environment OK[/bold green]")
    else:
        console.print("\n[bold red]Environment has issues[/bold red]")
        raise typer.Exit(1)

"""Clarion web API — layer 5 (entrypoints).

App factory pattern: create_app() returns a configured FastAPI instance.
Reads agent configs, run history, and conversation turns from the filesystem.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from clarion.agent_config import ConfigValidationError, load_agent_config
from clarion.agent_state import last_run, load_run_history, load_run_turns
from clarion.models import AgentRun

log = structlog.get_logger()


def create_app(
    *,
    agents_dir: Path,
    templates_dir: Path,
    data_root: Path,
    daemon: Any = None,
    static_dir: Path | None = None,
    dev: bool = False,
) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="Clarion", docs_url="/api/docs", openapi_url="/api/openapi.json")

    if dev:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    def _load_all_agents() -> dict[str, dict]:
        """Scan agents/ dir and load all valid configs."""
        agents = {}
        if not agents_dir.exists():
            return agents
        for agent_path in sorted(agents_dir.iterdir()):
            if not agent_path.is_dir():
                continue
            if not (agent_path / "agent.yaml").exists():
                continue
            agent_id = agent_path.name
            try:
                config = load_agent_config(
                    agent_dir=agent_path,
                    agent_id=agent_id,
                    templates_dir=templates_dir,
                )
                agents[agent_id] = config
            except ConfigValidationError:
                log.warning("api.invalid_agent_config", agent_id=agent_id)
        return agents

    def _workspace(agent_id: str) -> Path:
        return data_root / "agents" / agent_id

    def _agent_summary(agent_id: str, config: Any) -> dict:
        ws = _workspace(agent_id)
        lr = last_run(ws)
        return {
            "id": agent_id,
            "name": config.name,
            "description": config.description,
            "owner": config.owner,
            "template": config.template,
            "schedule_cron": config.schedule_cron,
            "schedule_timezone": config.schedule_timezone,
            "last_run_status": lr.status.value if lr else None,
            "last_run_at": lr.started_at.isoformat() if lr else None,
            "outputs_count": len(config.outputs),
            "runs_today": _count_runs_today(ws),
            "max_runs_per_day": config.resources.max_runs_per_day,
        }

    def _count_runs_today(ws: Path) -> int:
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        runs = load_run_history(ws, limit=100)
        return sum(1 for r in runs if r.started_at >= today_start)

    def _find_config(agent_id: str):
        agents = _load_all_agents()
        if agent_id not in agents:
            raise HTTPException(404, f"Agent '{agent_id}' not found")
        return agents[agent_id]

    def _find_run(ws: Path, run_id: str) -> AgentRun:
        runs = load_run_history(ws, limit=500)
        for r in runs:
            if r.run_id == run_id:
                return r
        raise HTTPException(404, f"Run '{run_id}' not found")

    # ── Routes ───────────────────────────────────────────────────────────

    @app.get("/api/agents")
    def list_agents():
        agents = _load_all_agents()
        return [_agent_summary(aid, cfg) for aid, cfg in agents.items()]

    @app.get("/api/agents/{agent_id}")
    def get_agent(agent_id: str):
        config = _find_config(agent_id)
        ws = _workspace(agent_id)

        mission_md = ""
        mission_path = ws / "mission.md"
        if mission_path.exists():
            mission_md = mission_path.read_text(encoding="utf-8")

        lr = last_run(ws)
        return {
            **_agent_summary(agent_id, config),
            "mission_md": mission_md,
            "outputs": [o.model_dump() for o in config.outputs],
            "resources": config.resources.model_dump(),
            "tools": config.tools,
            "model": config.model,
            "last_run": lr.model_dump(mode="json") if lr else None,
        }

    @app.get("/api/agents/{agent_id}/runs")
    def list_runs(agent_id: str, limit: int = 20, offset: int = 0):
        _find_config(agent_id)
        ws = _workspace(agent_id)
        all_runs = load_run_history(ws, limit=offset + limit)
        page = all_runs[offset : offset + limit]
        return [r.model_dump(mode="json") for r in page]

    @app.get("/api/agents/{agent_id}/runs/{run_id}")
    def get_run(agent_id: str, run_id: str):
        _find_config(agent_id)
        ws = _workspace(agent_id)
        run = _find_run(ws, run_id)
        turns = load_run_turns(ws, run_id)
        return {
            **run.model_dump(mode="json"),
            "turns": turns,
        }

    @app.post("/api/agents/{agent_id}/run")
    async def trigger_run(agent_id: str):
        _find_config(agent_id)
        if daemon is None:
            raise HTTPException(503, "Manual runs require the daemon (use clarion daemon --web-port)")
        await daemon._fire_run(agent_id, trigger="manual_web")
        return {"status": "triggered", "agent_id": agent_id}

    # ── Static files (production) ────────────────────────────────────────

    if static_dir and static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app

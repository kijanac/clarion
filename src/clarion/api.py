"""Clarion web API — layer 5 (entrypoints).

App factory pattern: create_app() returns a configured FastAPI instance.
Reads agent configs, run history, and conversation turns from the filesystem.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from clarion.agent_config import (
    ConfigValidationError,
    load_agent_config,
    parse_triggers,
)
from clarion.agent_state import ensure_workspace, load_run_history, load_run_turns
from clarion.models import AgentRun

log = structlog.get_logger()


class CreateAgentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    owner: str = Field(min_length=1, max_length=64)
    template: str = Field(min_length=1)
    mission: str = Field(min_length=1)
    triggers: list[dict] = Field(default_factory=lambda: [{"type": "cron", "expression": "0 6 * * 1", "timezone": "UTC"}])


class UpdateMissionRequest(BaseModel):
    mission: str = Field(min_length=1)


class UpdateAgentRequest(BaseModel):
    triggers: list[dict] | None = None
    description: str | None = None
    owner: str | None = None


class UpdateTemplateRequest(BaseModel):
    model: str | None = None
    system_prompt: str | None = None
    tools: list[str] | None = None
    max_tokens: int | None = None
    resources: dict[str, int] | None = None


def _validate_inputs(triggers: list[dict] | None = None) -> None:
    """Validate trigger definitions, converting ConfigValidationError to HTTPException."""
    try:
        if triggers is not None:
            parse_triggers(triggers)
    except ConfigValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


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
            allow_origins=["http://localhost:5173", "http://localhost:5174"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    def _workspace(agent_id: str) -> Path:
        return data_root / "agents" / agent_id

    def _load_config(agent_id: str):
        """Load a single agent's config. Raises 404 if not found."""
        agent_path = agents_dir / agent_id
        if not agent_path.is_dir() or not (agent_path / "agent.yaml").exists():
            raise HTTPException(404, f"Agent '{agent_id}' not found")
        try:
            return load_agent_config(
                agent_dir=agent_path,
                agent_id=agent_id,
                templates_dir=templates_dir,
            )
        except ConfigValidationError as exc:
            raise HTTPException(500, f"Agent '{agent_id}' has invalid config: {exc}") from exc

    def _agent_summary(agent_id: str, config: Any, runs: list[AgentRun] | None = None) -> dict:
        if runs is None:
            ws = _workspace(agent_id)
            runs = load_run_history(ws, limit=100)
        lr = runs[0] if runs else None
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        runs_today = sum(1 for r in runs if r.started_at >= today_start)
        return {
            "id": agent_id,
            "name": config.name,
            "description": config.description,
            "owner": config.owner,
            "template": config.template,
            "triggers": [t.model_dump() for t in config.triggers],
            "last_run_status": lr.status.value if lr else None,
            "last_run_at": lr.started_at.isoformat() if lr else None,
            "outputs_count": len(config.outputs),
            "runs_today": runs_today,
            "max_runs_per_day": config.resources.max_runs_per_day,
        }

    def _find_run(ws: Path, run_id: str) -> AgentRun:
        runs = load_run_history(ws, limit=500)
        for r in runs:
            if r.run_id == run_id:
                return r
        raise HTTPException(404, f"Run '{run_id}' not found")

    # ── Read routes ──────────────────────────────────────────────────────

    @app.get("/api/agents")
    def list_agents():
        results = []
        if not agents_dir.exists():
            return results
        for agent_path in sorted(agents_dir.iterdir()):
            if not agent_path.is_dir() or not (agent_path / "agent.yaml").exists():
                continue
            agent_id = agent_path.name
            try:
                config = load_agent_config(
                    agent_dir=agent_path,
                    agent_id=agent_id,
                    templates_dir=templates_dir,
                )
                results.append(_agent_summary(agent_id, config))
            except ConfigValidationError:
                log.warning("api.invalid_agent_config", agent_id=agent_id)
        return results

    @app.get("/api/agents/{agent_id}")
    def get_agent(agent_id: str):
        config = _load_config(agent_id)
        ws = _workspace(agent_id)
        runs = load_run_history(ws, limit=100)

        mission_md = ""
        mission_path = ws / "mission.md"
        if mission_path.exists():
            mission_md = mission_path.read_text(encoding="utf-8")

        lr = runs[0] if runs else None
        return {
            **_agent_summary(agent_id, config, runs),
            "mission_md": mission_md,
            "outputs": [o.model_dump() for o in config.outputs],
            "resources": config.resources.model_dump(),
            "tools": config.tools,
            "model": config.model,
            "last_run": lr.model_dump(mode="json") if lr else None,
        }

    @app.get("/api/agents/{agent_id}/runs")
    def list_runs(agent_id: str, limit: int = 20, offset: int = 0):
        _load_config(agent_id)
        ws = _workspace(agent_id)
        all_runs = load_run_history(ws, limit=offset + limit)
        page = all_runs[offset : offset + limit]
        return [r.model_dump(mode="json") for r in page]

    @app.get("/api/agents/{agent_id}/runs/{run_id}")
    def get_run(agent_id: str, run_id: str):
        _load_config(agent_id)
        ws = _workspace(agent_id)
        run = _find_run(ws, run_id)
        turns = load_run_turns(ws, run_id)
        return {
            **run.model_dump(mode="json"),
            "turns": turns,
        }

    @app.post("/api/agents/{agent_id}/run")
    async def trigger_run(agent_id: str):
        _load_config(agent_id)
        if daemon is None:
            raise HTTPException(503, "Manual runs require the daemon (use clarion daemon --web-port)")
        await daemon.trigger_run(agent_id, trigger="manual_web")
        return {"status": "triggered", "agent_id": agent_id}

    # ── Templates ────────────────────────────────────────────────────────

    @app.get("/api/templates")
    def list_templates():
        results = []
        if not templates_dir.exists():
            return results
        for path in sorted(templates_dir.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            results.append({
                "id": path.stem,
                "name": raw.get("name", path.stem),
                "description": raw.get("description", ""),
                "tools": raw.get("tools", []),
                "model": raw.get("model", ""),
            })
        return results

    @app.get("/api/templates/{template_id}")
    def get_template(template_id: str):
        path = templates_dir / f"{template_id}.yaml"
        if not path.exists():
            raise HTTPException(404, f"Template '{template_id}' not found")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return {
            "id": path.stem,
            "name": raw.get("name", path.stem),
            "description": raw.get("description", ""),
            "tools": raw.get("tools", []),
            "model": raw.get("model", ""),
            "max_tokens": raw.get("max_tokens", 8192),
            "system_prompt": raw.get("system_prompt", ""),
            "resources": raw.get("resources", {}),
        }

    @app.put("/api/templates/{template_id}")
    def update_template(template_id: str, req: UpdateTemplateRequest):
        path = templates_dir / f"{template_id}.yaml"
        if not path.exists():
            raise HTTPException(404, f"Template '{template_id}' not found")

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))

        if req.model is not None:
            raw["model"] = req.model
        if req.system_prompt is not None:
            raw["system_prompt"] = req.system_prompt
        if req.tools is not None:
            raw["tools"] = req.tools
        if req.max_tokens is not None:
            raw["max_tokens"] = req.max_tokens
        if req.resources is not None:
            raw["resources"] = req.resources

        path.write_text(
            yaml.dump(raw, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        log.info("api.template_updated", template_id=template_id)

        return get_template(template_id)

    # ── Write routes ─────────────────────────────────────────────────────

    @app.post("/api/agents", status_code=201)
    def create_agent(req: CreateAgentRequest):
        template_path = templates_dir / f"{req.template}.yaml"
        if not template_path.exists():
            raise HTTPException(400, f"Template '{req.template}' not found")

        _validate_inputs(triggers=req.triggers)

        agent_id = re.sub(r"[^a-z0-9]+", "-", req.name.lower()).strip("-")[:64]
        if not agent_id:
            raise HTTPException(400, "Could not generate agent ID from name")

        agent_dir = agents_dir / agent_id
        if agent_dir.exists():
            raise HTTPException(409, f"Agent '{agent_id}' already exists")

        agent_yaml = {
            "meta": {
                "name": req.name,
                "description": req.description,
                "owner": req.owner,
                "version": 1,
            },
            "template": req.template,
            "triggers": req.triggers,
            "database": {"enabled": True},
            "outputs": [],
            "resources": {},
        }

        agent_dir.mkdir(parents=True)
        (agent_dir / "agent.yaml").write_text(
            yaml.dump(agent_yaml, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

        ws = ensure_workspace(_workspace(agent_id))
        (ws / "mission.md").write_text(req.mission, encoding="utf-8")

        log.info("api.agent_created", agent_id=agent_id)

        config = load_agent_config(
            agent_dir=agent_dir,
            agent_id=agent_id,
            templates_dir=templates_dir,
        )
        return _agent_summary(agent_id, config)

    @app.put("/api/agents/{agent_id}/mission")
    def update_mission(agent_id: str, req: UpdateMissionRequest):
        _load_config(agent_id)
        ws = ensure_workspace(_workspace(agent_id))
        (ws / "mission.md").write_text(req.mission, encoding="utf-8")
        log.info("api.mission_updated", agent_id=agent_id)
        return {"status": "updated", "agent_id": agent_id}

    @app.put("/api/agents/{agent_id}")
    def update_agent(agent_id: str, req: UpdateAgentRequest):
        _load_config(agent_id)

        _validate_inputs(triggers=req.triggers)

        agent_yaml_path = agents_dir / agent_id / "agent.yaml"
        raw = yaml.safe_load(agent_yaml_path.read_text(encoding="utf-8"))

        if req.triggers is not None:
            raw["triggers"] = req.triggers
        if req.description is not None:
            raw.setdefault("meta", {})["description"] = req.description
        if req.owner is not None:
            raw.setdefault("meta", {})["owner"] = req.owner

        agent_yaml_path.write_text(
            yaml.dump(raw, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        log.info("api.agent_updated", agent_id=agent_id)

        config = load_agent_config(
            agent_dir=agents_dir / agent_id,
            agent_id=agent_id,
            templates_dir=templates_dir,
        )
        return _agent_summary(agent_id, config)

    # ── Static files (production) ────────────────────────────────────────

    if static_dir and static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app

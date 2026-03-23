"""Agent registry — layer 3.

In-memory registry of all configured agents. Scans agents/ directory
at startup, watches for changes. Maintains last-valid config for each
agent — if an edit to agent.yaml is invalid, the previous valid config
continues to be used (with an error logged).
"""

from __future__ import annotations

from pathlib import Path

import structlog

from clarion.agent_config import ConfigValidationError, load_agent_config
from clarion.models import AgentConfig

log = structlog.get_logger()


class AgentRegistry:
    """In-memory registry of all configured agents.

    Scans agents/ directory at startup, watches for changes.
    Maintains last-valid config for each agent — if an edit to
    agent.yaml is invalid, the previous valid config continues
    to be used (with an error logged).
    """

    def __init__(
        self,
        agents_dir: Path,
        templates_dir: Path,
        data_root: Path,
    ) -> None:
        self._agents_dir = agents_dir
        self._templates_dir = templates_dir
        self._data_root = data_root
        self._configs: dict[str, AgentConfig] = {}

    def scan(self) -> None:
        """Scan agents/ directory and register all valid agents."""
        if not self._agents_dir.exists():
            log.warning("registry.scan_skip", reason="agents dir not found")
            return

        for entry in sorted(self._agents_dir.iterdir()):
            if not entry.is_dir():
                continue
            if not (entry / "agent.yaml").exists():
                continue
            agent_id = entry.name
            try:
                config = load_agent_config(
                    agent_dir=entry,
                    agent_id=agent_id,
                    templates_dir=self._templates_dir,
                )
                self._configs[agent_id] = config
                log.info("registry.registered", agent_id=agent_id)
            except (ConfigValidationError, Exception) as exc:
                log.error("registry.invalid_config", agent_id=agent_id, error=str(exc))

    def get(self, agent_id: str) -> AgentConfig | None:
        """Get the current config for an agent, or None."""
        return self._configs.get(agent_id)

    def all_agents(self) -> dict[str, AgentConfig]:
        """Return all registered agents."""
        return dict(self._configs)

    def reload_agent(self, agent_id: str) -> AgentConfig | None:
        """Re-read and re-validate an agent's config.

        If the new config is valid, update the registry.
        If invalid, keep the old config and log an error.
        Returns the active config (old or new).
        """
        agent_dir = self._agents_dir / agent_id
        if not (agent_dir / "agent.yaml").exists():
            log.error("registry.reload_skip", agent_id=agent_id, reason="no agent.yaml")
            return self._configs.get(agent_id)

        try:
            config = load_agent_config(
                agent_dir=agent_dir,
                agent_id=agent_id,
                templates_dir=self._templates_dir,
            )
            self._configs[agent_id] = config
            log.info("registry.reloaded", agent_id=agent_id)
            return config
        except (ConfigValidationError, Exception) as exc:
            log.error(
                "registry.reload_invalid",
                agent_id=agent_id,
                error=str(exc),
            )
            return self._configs.get(agent_id)

    def reload_mission(self, agent_id: str) -> str | None:
        """Re-read an agent's mission.md from disk.

        Returns the updated mission text, or None if not found.
        """
        workspace = self._data_root / "agents" / agent_id
        mission_path = workspace / "mission.md"
        if not mission_path.exists():
            return None
        return mission_path.read_text()

    def remove_agent(self, agent_id: str) -> None:
        """Unregister an agent (directory was removed)."""
        if agent_id in self._configs:
            del self._configs[agent_id]
            log.info("registry.removed", agent_id=agent_id)

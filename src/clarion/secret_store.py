"""Per-agent secret storage — layer 0.

File-per-credential with 0600 permissions. Secrets live at
data/agents/<agent_id>/.secrets/<tool_name>.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

KNOWN_TOOLS: frozenset[str] = frozenset({
    "brave_search",
    "perplexity_search",
    "telegram",
    "github",
    "slack",
})

_SECRETS_DIR_NAME = ".secrets"
_SECRETS_DIR_MODE = 0o700
_SECRET_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0600


def _validate_tool_name(tool_name: str) -> None:
    """Reject unknown tool names to prevent arbitrary file creation."""
    if tool_name not in KNOWN_TOOLS:
        raise ValueError(
            f"Unknown tool {tool_name!r}. Known tools: {sorted(KNOWN_TOOLS)}"
        )


def store_secret(agent_id: str, tool_name: str, value: str, workspace_root: Path) -> Path:
    """Store a credential. Creates .secrets/ dir if needed. Sets 0600 perms.

    Returns the path to the stored secret file.
    """
    _validate_tool_name(tool_name)
    secrets_dir = workspace_root / _SECRETS_DIR_NAME
    secrets_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(secrets_dir, _SECRETS_DIR_MODE)
    secret_file = secrets_dir / tool_name
    secret_file.write_text(value)
    secret_file.chmod(_SECRET_FILE_MODE)
    return secret_file


def load_secret(agent_id: str, tool_name: str, workspace_root: Path) -> str | None:
    """Load a credential, or None if not set."""
    _validate_tool_name(tool_name)
    secret_file = workspace_root / _SECRETS_DIR_NAME / tool_name
    if not secret_file.exists():
        return None
    return secret_file.read_text().strip()

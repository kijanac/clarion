"""Platform credential storage — layer 0.

Single entry point for secrets. Lookup order:
  1. Platform secrets: $CLARION_DATA_DIR/platform/.secrets/<key>
  2. Environment variables: KEY (uppercased)

File-per-credential with 0600 permissions.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

_SECRETS_DIR_NAME = ".secrets"
_SECRETS_DIR_MODE = 0o700
_SECRET_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0600


def _platform_secrets_dir() -> Path | None:
    """Return the platform secrets directory, or None if CLARION_DATA_DIR is not set."""
    data_dir = os.environ.get("CLARION_DATA_DIR", "").strip()
    if not data_dir:
        return None
    return Path(data_dir) / "platform" / _SECRETS_DIR_NAME


def load_secret(key: str) -> str | None:
    """Load a credential by key.

    Checks platform secrets directory first, then falls back
    to environment variables.
    """
    # 1. Platform secrets file
    secrets_dir = _platform_secrets_dir()
    if secrets_dir is not None:
        secret_file = secrets_dir / key
        if secret_file.exists():
            value = secret_file.read_text().strip()
            if value:
                return value

    # 2. Environment variable fallback (uppercase)
    env_val = os.environ.get(key.upper(), "").strip()
    if env_val:
        return env_val

    return None


def store_secret(key: str, value: str) -> Path:
    """Store a platform credential. Requires CLARION_DATA_DIR to be set.

    Returns the path to the stored secret file.
    """
    secrets_dir = _platform_secrets_dir()
    if secrets_dir is None:
        raise RuntimeError("CLARION_DATA_DIR must be set to store secrets")
    secrets_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(secrets_dir, _SECRETS_DIR_MODE)
    secret_file = secrets_dir / key
    secret_file.write_text(value)
    secret_file.chmod(_SECRET_FILE_MODE)
    return secret_file

"""Tests for clarion.secret_store — layer 0 credential storage."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from clarion.secret_store import load_secret, store_secret


class TestSecretStoreRoundtrip:
    def test_store_and_load(self, tmp_workspace: Path) -> None:
        store_secret("test-agent", "telegram", "my-token", tmp_workspace)
        assert load_secret("test-agent", "telegram", tmp_workspace) == "my-token"

    def test_load_missing_returns_none(self, tmp_workspace: Path) -> None:
        assert load_secret("test-agent", "brave_search", tmp_workspace) is None

    def test_file_permissions_0600(self, tmp_workspace: Path) -> None:
        store_secret("test-agent", "github", "ghp_abc123", tmp_workspace)
        secret_file = tmp_workspace / ".secrets" / "github"
        mode = os.stat(secret_file).st_mode
        assert stat.S_IMODE(mode) == 0o600

    def test_overwrite_keeps_last_value(self, tmp_workspace: Path) -> None:
        store_secret("test-agent", "slack", "first", tmp_workspace)
        store_secret("test-agent", "slack", "second", tmp_workspace)
        assert load_secret("test-agent", "slack", tmp_workspace) == "second"

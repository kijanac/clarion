"""Tests for clarion.secret_store — platform credential storage."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

from clarion.secret_store import load_secret, store_secret


class TestLoadSecret:
    def test_platform_file_found(self, tmp_path: Path) -> None:
        secrets_dir = tmp_path / "platform" / ".secrets"
        secrets_dir.mkdir(parents=True)
        (secrets_dir / "brave_api_key").write_text("test-key")

        with patch.dict(os.environ, {"CLARION_DATA_DIR": str(tmp_path)}):
            assert load_secret("brave_api_key") == "test-key"

    def test_env_var_fallback(self) -> None:
        with patch.dict(os.environ, {"BRAVE_API_KEY": "env-key"}, clear=False):
            # No CLARION_DATA_DIR set, should fall back to env
            with patch.dict(os.environ, {"CLARION_DATA_DIR": ""}, clear=False):
                assert load_secret("brave_api_key") == "env-key"

    def test_missing_returns_none(self) -> None:
        with patch.dict(os.environ, {"CLARION_DATA_DIR": ""}, clear=False):
            assert load_secret("nonexistent_key") is None

    def test_platform_file_takes_precedence(self, tmp_path: Path) -> None:
        secrets_dir = tmp_path / "platform" / ".secrets"
        secrets_dir.mkdir(parents=True)
        (secrets_dir / "brave_api_key").write_text("file-key")

        with patch.dict(os.environ, {
            "CLARION_DATA_DIR": str(tmp_path),
            "BRAVE_API_KEY": "env-key",
        }):
            assert load_secret("brave_api_key") == "file-key"


class TestStoreSecret:
    def test_store_and_load(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {"CLARION_DATA_DIR": str(tmp_path)}):
            store_secret("telegram_bot_token", "my-token")
            assert load_secret("telegram_bot_token") == "my-token"

    def test_file_permissions_0600(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {"CLARION_DATA_DIR": str(tmp_path)}):
            path = store_secret("github_token", "ghp_abc123")
            mode = os.stat(path).st_mode
            assert stat.S_IMODE(mode) == 0o600

    def test_overwrite_keeps_last_value(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {"CLARION_DATA_DIR": str(tmp_path)}):
            store_secret("slack_token", "first")
            store_secret("slack_token", "second")
            assert load_secret("slack_token") == "second"

    def test_requires_data_dir(self) -> None:
        import pytest

        with patch.dict(os.environ, {"CLARION_DATA_DIR": ""}):
            with pytest.raises(RuntimeError, match="CLARION_DATA_DIR"):
                store_secret("key", "value")

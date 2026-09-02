"""Shared test fixtures and helpers.

The key pattern: redirect all path resolution to a temp dir so tests don't
pollute the real %APPDATA% / ~/.config.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from rdo_lobby_manager.config import paths as paths_module


@pytest.fixture
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect all user_data_dir/user_config_dir/user_cache_dir calls to tmp_path.

    Use this for any test that touches the filesystem, so the real user data
    is never at risk even if a test goes wrong.
    """
    data = tmp_path / "data"
    config = tmp_path / "config"
    cache = tmp_path / "cache"
    data.mkdir()
    config.mkdir()
    cache.mkdir()

    def _lobby_store_dir() -> Path:
        p = data / "lobbies"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _log_file() -> Path:
        p = cache / "logs" / "test.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    monkeypatch.setattr(paths_module, "user_data_dir", lambda: data)
    monkeypatch.setattr(paths_module, "user_config_dir", lambda: config)
    monkeypatch.setattr(paths_module, "user_cache_dir", lambda: cache)
    monkeypatch.setattr(paths_module, "user_log_dir", lambda: cache / "logs")
    monkeypatch.setattr(paths_module, "lobby_store_dir", _lobby_store_dir)
    monkeypatch.setattr(paths_module, "config_file", lambda: config / "config.json")
    monkeypatch.setattr(paths_module, "crypto_key_file", lambda: data / ".lobby_key")
    monkeypatch.setattr(paths_module, "log_file", _log_file)

    yield tmp_path


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Force a specific platform value for sys.platform-conditional logic.

    Defaults to "linux" since we develop on Linux. Override with
    `@pytest.mark.parametrize("platform", ["win32"], indirect=True)` to test
    Windows-specific paths.
    """
    p = os.environ.get("RDO_TEST_PLATFORM", "linux")
    monkeypatch.setattr(paths_module.sys, "platform", p)
    yield p

"""Tests for config/paths.py — verify XDG/AppData resolution and directory creation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


class TestUserDataDir:
    """user_data_dir returns the correct platform-specific path and creates it."""

    def test_linux_uses_xdg_data_home(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))

        # Import after monkeypatching so platform check picks it up
        from rdo_lobby_manager.config import paths

        result = paths.user_data_dir()
        assert result == tmp_path / ".local" / "share" / paths.APP_NAME
        assert result.exists()
        assert result.is_dir()

    def test_linux_respects_xdg_data_home(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        xdg = tmp_path / "custom_xdg"
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_DATA_HOME", str(xdg))

        from rdo_lobby_manager.config import paths

        result = paths.user_data_dir()
        assert result == xdg / paths.APP_NAME
        assert result.exists()

    def test_windows_uses_known_folder(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        appdata = tmp_path / "Roaming"
        appdata.mkdir()
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(appdata))

        from rdo_lobby_manager.config import paths

        result = paths.user_data_dir()
        assert result == appdata / paths.APP_NAME
        assert result.exists()

    def test_windows_falls_back_when_appdata_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """If APPDATA is unset on Windows, we fall back to ~/AppData/Roaming."""
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))  # POSIX fallback in some envs

        from rdo_lobby_manager.config import paths

        # We can't fully test the fallback on Linux because HOME handling differs,
        # but we can verify the function doesn't raise and returns a Path.
        result = paths.user_data_dir()
        assert isinstance(result, Path)
        assert result.name == paths.APP_NAME

    def test_creates_directory_if_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        target = tmp_path / "fresh" / "nested" / "RDOLobbyManager"
        assert not target.exists()
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "fresh" / "nested"))

        from rdo_lobby_manager.config import paths

        result = paths.user_data_dir()
        assert result.exists()
        assert result.is_dir()


class TestUserConfigDir:
    """On Windows, config and data are the same dir; on Linux, XDG_CONFIG_HOME."""

    def test_linux_uses_xdg_config_home(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))

        from rdo_lobby_manager.config import paths

        result = paths.user_config_dir()
        assert result == tmp_path / ".config" / paths.APP_NAME
        assert result.exists()

    def test_windows_equals_data_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        appdata = tmp_path / "Roaming"
        appdata.mkdir()
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(appdata))

        from rdo_lobby_manager.config import paths

        data = paths.user_data_dir()
        config = paths.user_config_dir()
        assert data == config


class TestConveniencePaths:
    """The convenience subpath helpers create their parents and resolve correctly."""

    def test_lobby_store_dir_creates_lobbies_subdir(self, isolated_data_dir: Path):
        from rdo_lobby_manager.config import paths

        result = paths.lobby_store_dir()
        assert result == isolated_data_dir / "data" / "lobbies"
        assert result.exists()

    def test_config_file_returns_json_path(self, isolated_data_dir: Path):
        from rdo_lobby_manager.config import paths

        result = paths.config_file()
        assert result == isolated_data_dir / "config" / "config.json"
        # Note: does not create the file, just the path

    def test_crypto_key_file_path(self, isolated_data_dir: Path):
        from rdo_lobby_manager.config import paths

        result = paths.crypto_key_file()
        assert result == isolated_data_dir / "data" / ".lobby_key"

    def test_log_file_creates_parent_dir(self, isolated_data_dir: Path):
        from rdo_lobby_manager.config import paths

        result = paths.log_file()
        # log_file goes to cache/logs/test.log
        assert "test.log" in str(result)
        assert result.parent.exists()

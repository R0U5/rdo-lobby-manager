"""Tests for app.py — the application controller."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from rdo_lobby_manager.app import AppController, AppSettings, NoRDR2InstallError
from rdo_lobby_manager.domain.lobby import Lobby


@pytest.fixture
def controller(isolated_data_dir: Path) -> AppController:
    """An AppController with isolated data dir."""
    return AppController()


class TestSettings:
    def test_defaults(self):
        s = AppSettings()
        assert s.rdr2_path == ""
        assert s.theme == "dark"
        assert s.window_width == 900
        assert s.window_height == 600

    def test_round_trip_json(self):
        original = AppSettings(rdr2_path="/games/rdr2", theme="light", window_width=1200)
        text = original.to_json()
        restored = AppSettings.from_json(text)
        assert restored.rdr2_path == "/games/rdr2"
        assert restored.theme == "light"
        assert restored.window_width == 1200

    def test_from_json_missing_fields_uses_defaults(self):
        s = AppSettings.from_json("{}")
        assert s.rdr2_path == ""
        assert s.theme == "dark"

    def test_from_json_invalid_raises(self):
        with pytest.raises(json.JSONDecodeError):
            AppSettings.from_json("not json")


class TestSettingsPersistence:
    def test_save_and_load(self, controller: AppController, isolated_data_dir: Path):
        controller.settings.rdr2_path = "/fake/path"
        controller.settings.theme = "light"
        controller.save_settings()

        # Reload
        controller2 = AppController()
        assert controller2.settings.rdr2_path == "/fake/path"
        assert controller2.settings.theme == "light"

    def test_load_missing_returns_defaults(self, isolated_data_dir: Path):
        controller = AppController()
        assert controller.settings.rdr2_path == ""


class TestLobbyCRUD:
    def test_create_lobby(self, controller: AppController):
        ok, msg = controller.create_lobby("TestLobby", "secret123")
        assert ok is True
        assert "created" in msg.lower()

    def test_create_duplicate_fails(self, controller: AppController):
        controller.create_lobby("X", "pass1")
        ok, msg = controller.create_lobby("X", "pass2")
        assert ok is False
        assert "already exists" in msg.lower()

    def test_create_invalid_name_fails(self, controller: AppController):
        ok, msg = controller.create_lobby("../bad", "pass")
        assert ok is False
        assert "invalid" in msg.lower() or "error" in msg.lower()

    def test_update_lobby(self, controller: AppController):
        controller.create_lobby("X", "old_pass")
        ok, msg = controller.update_lobby("X", "new_pass")
        assert ok is True
        lobby = controller.get_lobby("X")
        assert lobby.passphrase == "new_pass"

    def test_update_missing_fails(self, controller: AppController):
        ok, msg = controller.update_lobby("Ghost", "pass")
        assert ok is False
        assert "not found" in msg.lower()

    def test_delete_lobby(self, controller: AppController):
        controller.create_lobby("X", "p")
        ok, msg, trash = controller.delete_lobby("X")
        assert ok is True
        assert trash is not None
        assert not controller.lobby_store.exists("X")

    def test_delete_missing_fails(self, controller: AppController):
        ok, msg, trash = controller.delete_lobby("Ghost")
        assert ok is False
        assert trash is None

    def test_undelete(self, controller: AppController):
        controller.create_lobby("X", "p")
        ok, _, trash = controller.delete_lobby("X")
        ok2, msg2 = controller.undelete_lobby(trash)  # type: ignore[arg-type]
        assert ok2 is True
        assert controller.lobby_store.exists("X")

    def test_list_lobbies(self, controller: AppController):
        controller.create_lobby("B", "p")
        controller.create_lobby("A", "p")
        names = controller.list_lobby_names()
        assert names == ["A", "B"]


class TestRDR2Install:
    def test_not_configured_by_default(self, controller: AppController):
        assert controller.is_rdr2_configured is False

    def test_set_valid_path(self, controller: AppController, tmp_path: Path):
        # Create a fake RDR2 install
        install = tmp_path / "RDR2"
        install.mkdir()
        (install / "RDR2.exe").write_text("x")
        (install / "x64").mkdir()

        ok, msg = controller.set_rdr2_path(str(install))
        assert ok is True
        assert controller.is_rdr2_configured is True

    def test_set_invalid_path(self, controller: AppController, tmp_path: Path):
        d = tmp_path / "empty"
        d.mkdir()
        ok, msg = controller.set_rdr2_path(str(d))
        assert ok is False
        assert "does not look" in msg.lower()

    def test_meta_store_raises_when_not_configured(self, controller: AppController):
        with pytest.raises(NoRDR2InstallError):
            _ = controller.meta_store


class TestMetaOperations:
    @pytest.fixture
    def configured_controller(self, controller: AppController, tmp_path: Path) -> AppController:
        """A controller with a fake RDR2 install + startup.meta."""
        install = tmp_path / "RDR2"
        install.mkdir()
        (install / "RDR2.exe").write_text("x")
        (install / "x64").mkdir()
        # Create the meta file
        meta_dir = install / "x64" / "data"
        meta_dir.mkdir(parents=True)
        meta_path = meta_dir / "startup.meta"
        meta_path.write_text("<Startup>\n</Startup>\n", encoding="utf-8")
        controller.set_rdr2_path(str(install))
        return controller

    def test_get_meta_state(self, configured_controller: AppController):
        meta = configured_controller.get_meta_state()
        assert meta is not None
        assert meta.has_private_lobby() is False

    def test_apply_lobby(self, configured_controller: AppController):
        # Mock process check so it doesn't block
        with patch("rdo_lobby_manager.app.assert_rdr2_not_running"):
            lobby = Lobby(name="Test", passphrase="mySecret")
            ok, msg = configured_controller.apply_lobby(lobby)
            assert ok is True
            assert "applied" in msg.lower()

            meta = configured_controller.get_meta_state()
            assert meta is not None
            assert meta.has_private_lobby() is True
            assert meta.passphrase == "mySecret"

    def test_apply_lobby_blocked_by_running_game(self, configured_controller: AppController):
        from rdo_lobby_manager.util.process_check import RDR2RunningError

        with patch(
            "rdo_lobby_manager.app.assert_rdr2_not_running",
            side_effect=RDR2RunningError("game is running"),
        ):
            lobby = Lobby(name="Test", passphrase="mySecret")
            ok, msg = configured_controller.apply_lobby(lobby)
            assert ok is False
            assert "running" in msg.lower()

    def test_go_public(self, configured_controller: AppController):
        with patch("rdo_lobby_manager.app.assert_rdr2_not_running"):
            lobby = Lobby(name="Test", passphrase="mySecret")
            configured_controller.apply_lobby(lobby)
            assert configured_controller.get_meta_state().has_private_lobby()

            ok, msg = configured_controller.go_public()
            assert ok is True
            assert "restored" in msg.lower() or "public" in msg.lower()

            meta = configured_controller.get_meta_state()
            assert not meta.has_private_lobby()

    def test_go_public_without_snapshot(self, configured_controller: AppController):
        with patch("rdo_lobby_manager.app.assert_rdr2_not_running"):
            ok, msg = configured_controller.go_public()
            assert ok is False
            assert "no default snapshot" in msg.lower()

    def test_apply_captures_snapshot_on_first_use(self, configured_controller: AppController):
        with patch("rdo_lobby_manager.app.assert_rdr2_not_running"):
            assert not configured_controller.has_default_snapshot()
            lobby = Lobby(name="Test", passphrase="mySecret")
            configured_controller.apply_lobby(lobby)
            assert configured_controller.has_default_snapshot()


class TestGetStatus:
    def test_status_no_rdr2(self, controller: AppController):
        status = controller.get_status()
        assert status["rdr2_configured"] is False
        assert status["lobby_count"] == 0
        assert status["meta_has_lobby"] is False

    def test_status_with_lobbies(self, controller: AppController):
        controller.create_lobby("A", "p")
        controller.create_lobby("B", "p")
        status = controller.get_status()
        assert status["lobby_count"] == 2

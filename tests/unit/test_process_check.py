"""Tests for util/process_check.py — detect running RDR2 process (B15)."""

from __future__ import annotations

import pytest

from rdo_lobby_manager.util.process_check import (
    _RDR2_PROCESS_NAMES,
    RDR2RunningError,
    _matches_rdr2,
    assert_rdr2_not_running,
    is_rdr2_running,
)


class TestMatchesRDR2:
    @pytest.mark.parametrize("name", sorted(_RDR2_PROCESS_NAMES))
    def test_known_process_names_match(self, name: str):
        assert _matches_rdr2(name) is True

    def test_case_insensitive(self):
        assert _matches_rdr2("RDR2.EXE") is True
        assert _matches_rdr2("rdr2.exe") is True
        assert _matches_rdr2("Rdr2.Exe") is True

    def test_unrelated_process(self):
        assert _matches_rdr2("chrome.exe") is False
        assert _matches_rdr2("discord.exe") is False
        assert _matches_rdr2("python3") is False


class TestIsRDR2Running:
    def test_returns_true_when_rdr2_in_process_list(self, monkeypatch):
        """When RDR2 is in the process list, return True."""
        monkeypatch.setattr(
            "rdo_lobby_manager.util.process_check._get_process_names",
            lambda: ["chrome.exe", "rdr2.exe", "discord.exe"],
        )
        assert is_rdr2_running() is True

    def test_returns_false_when_rdr2_not_running(self, monkeypatch):
        monkeypatch.setattr(
            "rdo_lobby_manager.util.process_check._get_process_names",
            lambda: ["chrome.exe", "discord.exe", "explorer.exe"],
        )
        assert is_rdr2_running() is False

    def test_returns_true_when_process_list_empty(self, monkeypatch):
        """Cautious: if we can't determine processes, assume running."""
        monkeypatch.setattr(
            "rdo_lobby_manager.util.process_check._get_process_names",
            lambda: [],
        )
        assert is_rdr2_running() is True

    def test_detects_rockstar_launcher(self, monkeypatch):
        monkeypatch.setattr(
            "rdo_lobby_manager.util.process_check._get_process_names",
            lambda: ["rockstarstarlauncher.exe"],
        )
        assert is_rdr2_running() is True

    def test_detects_linux_proton_process(self, monkeypatch):
        monkeypatch.setattr(
            "rdo_lobby_manager.util.process_check._get_process_names",
            lambda: ["wineserver", "rdr2", "plasma-desktop"],
        )
        assert is_rdr2_running() is True

    def test_does_not_match_substring(self, monkeypatch):
        """A process named 'rdr2_helper.exe' should NOT match."""
        monkeypatch.setattr(
            "rdo_lobby_manager.util.process_check._get_process_names",
            lambda: ["rdr2_helper.exe"],
        )
        assert is_rdr2_running() is False


class TestAssertNotRunning:
    def test_raises_when_running(self, monkeypatch):
        monkeypatch.setattr(
            "rdo_lobby_manager.util.process_check._get_process_names",
            lambda: ["rdr2.exe"],
        )
        with pytest.raises(RDR2RunningError, match="appears to be running"):
            assert_rdr2_not_running()

    def test_does_not_raise_when_not_running(self, monkeypatch):
        monkeypatch.setattr(
            "rdo_lobby_manager.util.process_check._get_process_names",
            lambda: ["chrome.exe"],
        )
        # Should not raise
        assert_rdr2_not_running()

    def test_raises_when_process_list_empty(self, monkeypatch):
        """Cautious: unknown process state → raise (don't write)."""
        monkeypatch.setattr(
            "rdo_lobby_manager.util.process_check._get_process_names",
            lambda: [],
        )
        with pytest.raises(RDR2RunningError):
            assert_rdr2_not_running()

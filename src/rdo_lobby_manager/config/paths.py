"""Resolve platform-appropriate filesystem paths for app data.

Replaces the original Qt6 tool's habit of putting everything next to the .exe.
v2 uses the standard per-user data directory so config doesn't get clobbered
on reinstall and survives being run from a read-only location (e.g. a USB
drive or a network share).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "RDOLobbyManager"
APP_AUTHOR = "R0U5"


def _xdg(env_var: str, fallback: Path) -> Path:
    """Return $XDG_*_HOME if set, else the fallback."""
    value = os.environ.get(env_var)
    return Path(value).expanduser() if value else fallback


def user_data_dir() -> Path:
    """Return the per-user data directory; create it if missing.

    Windows: %APPDATA%\\\\RDOLobbyManager
    macOS:   ~/Library/Application Support/RDOLobbyManager
    Linux:   $XDG_DATA_HOME or ~/.local/share/RDOLobbyManager
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share")

    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_config_dir() -> Path:
    """Return the per-user config directory; create it if missing.

    On Windows we use the same dir as data; on Linux/macOS we honour
    XDG_CONFIG_HOME so config and data can be split if the user wants.
    """
    if sys.platform == "win32":
        return user_data_dir()

    base = _xdg("XDG_CONFIG_HOME", Path.home() / ".config")
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_cache_dir() -> Path:
    """Return the per-user cache directory; create it if missing.

    Used for thumbnails, downloaded assets, etc. Safe to delete by the user.
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = _xdg("XDG_CACHE_HOME", Path.home() / ".cache")

    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_log_dir() -> Path:
    """Return the per-user log directory; create it if missing.

    Logs go under cache on Linux/macOS (transient) but under data on Windows
    (so users can find them for support).
    """
    if sys.platform == "win32":
        return user_data_dir() / "logs"
    return user_cache_dir() / "logs"


# --- Convenience subpaths ---


def lobby_store_dir() -> Path:
    """Directory holding .lobby files (one per saved configuration)."""
    path = user_data_dir() / "lobbies"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    """Path to the main app config file (app settings, not lobby data)."""
    return user_config_dir() / "config.json"


def crypto_key_file() -> Path:
    """Path to the Fernet key used to encrypt lobby passphrases at rest.

    Generated on first run with safe random. Stays in user_data_dir so
    the key never leaves the machine.
    """
    return user_data_dir() / ".lobby_key"


def log_file() -> Path:
    """Path to the rolling log file."""
    path = user_log_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path / "rdo_lobby_manager.log"

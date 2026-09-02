"""Application controller — the glue between domain, storage, and UI.

The UI layer talks to this controller, never directly to storage or
crypto. This keeps the UI thin (no business logic in widgets) and makes
the controller testable without a GUI.

Responsibilities:
- Load/save app settings (RDR2 path, theme, window geometry)
- Coordinate lobby CRUD, meta-file apply/restore, and process checks
- Emit high-level results the UI can render (no Qt/CTk types here)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from rdo_lobby_manager.config.paths import (
    config_file,
)
from rdo_lobby_manager.domain.install_detect import (
    best_guess_install,
    find_all_candidates,
    validate_user_path,
)
from rdo_lobby_manager.domain.lobby import Lobby, LobbyError
from rdo_lobby_manager.domain.meta_file import MetaFile, MetaFileNotFoundError, MetaFileStore
from rdo_lobby_manager.storage.errors import (
    LobbyAlreadyExistsError,
    LobbyNotFoundError,
)
from rdo_lobby_manager.storage.lobby_store import LobbyStore
from rdo_lobby_manager.util.atomic_write import atomic_write_text
from rdo_lobby_manager.util.backup import BackupStore
from rdo_lobby_manager.util.log import get_logger
from rdo_lobby_manager.util.process_check import RDR2RunningError, assert_rdr2_not_running

_LOG = get_logger(__name__)

# The meta file lives at <RDR2_install>/x64/data/startup.meta
_META_SUBPATH = "x64/data/startup.meta"
# Backups live in the app's data dir, not in the game install
_BACKUP_DIR_NAME = "meta_backups"


# --- Exceptions ---


class AppError(Exception):
    """Base class for controller-level errors."""


class NoRDR2InstallError(AppError):
    """No RDR2 install path is configured."""


class MetaFileMissingError(AppError):
    """The meta file doesn't exist at the expected path."""


# --- Settings ---


@dataclass
class AppSettings:
    """Persisted application settings."""

    rdr2_path: str = ""
    theme: str = "dark"
    window_width: int = 900
    window_height: int = 600
    last_selected_lobby: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {
                "rdr2_path": self.rdr2_path,
                "theme": self.theme,
                "window_width": self.window_width,
                "window_height": self.window_height,
                "last_selected_lobby": self.last_selected_lobby,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> AppSettings:
        data = json.loads(text)
        return cls(
            rdr2_path=data.get("rdr2_path", ""),
            theme=data.get("theme", "dark"),
            window_width=data.get("window_width", 900),
            window_height=data.get("window_height", 600),
            last_selected_lobby=data.get("last_selected_lobby", ""),
        )


# --- The controller ---


class AppController:
    """High-level API for the UI layer.

    All methods return plain Python types (dataclasses, lists, bools, strs).
    No GUI types. The UI layer wraps these in CTk widgets.
    """

    def __init__(self) -> None:
        self.settings: AppSettings = self._load_settings()
        self._lobby_store: LobbyStore | None = None
        self._meta_store: MetaFileStore | None = None
        self._backup_store: BackupStore | None = None

    # --- Settings ---

    def _load_settings(self) -> AppSettings:
        path = config_file()
        if not path.exists():
            return AppSettings()
        try:
            return AppSettings.from_json(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _LOG.warning("Could not load settings from %s: %s", path, exc)
            return AppSettings()

    def save_settings(self) -> None:
        path = config_file()
        atomic_write_text(path, self.settings.to_json() + "\n")
        _LOG.debug("Saved settings to %s", path)

    # --- Lazy stores ---

    @property
    def lobby_store(self) -> LobbyStore:
        if self._lobby_store is None:
            self._lobby_store = LobbyStore()
        return self._lobby_store

    @property
    def meta_store(self) -> MetaFileStore:
        if self._meta_store is None:
            if not self.settings.rdr2_path:
                raise NoRDR2InstallError("No RDR2 install path configured")
            meta_path = Path(self.settings.rdr2_path) / _META_SUBPATH
            snapshot_path = Path(self.settings.rdr2_path) / _META_SUBPATH / ".original"
            # Actually snapshot should be in app data dir, not game dir
            from rdo_lobby_manager.config.paths import user_data_dir  # noqa: PLC0415

            snapshot_path = user_data_dir() / "startup.meta.snapshot"
            self._meta_store = MetaFileStore(meta_path, snapshot_path)
        return self._meta_store

    @property
    def backup_store(self) -> BackupStore:
        if self._backup_store is None:
            from rdo_lobby_manager.config.paths import user_data_dir  # noqa: PLC0415

            self._backup_store = BackupStore(user_data_dir() / _BACKUP_DIR_NAME)
        return self._backup_store

    # --- RDR2 install ---

    def detect_installs(self) -> list:
        """Return all detected RDR2 install candidates."""
        return find_all_candidates()

    def set_rdr2_path(self, path: str) -> tuple[bool, str]:
        """Set the RDR2 install path. Validates it first.

        Returns (success, message).
        """
        candidate = validate_user_path(Path(path))
        if not candidate.is_valid:
            return False, candidate.notes or "Directory does not look like an RDR2 install"
        self.settings.rdr2_path = str(candidate.path)
        self._meta_store = None  # force re-init with new path
        self.save_settings()
        return True, f"RDR2 directory set to {candidate.path}"

    def auto_detect_path(self) -> str | None:
        """Try to auto-detect the RDR2 install path."""
        path = best_guess_install()
        if path:
            self.settings.rdr2_path = str(path)
            self._meta_store = None
            self.save_settings()
            return str(path)
        return None

    @property
    def is_rdr2_configured(self) -> bool:
        return bool(self.settings.rdr2_path)

    # --- Lobby CRUD ---

    def list_lobbies(self) -> list[Lobby]:
        """Return all saved lobbies."""
        return self.lobby_store.list()

    def list_lobby_names(self) -> list[str]:
        return self.lobby_store.list_names()

    def get_lobby(self, name: str) -> Lobby:
        return self.lobby_store.get(name)

    def create_lobby(self, name: str, passphrase: str, notes: str = "") -> tuple[bool, str]:
        """Create a new lobby. Returns (success, message)."""
        try:
            lobby = Lobby(name=name, passphrase=passphrase, notes=notes)
        except LobbyError as exc:
            return False, str(exc)
        try:
            self.lobby_store.add(lobby)
        except LobbyAlreadyExistsError:
            return False, f"A lobby named {name!r} already exists. Use Update instead."
        _LOG.info("Created lobby %r", name)
        return True, f"Lobby {name!r} created."

    def update_lobby(self, name: str, passphrase: str, notes: str = "") -> tuple[bool, str]:
        """Update an existing lobby. Returns (success, message)."""
        try:
            existing = self.lobby_store.get(name)
            updated = existing.with_changes(passphrase=passphrase, notes=notes)
            self.lobby_store.update(updated)
        except LobbyNotFoundError:
            return False, f"Lobby {name!r} not found."
        except LobbyError as exc:
            return False, str(exc)
        _LOG.info("Updated lobby %r", name)
        return True, f"Lobby {name!r} updated."

    def delete_lobby(self, name: str) -> tuple[bool, str, Path | None]:
        """Delete a lobby. Returns (success, message, trash_path_for_undo)."""
        if not self.lobby_store.exists(name):
            return False, f"Lobby {name!r} not found.", None
        trash_path = self.lobby_store.delete(name)
        self.settings.last_selected_lobby = ""
        self.save_settings()
        _LOG.info("Deleted lobby %r", name)
        return True, f"Lobby {name!r} deleted.", trash_path

    def undelete_lobby(self, trash_path: Path) -> tuple[bool, str]:
        """Restore a previously-deleted lobby."""
        try:
            self.lobby_store.undelete(trash_path)
        except LobbyNotFoundError as exc:
            return False, str(exc)
        return True, "Lobby restored."

    # --- Meta file operations ---

    def get_meta_state(self) -> MetaFile | None:
        """Return the current meta file state, or None if not configured."""
        if not self.is_rdr2_configured:
            return None
        try:
            return self.meta_store.current()
        except MetaFileNotFoundError:
            return None

    def is_meta_default(self) -> bool:
        """True if the meta file matches the stored default snapshot."""
        if not self.is_rdr2_configured:
            return False
        return self.meta_store.is_default()

    def has_default_snapshot(self) -> bool:
        return self.meta_store.has_default_snapshot() if self.is_rdr2_configured else False

    def apply_lobby(self, lobby: Lobby) -> tuple[bool, str]:
        """Apply a lobby configuration to the meta file.

        Checks that RDR2 is not running before writing.
        """
        if not self.is_rdr2_configured:
            return False, "No RDR2 directory set. Use File > Set RDR2 Directory."

        try:
            assert_rdr2_not_running()
        except RDR2RunningError as exc:
            return False, str(exc)

        # Back up the current meta file before modifying
        try:
            meta_path = self.meta_store.meta_path
            if meta_path.exists():
                self.backup_store.create(meta_path, base_name="startup.meta")
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("Could not create backup before apply: %s", exc)

        try:
            self.meta_store.apply_lobby(lobby.passphrase, lines=2)
        except MetaFileNotFoundError:
            return False, "Meta file not found. Has the game been installed correctly?"
        except Exception as exc:  # noqa: BLE001
            return False, f"Could not write to meta file: {exc}"

        self.settings.last_selected_lobby = lobby.name
        self.save_settings()
        return True, f"Lobby {lobby.name!r} applied. Start RDR2 to use it."

    def go_public(self) -> tuple[bool, str]:
        """Restore the meta file to its default (public) state.

        This is the "Go Public" menu action.
        """
        if not self.is_rdr2_configured:
            return False, "No RDR2 directory set."

        try:
            assert_rdr2_not_running()
        except RDR2RunningError as exc:
            return False, str(exc)

        if not self.meta_store.has_default_snapshot():
            return False, "No default snapshot available. Nothing to restore."

        try:
            self.meta_store.restore_default()
        except Exception as exc:  # noqa: BLE001
            return False, f"Could not restore default: {exc}"

        self.settings.last_selected_lobby = ""
        self.save_settings()
        return True, "Restored to public (default) lobby."

    def clear_backup(self) -> tuple[bool, str]:
        """Clear the stored default snapshot."""
        if not self.is_rdr2_configured:
            return False, "No RDR2 directory set."
        self.meta_store.clear_snapshot()
        return True, "Backup snapshot cleared."

    # --- Status ---

    def get_status(self) -> dict:
        """Return a status dict for the UI to render."""
        meta = self.get_meta_state()
        return {
            "rdr2_configured": self.is_rdr2_configured,
            "rdr2_path": self.settings.rdr2_path,
            "lobby_count": len(self.list_lobby_names()),
            "meta_has_lobby": meta.has_private_lobby() if meta else False,
            "meta_is_default": self.is_meta_default() if meta else False,
            "meta_passphrase": meta.passphrase if meta else None,
            "has_snapshot": self.has_default_snapshot() if self.is_rdr2_configured else False,
        }

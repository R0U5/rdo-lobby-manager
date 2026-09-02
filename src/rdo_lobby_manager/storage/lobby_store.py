"""Encrypted lobby storage.

Lobbies are persisted as one file per lobby in the user's lobby store
directory. Each file is JSON, with the passphrase field stored as a Fernet
token (never plaintext — fixes B6).

File format (v2):
    {
        "schema_version": 2,
        "name": "MyLobby",
        "passphrase_encrypted": "gAAAAA...",
        "created_at": "2026-09-02T10:34:22.123456+00:00",
        "modified_at": "2026-09-02T10:34:22.123456+00:00",
        "notes": "freeform text"
    }

The v1 plaintext format from the original Qt6 tool is detected and migrated
on first read (see migrations.py).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from rdo_lobby_manager.config import crypto
from rdo_lobby_manager.config.paths import lobby_store_dir
from rdo_lobby_manager.domain.lobby import (
    SCHEMA_VERSION,
    Lobby,
    LobbyError,
)
from rdo_lobby_manager.storage.errors import (
    LobbyAlreadyExistsError,
    LobbyNotFoundError,
    LobbyStoreCorruptError,
)
from rdo_lobby_manager.storage.migrations import migrate_v1_file
from rdo_lobby_manager.util.atomic_write import atomic_write_text
from rdo_lobby_manager.util.log import get_logger

_LOG = get_logger(__name__)


# --- Exceptions ---
# Defined in errors.py to avoid circular import with migrations.py.


# --- Filename safety ---


def lobby_path(name: str) -> Path:
    """Return the absolute path to a lobby file given its name.

    Uses Lobby.to_filename() to ensure the path component is safe.
    Raises LobbyError if the name is invalid (e.g. contains path separators).
    """
    # Construct a temporary Lobby to get the validated filename. We never
    # store this object, so the passphrase is irrelevant.
    tmp = Lobby(name=name, passphrase=".")  # noqa: S106  -- placeholder, not a secret
    return lobby_store_dir() / tmp.to_filename()


# --- The store ---


class LobbyStore:
    """CRUD over the user's encrypted lobby files.

    A LobbyStore is bound to a single directory. The default directory is
    resolved from `paths.lobby_store_dir()` at construction time, so tests
    using `isolated_data_dir` get an isolated store automatically.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root: Path = root or lobby_store_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    # --- Read ---

    def list_names(self) -> list[str]:
        """Return the names of all lobbies in the store, sorted alphabetically."""
        return sorted(self._iter_names())

    def _iter_names(self) -> Iterator[str]:
        """Yield every lobby name in the store, silently skipping non-.lobby files."""
        for path in self.root.iterdir():
            if not path.is_file():
                continue
            if path.suffix != ".lobby":
                continue
            # Derive the name from the filename, not from the file content.
            # This way we don't need to decrypt to list.
            yield path.stem

    def list(self) -> list[Lobby]:
        """Return all lobbies, fully decoded (incl. decrypted passphrases)."""
        out: list[Lobby] = []
        for path in sorted(self.root.iterdir()):
            if not path.is_file() or path.suffix != ".lobby":
                continue
            try:
                out.append(self._read_one(path))
            except LobbyStoreCorruptError as exc:
                _LOG.warning("Skipping corrupt lobby file %s: %s", path, exc)
        return out

    def get(self, name: str) -> Lobby:
        """Return a single lobby by name. Raises LobbyNotFoundError if missing."""
        path = self._path_for(name)
        if not path.exists():
            raise LobbyNotFoundError(f"No lobby named {name!r}")
        return self._read_one(path)

    def exists(self, name: str) -> bool:
        """True iff a lobby with this name is in the store."""
        return self._path_for(name).exists()

    def _path_for(self, name: str) -> Path:
        """Resolve a lobby name to a path. Validates the name first."""
        return lobby_path(name) if name else lobby_store_dir()  # noqa: FURB181

    def _read_one(self, path: Path) -> Lobby:
        """Read and decode one .lobby file. Handles v1 and v2 formats."""
        try:
            raw = path.read_bytes()
        except OSError as exc:
            msg = f"Cannot read {path}: {exc}"
            raise LobbyStoreCorruptError(msg) from exc

        # Empty file → treat as corrupt
        if not raw.strip():
            raise LobbyStoreCorruptError(f"{path} is empty")

        # Try JSON first (v2). If that fails, try v1 plaintext migration.
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            lobby = migrate_v1_file(path, raw)
            # Migration succeeded; we got a v2 Lobby. Optionally rewrite
            # the file in v2 format so next time we skip the migration.
            # We do this lazily — only if the migration path returned the
            # same name (always true). Errors here are non-fatal.
            try:
                self._write_one(lobby)
            except OSError as exc:
                _LOG.warning("Could not rewrite migrated lobby in v2 format: %s", exc)
            return lobby

        return self._decode_v2(data, path)

    def _decode_v2(self, data: object, path: Path) -> Lobby:
        """Decode a v2-format JSON document into a Lobby."""
        if not isinstance(data, dict):
            raise LobbyStoreCorruptError(f"{path}: expected object, got {type(data)}")
        try:
            name = str(data["name"])
            ct = str(data["passphrase_encrypted"])
            created_at = datetime.fromisoformat(str(data["created_at"]))
            modified_at = datetime.fromisoformat(str(data["modified_at"]))
            notes = str(data.get("notes", ""))
        except (KeyError, ValueError, TypeError) as exc:
            raise LobbyStoreCorruptError(f"{path}: missing or invalid field: {exc}") from exc

        try:
            plaintext = crypto.decrypt(ct)
        except crypto.DecryptionError as exc:
            raise LobbyStoreCorruptError(
                f"{path}: cannot decrypt passphrase (key may have changed): {exc}"
            ) from exc

        # Constructing a Lobby re-runs validation. If a stored lobby has bad
        # data we treat that as corruption rather than a validation error
        # to make the recovery path explicit.
        try:
            return Lobby(
                name=name,
                passphrase=plaintext,
                created_at=created_at,
                modified_at=modified_at,
                notes=notes,
            )
        except LobbyError as exc:
            raise LobbyStoreCorruptError(f"{path}: stored lobby is invalid: {exc}") from exc

    # --- Write ---

    def add(self, lobby: Lobby) -> None:
        """Add a new lobby. Raises LobbyAlreadyExistsError if `name` is taken."""
        path = self._path_for(lobby.name)
        if path.exists():
            raise LobbyAlreadyExistsError(lobby.name, path)
        self._write_one(lobby)

    def update(self, lobby: Lobby) -> None:
        """Update an existing lobby. Raises LobbyNotFoundError if missing.

        Note: if `lobby.name` was changed via `with_changes(name=...)`, this
        writes to the new name. The old file is *not* automatically removed
        because we want explicit control over renames. Use `rename` for that.
        """
        path = self._path_for(lobby.name)
        if not path.exists():
            raise LobbyNotFoundError(f"No lobby named {lobby.name!r}")
        self._write_one(lobby)

    def add_or_update(self, lobby: Lobby) -> bool:
        """Add if missing, update if present. Returns True if updated, False if added."""
        if self.exists(lobby.name):
            self.update(lobby)
            return True
        self.add(lobby)
        return False

    def delete(self, name: str) -> Path | None:
        """Delete a lobby by name. No-op if it doesn't exist (unlike get).

        Returns the trash path of the moved file (so undelete() can find it),
        or None if the lobby didn't exist. This is B19-mitigated: callers
        (UI) should put it behind a confirm dialog and offer undo via the
        returned path.
        """
        path = self._path_for(name)
        if not path.exists():
            return None
        trash = self.root / ".trash"
        trash.mkdir(exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        dest = trash / f"{path.stem}.{timestamp}.lobby"
        shutil.move(str(path), str(dest))
        _LOG.info("Deleted lobby %r (moved to %s)", name, dest)
        return dest

    def undelete(self, path: Path) -> None:
        """Restore a previously-deleted lobby from the trash.

        `path` is the value returned by `delete()`. The trash filename is
        `<original_name>.<timestamp>.lobby`, so we strip the timestamp segment
        to recover the original name. If the slot is now occupied (the user
        created a new lobby with the same name while the old was in trash),
        the restored file gets a `-restored` suffix.
        """
        if not path.exists():
            raise LobbyNotFoundError(f"Trash file {path} no longer exists")
        # Trash filename: "MyLobby.20260902T181336.lobby" -> stem = "MyLobby.20260902T181336"
        # Split on "." to recover the original name (first segment).
        original_name = path.stem.split(".", 1)[0]
        dest = self._path_for(original_name)
        if dest.exists():
            i = 1
            while True:
                candidate = self.root / f"{original_name}-restored{i}.lobby"
                if not candidate.exists():
                    dest = candidate
                    break
                i += 1
        shutil.move(str(path), str(dest))
        _LOG.info("Restored lobby from trash to %s", dest)

    def rename(self, old_name: str, new_lobby: Lobby) -> None:
        """Rename `old_name` to `new_lobby.name`. Both files are involved.

        Use this when the user wants to change a lobby's name. We write the
        new file (with updated content) and delete the old.
        """
        old_path = self._path_for(old_name)
        if not old_path.exists():
            raise LobbyNotFoundError(f"No lobby named {old_name!r}")
        if self.exists(new_lobby.name) and new_lobby.name != old_name:
            raise LobbyAlreadyExistsError(new_lobby.name, self._path_for(new_lobby.name))
        # Write the new file, then remove the old. Order matters: write
        # first, so a crash between the two operations leaves us with the
        # new lobby intact (the old becomes a redundant copy we can clean
        # up later).
        self._write_one(new_lobby)
        if new_lobby.name != old_name:
            old_path.unlink()
            _LOG.info("Renamed lobby %r -> %r", old_name, new_lobby.name)

    # --- Internal ---

    def _write_one(self, lobby: Lobby) -> None:
        """Serialize and write one lobby atomically."""
        path = self._path_for(lobby.name)
        # Validate the name can be safely turned into a path.
        # (Lobby already validated it, but re-check defensively.)
        if "/" in lobby.name or "\\" in lobby.name or "\x00" in lobby.name:
            raise LobbyError(f"Unsafe lobby name for storage: {lobby.name!r}")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "name": lobby.name,
            "passphrase_encrypted": crypto.encrypt(lobby.passphrase),
            "created_at": lobby.created_at.isoformat(),
            "modified_at": lobby.modified_at.isoformat(),
            "notes": lobby.notes,
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        atomic_write_text(path, text + "\n", encoding="utf-8", newline="\n")
        _LOG.debug("Wrote lobby %r to %s", lobby.name, path)

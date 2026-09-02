"""Non-overwriting backup helpers.

Fixes B14: the original Qt6 tool's "Set RDR2 Directory" flow called
`QFile::copy` to write `startup.meta.original` without checking whether
that file already existed. The second time a user pointed the app at an
install, the first backup was destroyed silently. The only way to recover
the original game state was then to use the *second* backup, which was
already a modded state.

The fix: backups are never overwritten. Each backup is a timestamped file
under a `.backups/` directory adjacent to the target. The most recent
backup is the "active" one (returned by `latest_backup()`), but all older
backups are retained until the user explicitly purges them.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rdo_lobby_manager.util.atomic_write import atomic_write_bytes
from rdo_lobby_manager.util.log import get_logger

_LOG = get_logger(__name__)

# Maximum number of historical backups to retain. Older ones are pruned
# (oldest-first) when a new backup is created. Set to a small number so we
# don't fill the user's disk over years of use.
MAX_BACKUPS = 10

# Filename: <basename>.backup.<YYYYMMDDTHHMMSSZ>.bin
# Collisions get a -N counter: <basename>.backup.<TS>-N.bin
# .bin extension so the file isn't mistaken for a .lobby by the store layer.
_BACKUP_FILENAME_RE = re.compile(
    r"^(?P<base>.+)\.backup\.(?P<ts>\d{8}T\d{6}Z)(?:-(?P<counter>\d+))?\.bin$"
)


# --- Exceptions ---


class BackupError(Exception):
    """Base class for backup failures."""


class BackupNotFoundError(BackupError):
    """No backup exists for the requested target."""


# --- Data types ---


@dataclass(frozen=True, slots=True)
class BackupInfo:
    """Metadata about a single backup file."""

    path: Path
    base_name: str
    created_at: datetime
    size_bytes: int

    @property
    def display_name(self) -> str:
        """Human-readable label for the UI."""
        return f"{self.base_name} @ {self.created_at.isoformat(timespec='seconds')}"


# --- The backup directory manager ---


class BackupStore:
    """Manages a directory of timestamped backup files.

    Each `create()` call writes a new file with a UTC timestamp in the
    filename. Older backups are pruned to MAX_BACKUPS. The active/latest
    backup is the most recent one.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, source: Path, base_name: str | None = None) -> BackupInfo:
        """Copy `source` into the backup directory under a new timestamped name.

        Args:
            source: the file to back up. Must exist and be a file.
            base_name: the human-readable name to embed in the backup
                filename. Defaults to source.name (with `.bin` extension
                stripped if present).

        Returns:
            BackupInfo for the new backup file.

        Raises:
            BackupError: if source doesn't exist or isn't readable.
            OSError: on filesystem failure.
        """
        if not source.exists():
            msg = f"Source file does not exist: {source}"
            raise BackupError(msg)
        if not source.is_file():
            msg = f"Source is not a regular file: {source}"
            raise BackupError(msg)

        if base_name is None:
            # Default: use the full source filename as the base name.
            # This preserves distinguishing extensions (e.g. "startup.meta"
            # vs "startup.txt" stay separate in the backup directory).
            base_name = source.name

        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        dest = self.root / f"{base_name}.backup.{ts}.bin"
        if dest.exists():
            # Should be impossible with a microsecond timestamp, but
            # guard anyway: append a counter.
            counter = 1
            while True:
                candidate = self.root / f"{base_name}.backup.{ts}-{counter}.bin"
                if not candidate.exists():
                    dest = candidate
                    break
                counter += 1

        # Read source, atomic-write dest. Using atomic_write means the
        # backup is never half-written (B11 again).
        try:
            data = source.read_bytes()
        except OSError as exc:
            msg = f"Cannot read source {source}: {exc}"
            raise BackupError(msg) from exc
        atomic_write_bytes(dest, data)
        _LOG.info("Created backup %s (%d bytes)", dest, len(data))

        # Prune older backups so we don't accumulate forever.
        self._prune(base_name)

        return BackupInfo(
            path=dest,
            base_name=base_name,
            created_at=_parse_backup_timestamp(dest.name),
            size_bytes=len(data),
        )

    def latest(self, base_name: str) -> BackupInfo:
        """Return the most recent backup for `base_name`, or raise."""
        matches = self.list(base_name)
        if not matches:
            raise BackupNotFoundError(f"No backups for {base_name!r}")
        return matches[0]  # list() returns newest-first

    def list(self, base_name: str | None = None) -> list[BackupInfo]:
        """Return all backups, newest first. Optionally filter by base_name."""
        infos = [
            info for info in self._iter_all() if base_name is None or info.base_name == base_name
        ]
        infos.sort(key=lambda b: b.created_at, reverse=True)
        return infos

    def _iter_all(self) -> Iterator[BackupInfo]:
        """Yield BackupInfo for every file in the backup directory."""
        for path in self.root.iterdir():
            if not path.is_file():
                continue
            match = _BACKUP_FILENAME_RE.match(path.name)
            if not match:
                continue
            base = match.group("base")
            try:
                created = _parse_backup_timestamp(path.name)
            except ValueError:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            yield BackupInfo(path=path, base_name=base, created_at=created, size_bytes=size)

    def _prune(self, base_name: str) -> None:
        """Keep only the most recent MAX_BACKUPS for `base_name`."""
        all_for_name = self.list(base_name)
        # list() returns newest first; we want to keep the first MAX_BACKUPS.
        for old in all_for_name[MAX_BACKUPS:]:
            try:
                old.path.unlink()
                _LOG.info("Pruned old backup %s", old.path)
            except OSError as exc:
                _LOG.warning("Could not prune old backup %s: %s", old.path, exc)

    def restore(self, info: BackupInfo, dest: Path) -> None:
        """Restore the contents of `info` to `dest`.

        `dest`'s parent is created if needed. `dest` is overwritten
        atomically. The backup file itself is not modified.
        """
        if not info.path.exists():
            raise BackupNotFoundError(f"Backup file no longer exists: {info.path}")
        data = info.path.read_bytes()
        atomic_write_bytes(dest, data)
        _LOG.info("Restored %s from %s", dest, info.path)

    def purge_all(self, base_name: str | None = None) -> int:
        """Delete every backup (optionally filtered by base_name).

        Returns the number of files deleted.
        """
        count = 0
        for info in self._iter_all():
            if base_name is not None and info.base_name != base_name:
                continue
            try:
                info.path.unlink()
                count += 1
            except OSError as exc:
                _LOG.warning("Could not delete %s: %s", info.path, exc)
        return count


# --- Helpers ---


def _parse_backup_timestamp(filename: str) -> datetime:
    """Extract the ISO timestamp from a backup filename.

    Raises ValueError if the filename doesn't match the expected pattern.
    """
    match = _BACKUP_FILENAME_RE.match(filename)
    if not match:
        msg = f"Filename does not match backup pattern: {filename}"
        raise ValueError(msg)
    ts = match.group("ts")
    return datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)

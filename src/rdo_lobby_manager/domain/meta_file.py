"""RDR2 startup.meta file reader/writer with content-hash detection.

Fixes B16 and B17 from the decompilation:

  B16: The original Qt6 tool compared the meta file's content against a
       static byte array baked into the binary at compile time. If Rockstar
       patched the meta file in a game update, the comparison broke silently
       and "Go Public" could restore content that no longer matched the
       current game. We replace this with a content hash that's captured
       dynamically — on first use with a new install, we hash whatever
       pristine content is there and remember that as the baseline.

  B17: The original tool's QString::indexOf comparisons failed on Windows
       files written with CRLF line endings (QTextStream::readLine on Windows
       strips \\n but not \\r). We normalize line endings to \\n on read and
       write \\n on output. The game itself accepts either, since both
       the file format and RAGE engine's parser are LF-tolerant.

File format (inferred from the decompilation + a working install):

  <many lines, often XML-ish fragments for RAGE engine>
  <when a private lobby is configured, the tool appends or modifies lines>
  pass=<passphrase>
  lines=<n>
  <more content>

The exact prefix/structure beyond `pass=` and `lines=` is private to the
RAGE engine. We treat the meta file as opaque text we can read, hash, and
write back. The default state is whatever pristine content we see on first
inspection of a new install.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rdo_lobby_manager.util.atomic_write import atomic_write_text
from rdo_lobby_manager.util.log import get_logger

_LOG = get_logger(__name__)


# The two keys that the original tool's `pass=` / `lines=` style format uses.
# We treat these as known but we don't assume the file is *only* these keys —
# the meta file contains RAGE engine config that we must not destroy.
_KNOWN_KEYS = frozenset({"pass", "lines"})

# Match "key=value" lines, anchored at start of line, terminating at end.
# The original Qt6 tool used QString::indexOf, which finds the substring
# anywhere; we use line-anchored matching to be stricter and avoid false
# positives inside XML fragments.
_KV_RE = re.compile(r"^(pass|lines)=(.*)$", re.MULTILINE)


# --- Exceptions ---


class MetaFileError(Exception):
    """Base class for meta file errors."""


class MetaFileNotFoundError(MetaFileError):
    """The meta file doesn't exist at the expected path."""


class MetaFileUnreadableError(MetaFileError):
    """The meta file exists but couldn't be read or parsed."""


# --- Data types ---


@dataclass(frozen=True, slots=True)
class MetaFile:
    """An in-memory representation of the RDR2 startup.meta file.

    `content` is the normalized (LF-line-ending) file body.
    `sha256` is a fingerprint for "is this the default state?" comparisons.
    `key_values` is the subset of `key=value` lines we recognize.

    The class is frozen so we can use it as a dict key / set member, and so
    mutations require going through `MetaFileStore.write()` which records
    the change.
    """

    path: Path
    content: str
    sha256: str
    key_values: dict[str, str]
    modified_at: datetime

    @property
    def passphrase(self) -> str | None:
        """The `pass=` value if present, else None.

        Returning a string (not a str) because the meta file may not have
        one set — that's the "default" / "public" state.
        """
        return self.key_values.get("pass")

    @property
    def lines(self) -> int | None:
        """The `lines=` value if present, parsed as an integer."""
        raw = self.key_values.get("lines")
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            _LOG.warning("meta file at %s has non-integer lines=%r", self.path, raw)
            return None

    def has_private_lobby(self) -> bool:
        """True if the file contains a `pass=` line (private lobby configured)."""
        return "pass" in self.key_values


# --- Read ---


def _normalize_line_endings(text: str) -> str:
    """Convert CRLF and CR to LF. Fixes B17."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _compute_hash(content: str) -> str:
    """SHA-256 of the normalized content. Used to detect "default" state."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _parse_key_values(content: str) -> dict[str, str]:
    """Extract the recognized `key=value` lines from the meta file content.

    Only keys in `_KNOWN_KEYS` (currently `pass` and `lines`) are returned.
    We don't try to parse the rest of the RAGE engine content.
    """
    return dict(_KV_RE.findall(content))  # noqa: C416  -- the dict() form here is clearer


def read_meta_file(path: Path) -> MetaFile:
    """Read and parse a startup.meta file.

    Raises:
        MetaFileNotFoundError: if the file doesn't exist.
        MetaFileUnreadableError: if the file can't be read or isn't valid UTF-8.
    """
    if not path.exists():
        raise MetaFileNotFoundError(f"Meta file not found: {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise MetaFileUnreadableError(f"Cannot read meta file {path}: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MetaFileUnreadableError(f"Meta file {path} is not valid UTF-8: {exc}") from exc

    normalized = _normalize_line_endings(text)
    return MetaFile(
        path=path,
        content=normalized,
        sha256=_compute_hash(normalized),
        key_values=_parse_key_values(normalized),
        modified_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
    )


# --- The meta-file manager (stateful) ---


class MetaFileStore:
    """Stateful manager for the startup.meta file.

    Knows the file's "default" state (captured dynamically on first read of
    a fresh install) and can detect whether the current state is the default
    or has been modified by this app or another tool.

    Replaces the original Qt6 tool's broken static-blob comparison.
    """

    def __init__(self, meta_path: Path, default_snapshot_path: Path) -> None:
        self.meta_path = meta_path
        self.snapshot_path = default_snapshot_path

    @property
    def exists(self) -> bool:
        return self.meta_path.exists()

    def current(self) -> MetaFile:
        """Return the current state of the meta file."""
        return read_meta_file(self.meta_path)

    def has_default_snapshot(self) -> bool:
        """True iff we have a stored "default" baseline to compare against."""
        return self.snapshot_path.exists()

    def capture_default(self) -> MetaFile:
        """Snapshot the current meta file as the "default" state.

        Call this on first use of a new install (or when the user clicks
        "Set RDR2 Directory"). The snapshot is what we restore when they
        click "Go Public" or "Clear backup".
        """
        meta = self.current()
        atomic_write_text(self.snapshot_path, meta.content, encoding="utf-8")
        _LOG.info("Captured default meta snapshot at %s", self.snapshot_path)
        return meta

    def is_default(self) -> bool:
        """True iff the current meta content matches the stored default.

        If we have no snapshot yet, return False (treat as "modified/unknown"
        so the UI shows a warning instead of silently doing nothing).
        """
        if not self.has_default_snapshot():
            return False
        try:
            current_meta = self.current()
        except MetaFileNotFoundError:
            return False
        try:
            snapshot = read_meta_file(self.snapshot_path)
        except MetaFileUnreadableError:
            _LOG.warning("Default snapshot at %s is unreadable", self.snapshot_path)
            return False
        return current_meta.sha256 == snapshot.sha256

    def apply_lobby(self, passphrase: str, lines: int) -> MetaFile:
        """Write a private-lobby configuration into the meta file.

        Args:
            passphrase: the lobby password/code to inject
            lines: the number of meta-file lines the value occupies
                (preserved from the original tool's format; not used
                in our rewrite, but kept for compatibility)

        Returns the new MetaFile state.

        If the meta file doesn't have a snapshot yet, captures one first
        so "Go Public" can restore the pristine state.
        """
        if not self.meta_path.exists():
            raise MetaFileNotFoundError(f"Meta file not found: {self.meta_path}")

        if not self.has_default_snapshot():
            _LOG.info("No default snapshot — capturing one before first apply")
            self.capture_default()

        meta = self.current()

        # Replace existing pass= / lines= lines, or append if absent.
        # We use a fresh body that strips any existing private-lobby config
        # and re-appends the new values. Everything else in the file is
        # preserved verbatim.
        body = _strip_known_keys(meta.content)
        # Append the new private-lobby config. Order matches the original
        # tool's output (pass= first, then lines=).
        new_content = body.rstrip("\n") + f"\npass={passphrase}\nlines={lines}\n"

        atomic_write_text(self.meta_path, new_content, encoding="utf-8")
        _LOG.info("Applied lobby to %s (passphrase=***, lines=%d)", self.meta_path, lines)
        return read_meta_file(self.meta_path)

    def restore_default(self) -> MetaFile | None:
        """Restore the meta file to its stored default state.

        Returns the restored MetaFile, or None if there's no default snapshot.
        """
        if not self.has_default_snapshot():
            return None
        try:
            snapshot = read_meta_file(self.snapshot_path)
        except MetaFileUnreadableError as exc:
            raise MetaFileError(f"Cannot read snapshot {self.snapshot_path}: {exc}") from exc
        atomic_write_text(self.meta_path, snapshot.content, encoding="utf-8")
        _LOG.info("Restored default meta to %s", self.meta_path)
        return read_meta_file(self.meta_path)

    def clear_snapshot(self) -> None:
        """Delete the stored default snapshot. Used by "Clear backup" UI."""
        if self.snapshot_path.exists():
            self.snapshot_path.unlink()
            _LOG.info("Cleared default snapshot at %s", self.snapshot_path)


def _strip_known_keys(content: str) -> str:
    """Remove any existing `pass=` / `lines=` lines from the meta content.

    Preserves everything else (RAGE engine XML, asset declarations, etc.).
    """
    lines = content.split("\n")
    return "\n".join(line for line in lines if not _KV_RE.match(line))


# --- Convenience helpers ---


def iter_meta_file_lines(path: Path) -> Iterator[str]:
    """Yield each line of the meta file, normalized to LF endings."""
    meta = read_meta_file(path)
    yield from meta.content.split("\n")

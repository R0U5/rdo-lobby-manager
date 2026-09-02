"""Migrations from the original Qt6 tool's plaintext .lobby format to v2.

The original tool wrote files like:
    pass=mysecret
    lines=2

We parse that, construct a v2 Lobby, and return it. The caller (lobby_store)
optionally rewrites the file in v2 format so the migration only happens once.

If parsing fails (file is corrupt, or it's a v2 file with the wrong format),
we re-raise as LobbyStoreCorruptError so the caller can handle it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from rdo_lobby_manager.domain.lobby import (
    InvalidLobbyNameError,
    InvalidPassphraseError,
    Lobby,
    LobbyError,
)
from rdo_lobby_manager.storage.errors import LobbyStoreCorruptError

# Match "key=value" lines. The original tool used "pass=" and "lines=".
_KV_RE = re.compile(r"^([a-zA-Z_]+)=(.*)$", re.MULTILINE)


def parse_v1_text(text: str) -> dict[str, str]:
    """Extract key=value pairs from a v1 plaintext .lobby file.

    Args:
        text: the raw file content

    Returns:
        dict of key->value for every key=value line found.
        Strips trailing CR from CRLF line endings (fixes B17).

    Raises:
        LobbyStoreCorruptError: if no key=value lines are found.
    """
    # Normalize CRLF to LF for the regex, but keep the values intact.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    pairs = _KV_RE.findall(text)
    if not pairs:
        msg = "No key=value lines found"
        raise LobbyStoreCorruptError(msg)
    return dict(pairs)


def migrate_v1_file(path: Path, raw: bytes) -> Lobby:
    """Parse a v1 plaintext .lobby file into a v2 Lobby.

    Args:
        path: the file path (used for error messages)
        raw: the raw bytes of the file

    Returns:
        a Lobby constructed from the file's content.

    Raises:
        LobbyStoreCorruptError: if the file cannot be parsed.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = f"{path}: not valid UTF-8"
        raise LobbyStoreCorruptError(msg) from exc

    pairs = parse_v1_text(text)

    # The v1 format used "pass" (not "passphrase") and "lines".
    # The filename stem was the lobby name.
    name = path.stem
    passphrase = pairs.get("pass", "")

    # v1 didn't store created_at / modified_at / notes. We synthesize
    # reasonable defaults: now() for both timestamps, no notes.
    now = datetime.now(UTC)

    try:
        return Lobby(
            name=name,
            passphrase=passphrase,
            created_at=now,
            modified_at=now,
            notes="",
        )
    except InvalidLobbyNameError as exc:
        # The filename itself is invalid (e.g. "CON.lobby"). We surface
        # this as a corruption error rather than trying to rename.
        msg = f"{path}: invalid lobby name in v1 file: {exc}"
        raise LobbyStoreCorruptError(msg) from exc
    except InvalidPassphraseError as exc:
        msg = f"{path}: invalid passphrase in v1 file: {exc}"
        raise LobbyStoreCorruptError(msg) from exc
    except LobbyError as exc:
        # Catch-all for any other LobbyError subclass.
        msg = f"{path}: cannot construct Lobby from v1 file: {exc}"
        raise LobbyStoreCorruptError(msg) from exc

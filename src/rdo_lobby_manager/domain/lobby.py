"""Lobby — the core domain object.

A Lobby represents a saved private-lobby configuration that can be applied to
the RDR2 startup.meta file. It has a name (used as the filename), a passphrase
(stored encrypted at rest), and a metadata version.

This module's job is to enforce invariants that the original Qt6 tool left
unprotected, so a Lobby object is *always* safe to serialize, write to disk,
or pass to the meta-file writer without re-validation.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime

# --- Constants ---

# Name constraints. Tight enough to be safe on every supported FS, loose
# enough to allow normal Latin/Cyrillic/CJK names.
NAME_MIN_LEN = 1
NAME_MAX_LEN = 64

# Passphrase constraints. The original tool had no limit; a too-long passphrase
# could cause the meta file to grow past what the RAGE engine accepts. 256
# is a generous cap that won't hit game-side limits.
PASSPHRASE_MIN_LEN = 1
PASSPHRASE_MAX_LEN = 256

# Schema version. Bump on any change to on-disk format.
SCHEMA_VERSION = 2


# Filename safety. We restrict the character set rather than try to escape
# bad characters, because the latter opens the door to spoofing (e.g. names
# that look identical under Unicode normalization).
# Allowed: any Unicode letter or digit, space, hyphen, underscore, dot,
# parentheses. Disallowed: path separators (/, \\), colons (Windows drive
# letters), control chars, anything that's not a letter, digit, or the
# specific punctuation set below.
def _is_allowed_name_char(ch: str) -> bool:
    """True if `ch` is a letter, digit, or one of the allowed punctuation marks."""
    if ch in " _.-()":
        return True
    cat = unicodedata.category(ch)
    return cat.startswith("L") or cat.startswith("N")


# Strict subset of disallowed characters shown to users in error messages.
_DISALLOWED_NAME_CHARS_HINT = '/ \\ : * ? " < > | and control characters'

# A name that is all-whitespace, or contains only dots, is reserved
# (matches Windows reserved names: CON, PRN, AUX, NUL, COM1-9, LPT1-9).
_WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


# --- Exceptions ---


class LobbyError(ValueError):
    """Base class for Lobby validation errors."""


class InvalidLobbyNameError(LobbyError):
    """The lobby name failed validation."""


class InvalidPassphraseError(LobbyError):
    """The passphrase failed validation."""


# --- The dataclass ---


@dataclass(frozen=True, slots=True)
class Lobby:
    """A single saved private-lobby configuration.

    The dataclass is `frozen` so an instance is hashable and immutable —
    any change requires constructing a new Lobby, which re-runs validation.
    This makes it impossible to have a "Lobby with an invalid name" in memory.

    Fields:
        name: human-readable identifier, also used as the .lobby filename
              (without extension). Validated against NAME_RE.
        passphrase: the lobby password/code. Validated for length and
                    forbidden characters. Stored encrypted on disk.
        created_at: UTC timestamp of when the lobby was first created.
        modified_at: UTC timestamp of the last modification.
        notes: optional freeform field for the user (no constraints).
    """

    name: str
    passphrase: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    modified_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    notes: str = ""

    def __post_init__(self) -> None:
        # `frozen=True` + `__post_init__` means we validate BEFORE the frozen
        # instance is created. If we raise here, no Lobby is produced.
        normalized_name = _validate_name(self.name)
        normalized_pass = _validate_passphrase(self.passphrase)

        # object.__setattr__ because the dataclass is frozen
        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "passphrase", normalized_pass)

    # --- File path helpers ---

    @property
    def file_stem(self) -> str:
        """Return the safe-on-every-FS stem for the .lobby file.

        Unicode-normalized to NFC and stripped of leading/trailing dots and
        whitespace, so the same logical name always produces the same file
        regardless of which input form was used.
        """
        return self.name.strip().strip(".")

    def to_filename(self) -> str:
        """Return the full .lobby filename."""
        return f"{self.file_stem}.lobby"

    # --- Mutation ---

    def with_changes(
        self,
        *,
        name: str | None = None,
        passphrase: str | None = None,
        notes: str | None = None,
    ) -> Lobby:
        """Return a new Lobby with the specified fields updated.

        The original instance is unchanged (frozen). updated modified_at.
        """
        new_name = name if name is not None else self.name
        new_pass = passphrase if passphrase is not None else self.passphrase
        new_notes = notes if notes is not None else self.notes
        return Lobby(
            name=new_name,
            passphrase=new_pass,
            created_at=self.created_at,
            modified_at=datetime.now(UTC),
            notes=new_notes,
        )


# --- Validators (private) ---


def _validate_name(raw: str) -> str:
    """Normalize and validate a lobby name. Raises InvalidLobbyNameError on failure.

    Normalization steps:
    1. Strip leading/trailing whitespace.
    2. Unicode-normalize to NFC so the same logical name produces one file.
    """
    if not isinstance(raw, str):
        msg = f"Lobby name must be a string, got {type(raw).__name__}"
        raise InvalidLobbyNameError(msg)

    stripped = raw.strip()
    nfc = unicodedata.normalize("NFC", stripped)

    if len(nfc) < NAME_MIN_LEN:
        msg = "Lobby name cannot be empty."
        raise InvalidLobbyNameError(msg)
    if len(nfc.encode("utf-8")) > NAME_MAX_LEN:
        msg = f"Lobby name exceeds {NAME_MAX_LEN} bytes (UTF-8)."
        raise InvalidLobbyNameError(msg)

    if not all(_is_allowed_name_char(ch) for ch in nfc):
        for i, ch in enumerate(nfc):
            if not _is_allowed_name_char(ch):
                msg = (
                    f"Invalid character {ch!r} at position {i} in lobby name. "
                    f"Names may contain letters, digits, spaces, and . _ - ( ) only. "
                    f"Disallowed: {_DISALLOWED_NAME_CHARS_HINT}."
                )
                raise InvalidLobbyNameError(msg)
        # Unreachable but satisfies type checkers.
        msg = f"Invalid lobby name {nfc!r}."
        raise InvalidLobbyNameError(msg)

    if nfc.upper() in _WINDOWS_RESERVED:
        msg = f"Invalid lobby name {nfc!r}: reserved system name on Windows."
        raise InvalidLobbyNameError(msg)

    if nfc in {".", ".."}:
        msg = f"Invalid lobby name {nfc!r}: reserved path component."
        raise InvalidLobbyNameError(msg)

    return nfc


def _validate_passphrase(raw: str) -> str:
    """Validate a lobby passphrase. Raises InvalidPassphraseError on failure."""
    if not isinstance(raw, str):
        msg = f"Passphrase must be a string, got {type(raw).__name__}"
        raise InvalidPassphraseError(msg)

    if len(raw) < PASSPHRASE_MIN_LEN:
        msg = "Passphrase cannot be empty."
        raise InvalidPassphraseError(msg)
    if len(raw) > PASSPHRASE_MAX_LEN:
        msg = (
            f"Passphrase exceeds {PASSPHRASE_MAX_LEN} characters. "
            f"Got {len(raw)}. This limit exists to keep the meta file within "
            f"the size range the game engine accepts."
        )
        raise InvalidPassphraseError(msg)

    # No newlines, no carriage returns, no NUL — these would corrupt the
    # .lobby file format and split the key=value lines.
    for char in ("\n", "\r", "\x00"):
        if char in raw:
            display = {chr(10): "newline", chr(13): "carriage return", chr(0): "NUL"}.get(
                char, repr(char)
            )
            msg = f"Passphrase cannot contain {display} characters."
            raise InvalidPassphraseError(msg)

    return raw

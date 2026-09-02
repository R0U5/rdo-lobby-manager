"""Storage-layer exceptions.

Lives in its own module to avoid circular imports between lobby_store.py
and migrations.py (which both need to raise the same exception types).
"""

from __future__ import annotations

from pathlib import Path


class LobbyStoreError(Exception):
    """Base class for storage errors."""


class LobbyNotFoundError(LobbyStoreError):
    """The requested lobby does not exist in the store."""


class LobbyAlreadyExistsError(LobbyStoreError):
    """A lobby with the given name already exists. Use `update` or rename."""

    def __init__(self, name: str, path: Path) -> None:
        super().__init__(f"Lobby {name!r} already exists at {path}")
        self.name = name
        self.path = path


class LobbyStoreCorruptError(LobbyStoreError):
    """A .lobby file is unreadable or has an invalid schema."""

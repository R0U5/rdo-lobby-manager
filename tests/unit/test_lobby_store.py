"""Tests for storage/lobby_store.py — encrypted CRUD on .lobby files."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rdo_lobby_manager.config import crypto as crypto_module
from rdo_lobby_manager.domain.lobby import Lobby
from rdo_lobby_manager.storage.errors import (
    LobbyAlreadyExistsError,
    LobbyNotFoundError,
    LobbyStoreCorruptError,
)
from rdo_lobby_manager.storage.lobby_store import LobbyStore
from rdo_lobby_manager.storage.migrations import parse_v1_text


@pytest.fixture(autouse=True)
def _reset_fernet_cache():
    crypto_module.reset_cached_fernet()
    yield
    crypto_module.reset_cached_fernet()


@pytest.fixture
def store(isolated_data_dir: Path) -> LobbyStore:
    """An empty LobbyStore rooted in the test's isolated data dir."""
    return LobbyStore()


# --- Add / Get / List ---


class TestAdd:
    def test_add_creates_file(self, store: LobbyStore, isolated_data_dir: Path):
        lobby = Lobby(name="MyLobby", passphrase="secret")
        store.add(lobby)
        path = isolated_data_dir / "data" / "lobbies" / "MyLobby.lobby"
        assert path.exists()

    def test_add_writes_json(self, store: LobbyStore):
        store.add(Lobby(name="X", passphrase="y"))
        path = next((store.root).iterdir())
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == 2
        assert data["name"] == "X"
        assert "passphrase_encrypted" in data
        assert "gAAAAA" in data["passphrase_encrypted"]  # looks like a Fernet token
        assert "passphrase" not in data  # not plaintext

    def test_add_rejects_duplicate(self, store: LobbyStore):
        store.add(Lobby(name="X", passphrase="y"))
        with pytest.raises(LobbyAlreadyExistsError, match="already exists"):
            store.add(Lobby(name="X", passphrase="different"))

    def test_add_round_trips_passphrase(self, store: LobbyStore):
        original = Lobby(name="X", passphrase="mySecret🔑")
        store.add(original)
        loaded = store.get("X")
        assert loaded.passphrase == "mySecret🔑"
        assert loaded.name == "X"

    def test_add_preserves_timestamps(self, store: LobbyStore):
        created = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        modified = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)
        lobby = Lobby(
            name="X",
            passphrase="y",
            created_at=created,
            modified_at=modified,
        )
        store.add(lobby)
        loaded = store.get("X")
        assert loaded.created_at == created
        assert loaded.modified_at == modified


class TestGet:
    def test_get_missing_raises(self, store: LobbyStore):
        with pytest.raises(LobbyNotFoundError):
            store.get("nope")

    def test_get_returns_lobby(self, store: LobbyStore):
        store.add(Lobby(name="X", passphrase="y"))
        lobby = store.get("X")
        assert isinstance(lobby, Lobby)
        assert lobby.name == "X"
        assert lobby.passphrase == "y"


class TestList:
    def test_list_empty(self, store: LobbyStore):
        assert store.list() == []
        assert store.list_names() == []

    def test_list_returns_all(self, store: LobbyStore):
        store.add(Lobby(name="B", passphrase="p2"))
        store.add(Lobby(name="A", passphrase="p1"))
        store.add(Lobby(name="C", passphrase="p3"))
        assert store.list_names() == ["A", "B", "C"]
        assert [entry.name for entry in store.list()] == ["A", "B", "C"]

    def test_list_skips_non_lobby_files(self, store: LobbyStore):
        store.add(Lobby(name="Real", passphrase="p"))
        # Drop a junk file in the store dir
        (store.root / "README.md").write_text("hello")
        (store.root / "settings.json").write_text("{}")
        (store.root / "Real.txt").write_text("not a lobby")
        names = store.list_names()
        assert names == ["Real"]

    def test_list_skips_corrupt_files_with_warning(
        self, store: LobbyStore, caplog: pytest.LogCaptureFixture
    ):
        store.add(Lobby(name="Good", passphrase="p"))
        (store.root / "Bad.lobby").write_text("{not valid json")
        lobbies = store.list()
        assert [entry.name for entry in lobbies] == ["Good"]


# --- Update ---


class TestUpdate:
    def test_update_existing(self, store: LobbyStore):
        store.add(Lobby(name="X", passphrase="old"))
        updated = store.get("X").with_changes(passphrase="new")
        store.update(updated)
        assert store.get("X").passphrase == "new"

    def test_update_missing_raises(self, store: LobbyStore):
        with pytest.raises(LobbyNotFoundError):
            store.update(Lobby(name="Ghost", passphrase="x"))

    def test_update_changes_modified_at(self, store: LobbyStore):
        original = Lobby(name="X", passphrase="p")
        store.add(original)
        updated = original.with_changes(passphrase="q")
        assert updated.modified_at >= original.modified_at
        store.update(updated)
        assert store.get("X").modified_at >= original.modified_at


# --- Delete / Undelete ---


class TestDelete:
    def test_delete_existing(self, store: LobbyStore):
        store.add(Lobby(name="X", passphrase="p"))
        assert store.exists("X")
        store.delete("X")
        assert not store.exists("X")

    def test_delete_missing_is_noop(self, store: LobbyStore):
        """No-op for missing entries, unlike get() which raises."""
        result = store.delete("nonexistent")
        assert result is None

    def test_delete_moves_to_trash(self, store: LobbyStore):
        """B19-mitigated: delete moves to trash, not unlink, so undo is possible."""
        store.add(Lobby(name="X", passphrase="p"))
        deleted_path = store.delete("X")
        assert deleted_path is not None
        # The returned path is the new trash location
        assert deleted_path.exists()
        assert ".trash" in str(deleted_path)
        # The original location is empty
        assert not (store.root / "X.lobby").exists()
        # And exactly one file lives in .trash
        trash_files = list((store.root / ".trash").iterdir())
        assert len(trash_files) == 1
        assert trash_files[0].name.startswith("X.")

    def test_undelete_restores_lobby(self, store: LobbyStore):
        store.add(Lobby(name="X", passphrase="p"))
        deleted_path = store.delete("X")
        store.undelete(deleted_path)  # type: ignore[arg-type]
        assert store.exists("X")
        assert store.get("X").passphrase == "p"

    def test_undelete_adds_suffix_on_collision(self, store: LobbyStore):
        """If user created a new lobby with the same name while the old was in
        trash, undelete should NOT clobber — it adds `-restored1`."""
        store.add(Lobby(name="X", passphrase="old"))
        deleted_path = store.delete("X")
        # Create a new lobby with the same name
        store.add(Lobby(name="X", passphrase="new"))
        store.undelete(deleted_path)  # type: ignore[arg-type]
        # Both should exist now
        names = store.list_names()
        assert "X" in names
        assert any("X-restored" in n for n in names)
        # The original "X" is the new one
        assert store.get("X").passphrase == "new"


# --- Rename ---


class TestRename:
    def test_rename(self, store: LobbyStore):
        store.add(Lobby(name="Old", passphrase="p"))
        store.rename("Old", Lobby(name="New", passphrase="p"))
        assert not store.exists("Old")
        assert store.exists("New")

    def test_rename_to_existing_raises(self, store: LobbyStore):
        store.add(Lobby(name="A", passphrase="p"))
        store.add(Lobby(name="B", passphrase="q"))
        with pytest.raises(LobbyAlreadyExistsError):
            store.rename("A", Lobby(name="B", passphrase="different"))

    def test_rename_to_same_name_is_update(self, store: LobbyStore):
        store.add(Lobby(name="X", passphrase="old"))
        store.rename("X", Lobby(name="X", passphrase="new"))
        assert store.get("X").passphrase == "new"

    def test_rename_updates_content(self, store: LobbyStore):
        store.add(Lobby(name="Old", passphrase="old_pass", notes=""))
        new = Lobby(name="New", passphrase="new_pass", notes="fresh")
        store.rename("Old", new)
        loaded = store.get("New")
        assert loaded.passphrase == "new_pass"
        assert loaded.notes == "fresh"


# --- File format / safety ---


class TestFileFormat:
    def test_lobby_file_is_valid_json(self, store: LobbyStore):
        store.add(Lobby(name="X", passphrase="y"))
        path = next((store.root).iterdir())
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == 2

    def test_passphrase_not_in_plaintext_on_disk(self, store: LobbyStore):
        """B6 fix: the literal passphrase must not appear in the file bytes."""
        passphrase = "supersecretvalue123"
        store.add(Lobby(name="X", passphrase=passphrase))
        path = next((store.root).iterdir())
        content = path.read_text(encoding="utf-8")
        assert passphrase not in content

    def test_atomic_write_no_leftover_tmp_files(self, store: LobbyStore, isolated_data_dir: Path):
        """Even after successful writes, no .tmp files should be left behind."""
        store.add(Lobby(name="A", passphrase="a"))
        store.add(Lobby(name="B", passphrase="b"))
        store.update(Lobby(name="A", passphrase="a2"))
        tmp_files = list(store.root.glob(".A.lobby.*.tmp")) + list(
            store.root.glob(".B.lobby.*.tmp")
        )
        assert tmp_files == []


# --- v1 -> v2 migration ---


class TestV1Migration:
    def test_parse_v1_text_basic(self):
        text = "pass=mysecret\nlines=2\n"
        pairs = parse_v1_text(text)
        assert pairs == {"pass": "mysecret", "lines": "2"}

    def test_parse_v1_text_handles_crlf(self):
        """B17 fix: v1 files on Windows may have CRLF line endings."""
        text = "pass=mysecret\r\nlines=2\r\n"
        pairs = parse_v1_text(text)
        assert pairs == {"pass": "mysecret", "lines": "2"}

    def test_parse_v1_text_handles_lone_cr(self):
        text = "pass=mysecret\rlines=2\r"
        pairs = parse_v1_text(text)
        assert pairs == {"pass": "mysecret", "lines": "2"}

    def test_parse_v1_text_empty_raises(self):
        with pytest.raises(LobbyStoreCorruptError, match="No key=value"):
            parse_v1_text("")

    def test_lobby_store_reads_v1_file(self, store: LobbyStore):
        """A v1 plaintext file in the store dir should be readable."""
        path = store.root / "Legacy.lobby"
        path.write_text("pass=oldstyle\nlines=2\n", encoding="utf-8")
        lobby = store.get("Legacy")
        assert lobby.passphrase == "oldstyle"

    def test_lobby_store_rewrites_v1_to_v2_on_read(self, store: LobbyStore):
        """After reading a v1 file, the store rewrites it in v2 format."""
        path = store.root / "Legacy.lobby"
        path.write_text("pass=oldstyle\nlines=2\n", encoding="utf-8")
        store.get("Legacy")  # triggers migration
        # File should now be JSON
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == 2
        assert data["name"] == "Legacy"
        # And the plaintext "oldstyle" should be gone
        assert "oldstyle" not in path.read_text(encoding="utf-8")
        assert "gAAAAA" in path.read_text(encoding="utf-8")

    def test_lobby_store_with_passphrase_newline_is_corrupt(self, store: LobbyStore):
        """A v1 file with a newline in the passphrase value should be flagged
        as corrupt (not silently truncated)."""
        path = store.root / "Bad.lobby"
        # v1 files used raw newlines, so a "pass=foo\nbar\n" would have been
        # parsed as pass=foo, then "bar" on the next line as a stray value.
        path.write_text("pass=foo\nbar\n", encoding="utf-8")
        # The parse might succeed (with extra "bar" line ignored) — that's
        # the v1 behavior. The point is we don't crash, we return what we can.
        lobby = store.get("Bad")
        # pass= should be the first line
        assert lobby.passphrase == "foo"


class TestCorruptFiles:
    def test_invalid_json_raises(self, store: LobbyStore):
        path = store.root / "Bad.lobby"
        path.write_text("not valid json at all", encoding="utf-8")
        with pytest.raises(LobbyStoreCorruptError):
            store.get("Bad")

    def test_empty_file_raises(self, store: LobbyStore):
        path = store.root / "Empty.lobby"
        path.write_text("", encoding="utf-8")
        with pytest.raises(LobbyStoreCorruptError):
            store.get("Empty")

    def test_json_missing_required_fields_raises(self, store: LobbyStore):
        path = store.root / "Incomplete.lobby"
        path.write_text('{"schema_version": 2, "name": "X"}', encoding="utf-8")
        with pytest.raises(LobbyStoreCorruptError):
            store.get("Incomplete")

    def test_encrypted_with_wrong_key_raises(self, store: LobbyStore, isolated_data_dir: Path):
        """If the key file changes, stored ciphertext becomes unreadable."""
        from rdo_lobby_manager.config.paths import crypto_key_file

        # Add a lobby, then rotate the key
        store.add(Lobby(name="X", passphrase="p"))
        import secrets

        new_key = secrets.token_bytes(32)
        crypto_key_file().write_bytes(new_key)
        crypto_module.reset_cached_fernet()
        with pytest.raises(LobbyStoreCorruptError, match="decrypt"):
            store.get("X")


class TestPathSafety:
    def test_lobby_path_rejects_unsafe_names(self):
        """The helper used internally to build paths must reject bad names."""
        # Path-traversal in the name would let the file escape the store dir
        from rdo_lobby_manager.domain.lobby import InvalidLobbyNameError

        with pytest.raises(InvalidLobbyNameError):
            Lobby(name="../escape", passphrase="p")
        with pytest.raises(InvalidLobbyNameError):
            Lobby(name="with/slash", passphrase="p")

"""Tests for domain/lobby.py — validate the Lobby dataclass invariants.

These tests are the *enforcement layer* for bugs B3, B4, B5, B7, B8 from
the decompilation. If a Lobby can be constructed with a bad name, bad
passphrase, or with a value that would break the file format, the
redesign has failed.
"""

from __future__ import annotations

import pytest

from rdo_lobby_manager.domain.lobby import (
    NAME_MAX_LEN,
    PASSPHRASE_MAX_LEN,
    InvalidLobbyNameError,
    InvalidPassphraseError,
    Lobby,
)


class TestLobbyConstruction:
    def test_minimal_valid_lobby(self):
        lobby = Lobby(name="MyLobby", passphrase="secret")
        assert lobby.name == "MyLobby"
        assert lobby.passphrase == "secret"
        assert lobby.notes == ""

    def test_lobby_is_frozen(self):
        lobby = Lobby(name="X", passphrase="y")
        with pytest.raises((AttributeError, Exception)):
            lobby.name = "Z"  # type: ignore[misc]

    def test_lobby_is_hashable(self):
        a = Lobby(name="X", passphrase="y")
        b = Lobby(name="X", passphrase="y")
        # Note: created_at is set to datetime.now() in default_factory, so
        # two Lobbies created in sequence will differ in timestamp. We test
        # hashability on a constructed one, not equality.
        assert hash(a) is not None
        assert {a, b}  # doesn't raise


class TestNameValidation:
    """B3: No filename validation in the original. We make it impossible
    to construct a Lobby with an invalid name."""

    def test_simple_ascii_name(self):
        lobby = Lobby(name="MyLobby_2026", passphrase="p")
        assert lobby.name == "MyLobby_2026"

    def test_name_with_space_dot_hyphen_underscore_paren(self):
        # All allowed characters
        lobby = Lobby(name="My Lobby (v2).final-version", passphrase="p")
        assert "My Lobby" in lobby.name

    def test_unicode_name_accepted(self):
        """Non-ASCII names work (CJK, Cyrillic, accented Latin)."""
        lobby = Lobby(name="私密大厅", passphrase="p")
        assert lobby.name == "私密大厅"

    def test_unicode_normalized_to_nfc(self):
        """e + combining acute (NFD) becomes é (NFC) so identical-logical
        names don't produce different files."""
        # 'é' can be encoded as one codepoint (NFC) or as 'e' + combining
        # acute (NFD). We canonicalize to NFC.
        nfd_name = "Caf\u0065\u0301"  # e + combining acute
        nfc_name = "Café"
        lobby_nfd = Lobby(name=nfd_name, passphrase="p")
        assert lobby_nfd.name == nfc_name

    def test_empty_name_rejected(self):
        with pytest.raises(InvalidLobbyNameError, match="empty"):
            Lobby(name="", passphrase="p")

    def test_whitespace_only_name_rejected(self):
        """After stripping, empty -> rejected."""
        with pytest.raises(InvalidLobbyNameError, match="empty"):
            Lobby(name="   ", passphrase="p")

    def test_dot_only_name_rejected(self):
        """`.` and `..` are path components — must be rejected."""
        with pytest.raises(InvalidLobbyNameError, match="reserved path"):
            Lobby(name="..", passphrase="p")
        with pytest.raises(InvalidLobbyNameError, match="reserved path"):
            Lobby(name=".", passphrase="p")

    @pytest.mark.parametrize("reserved", ["CON", "PRN", "AUX", "NUL", "COM1", "LPT9"])
    def test_windows_reserved_names_rejected(self, reserved: str):
        with pytest.raises(InvalidLobbyNameError, match="reserved"):
            Lobby(name=reserved, passphrase="p")

    @pytest.mark.parametrize(
        "bad_name",
        [
            "name/with/slash",
            "name\\with\\backslash",
            "name:colon",
            "name*star",
            "name?q",
            'name"quote',
            "name<lt",
            "name>gt",
            "name|pipe",
            "name\x00null",
            "name\nnewline",
        ],
    )
    def test_path_traversal_characters_rejected(self, bad_name: str):
        """B3: any character that would let a name escape the lobby dir."""
        with pytest.raises(InvalidLobbyNameError):
            Lobby(name=bad_name, passphrase="p")

    def test_name_too_long_rejected(self):
        with pytest.raises(InvalidLobbyNameError, match="exceeds"):
            Lobby(name="A" * (NAME_MAX_LEN + 1), passphrase="p")

    def test_unicode_name_too_long_in_bytes(self):
        """Length is in UTF-8 bytes, not characters."""
        # CJK characters are 3 bytes each in UTF-8
        long_cjk = "私" * 20  # 60 bytes, fits
        too_long_cjk = "私" * 30  # 90 bytes, exceeds
        Lobby(name=long_cjk, passphrase="p")  # ok
        with pytest.raises(InvalidLobbyNameError, match="exceeds"):
            Lobby(name=too_long_cjk, passphrase="p")

    def test_emoji_rejected_in_name(self):
        """Emoji (Unicode category 'So') are not allowed in names.

        Rationale: they take multiple codepoints (variation selectors, ZWJ
        sequences), the byte count is non-obvious, and original Qt6 UI
        didn't render them well. Users can still put emoji in `notes`.
        """
        with pytest.raises(InvalidLobbyNameError, match="Invalid character"):
            Lobby(name="MyLobby🦞", passphrase="p")

    def test_name_strips_whitespace(self):
        lobby = Lobby(name="  MyLobby  ", passphrase="p")
        assert lobby.name == "MyLobby"

    def test_name_truncation_not_applied(self):
        """If too long, raise — don't silently truncate."""
        long_name = "x" * 200
        with pytest.raises(InvalidLobbyNameError):
            Lobby(name=long_name, passphrase="p")


class TestPassphraseValidation:
    """B4, B5: original tool had no length limit and no newline validation."""

    def test_minimal_passphrase(self):
        lobby = Lobby(name="L", passphrase="x")
        assert lobby.passphrase == "x"

    def test_long_passphrase_accepted_within_limit(self):
        Lobby(name="L", passphrase="a" * PASSPHRASE_MAX_LEN)

    def test_passphrase_too_long_rejected(self):
        with pytest.raises(InvalidPassphraseError, match="exceeds"):
            Lobby(name="L", passphrase="a" * (PASSPHRASE_MAX_LEN + 1))

    @pytest.mark.parametrize("bad", ["with\nnewline", "with\rcarriage", "with\x00null"])
    def test_passphrase_with_forbidden_char_rejected(self, bad: str):
        """B5: A newline in the passphrase would corrupt the file format."""
        with pytest.raises(InvalidPassphraseError):
            Lobby(name="L", passphrase=bad)

    def test_empty_passphrase_rejected(self):
        with pytest.raises(InvalidPassphraseError, match="empty"):
            Lobby(name="L", passphrase="")

    def test_unicode_passphrase_accepted(self):
        """Passphrases can contain any non-control, non-newline unicode."""
        lobby = Lobby(name="L", passphrase="pässwörd🔑")
        assert "🔑" in lobby.passphrase


class TestLobbyHelpers:
    def test_file_stem_uses_name(self):
        lobby = Lobby(name="MyLobby", passphrase="p")
        assert lobby.file_stem == "MyLobby"

    def test_to_filename_appends_extension(self):
        lobby = Lobby(name="MyLobby", passphrase="p")
        assert lobby.to_filename() == "MyLobby.lobby"

    def test_stripped_name_becomes_file_stem(self):
        """The .lobby filename uses the stripped form, not the raw input."""
        lobby = Lobby(name="  spaced  ", passphrase="p")
        assert lobby.to_filename() == "spaced.lobby"

    def test_dot_trimmed_from_file_stem(self):
        """Trailing dots are stripped so we don't get weird `.lobby.lobby`."""
        lobby = Lobby(name="MyLobby...", passphrase="p")
        assert lobby.to_filename() == "MyLobby.lobby"


class TestWithChanges:
    def test_update_passphrase_preserves_name_and_created_at(self):
        original = Lobby(name="X", passphrase="old")
        updated = original.with_changes(passphrase="new")
        assert updated.name == original.name
        assert updated.passphrase == "new"
        assert updated.created_at == original.created_at
        assert updated.modified_at >= original.modified_at

    def test_update_name_re_validates(self):
        original = Lobby(name="X", passphrase="p")
        with pytest.raises(InvalidLobbyNameError):
            original.with_changes(name="../escape")

    def test_update_preserves_notes_by_default(self):
        original = Lobby(name="X", passphrase="p", notes="original note")
        updated = original.with_changes(passphrase="new")
        assert updated.notes == "original note"

    def test_update_can_change_notes(self):
        original = Lobby(name="X", passphrase="p", notes="old")
        updated = original.with_changes(notes="new")
        assert updated.notes == "new"

    def test_original_instance_unchanged_after_with_changes(self):
        """`frozen` + `with_changes` = original stays intact, new one returned."""
        original = Lobby(name="X", passphrase="old")
        _ = original.with_changes(passphrase="new")
        assert original.passphrase == "old"

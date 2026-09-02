"""Tests for domain/meta_file.py — read, parse, apply, restore with hash detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from rdo_lobby_manager.domain.meta_file import (
    MetaFileNotFoundError,
    MetaFileStore,
    MetaFileUnreadableError,
    _normalize_line_endings,
    read_meta_file,
)

# --- Helpers ---


def write_meta(path: Path, content: str) -> None:
    """Write a meta file in LF form."""
    path.write_text(content, encoding="utf-8")


SAMPLE_PRISTINE = """\
<?xml version="1.0"?>
<Startup>
  <dataFiles>
    <includedDataFiles />
  </dataFiles>
  <patchFiles />
  <contentChangeSets />
</Startup>
"""

SAMPLE_WITH_LOBBY = SAMPLE_PRISTINE + "pass=hunter2\nlines=2\n"


# --- Line-ending normalization (B17) ---


class TestNormalizeLineEndings:
    def test_already_lf(self):
        assert _normalize_line_endings("a\nb\nc") == "a\nb\nc"

    def test_crlf_converted(self):
        """B17 fix: the original tool's indexOf broke on Windows CRLF files."""
        assert _normalize_line_endings("a\r\nb\r\nc") == "a\nb\nc"

    def test_lone_cr_converted(self):
        assert _normalize_line_endings("a\rb\rc") == "a\nb\nc"

    def test_mixed_line_endings(self):
        assert _normalize_line_endings("a\nb\r\nc\rd") == "a\nb\nc\nd"


# --- read_meta_file ---


class TestReadMetaFile:
    def test_read_existing(self, tmp_path: Path):
        path = tmp_path / "startup.meta"
        write_meta(path, SAMPLE_PRISTINE)
        meta = read_meta_file(path)
        assert meta.content == SAMPLE_PRISTINE
        assert meta.key_values == {}
        assert meta.has_private_lobby() is False
        assert meta.passphrase is None
        assert meta.lines is None

    def test_read_with_crlf(self, tmp_path: Path):
        """B17: Windows-written file with CRLF should parse correctly."""
        path = tmp_path / "startup.meta"
        path.write_bytes(SAMPLE_WITH_LOBBY.replace("\n", "\r\n").encode("utf-8"))
        meta = read_meta_file(path)
        assert meta.content == SAMPLE_WITH_LOBBY  # normalized to LF
        assert meta.passphrase == "hunter2"
        assert meta.lines == 2

    def test_read_with_lobby(self, tmp_path: Path):
        path = tmp_path / "startup.meta"
        write_meta(path, SAMPLE_WITH_LOBBY)
        meta = read_meta_file(path)
        assert meta.passphrase == "hunter2"
        assert meta.lines == 2
        assert meta.has_private_lobby() is True

    def test_read_missing_raises(self, tmp_path: Path):
        with pytest.raises(MetaFileNotFoundError):
            read_meta_file(tmp_path / "does_not_exist.meta")

    def test_read_unreadable_raises(self, tmp_path: Path):
        path = tmp_path / "startup.meta"
        path.write_bytes(b"\xff\xfe\x00\x01not utf-8")
        with pytest.raises(MetaFileUnreadableError, match="UTF-8"):
            read_meta_file(path)

    def test_sha256_stable_for_same_content(self, tmp_path: Path):
        path = tmp_path / "startup.meta"
        write_meta(path, SAMPLE_PRISTINE)
        meta1 = read_meta_file(path)
        # Re-read after no change
        meta2 = read_meta_file(path)
        assert meta1.sha256 == meta2.sha256

    def test_sha256_changes_for_modified_content(self, tmp_path: Path):
        path = tmp_path / "startup.meta"
        write_meta(path, SAMPLE_PRISTINE)
        meta1 = read_meta_file(path)
        write_meta(path, SAMPLE_WITH_LOBBY)
        meta2 = read_meta_file(path)
        assert meta1.sha256 != meta2.sha256

    def test_lines_non_integer_returns_none(self, tmp_path: Path):
        path = tmp_path / "startup.meta"
        write_meta(path, SAMPLE_PRISTINE + "pass=x\nlines=notanumber\n")
        meta = read_meta_file(path)
        assert meta.lines is None
        assert meta.passphrase == "x"  # other parsing still works

    def test_ignores_unknown_keys(self, tmp_path: Path):
        """RAGE engine content has many keys; we only care about pass/lines."""
        path = tmp_path / "startup.meta"
        write_meta(path, SAMPLE_PRISTINE + "unrelated=value\nfoo=bar\n")
        meta = read_meta_file(path)
        assert meta.key_values == {}

    def test_does_not_match_key_inside_xml(self, tmp_path: Path):
        """A key=value substring inside XML markup must not be picked up."""
        path = tmp_path / "startup.meta"
        content = '<fileType pass="oops">RPF_FILE</fileType>\n'
        write_meta(path, content)
        meta = read_meta_file(path)
        # The line `pass="oops"` is part of an attribute, not a real pass= line.
        # Our regex anchors to line start, so it won't match.
        assert "pass" not in meta.key_values


# --- MetaFileStore: snapshot lifecycle ---


class TestMetaFileStoreSnapshot:
    def test_capture_default_creates_snapshot(self, tmp_path: Path, isolated_data_dir: Path):
        meta_path = tmp_path / "startup.meta"
        snapshot_path = tmp_path / "startup.meta.original"
        write_meta(meta_path, SAMPLE_PRISTINE)
        store = MetaFileStore(meta_path, snapshot_path)

        assert not store.has_default_snapshot()
        store.capture_default()
        assert store.has_default_snapshot()
        assert snapshot_path.read_text(encoding="utf-8") == SAMPLE_PRISTINE

    def test_is_default_true_after_capture(self, tmp_path: Path, isolated_data_dir: Path):
        meta_path = tmp_path / "startup.meta"
        snapshot_path = tmp_path / "snapshot"
        write_meta(meta_path, SAMPLE_PRISTINE)
        store = MetaFileStore(meta_path, snapshot_path)
        store.capture_default()
        assert store.is_default() is True

    def test_is_default_false_after_modification(self, tmp_path: Path, isolated_data_dir: Path):
        meta_path = tmp_path / "startup.meta"
        snapshot_path = tmp_path / "snapshot"
        write_meta(meta_path, SAMPLE_PRISTINE)
        store = MetaFileStore(meta_path, snapshot_path)
        store.capture_default()

        write_meta(meta_path, SAMPLE_WITH_LOBBY)
        assert store.is_default() is False

    def test_is_default_false_without_snapshot(self, tmp_path: Path, isolated_data_dir: Path):
        """Without a snapshot, we can't know — treat as modified/unknown."""
        meta_path = tmp_path / "startup.meta"
        snapshot_path = tmp_path / "snapshot"
        write_meta(meta_path, SAMPLE_PRISTINE)
        store = MetaFileStore(meta_path, snapshot_path)
        # No capture_default() call
        assert store.is_default() is False

    def test_is_default_true_even_after_game_update(self, tmp_path: Path, isolated_data_dir: Path):
        """B16 fix: dynamic baseline adapts to game patches.

        Scenario: app captures snapshot of v1.0's startup.meta. Game updates
        to v1.1, changing startup.meta. User runs the app, captures a new
        snapshot of v1.1's pristine content. Now the v1.1 baseline is what
        we restore — we never compare against a stale v1.0 blob.
        """
        meta_path = tmp_path / "startup.meta"
        snapshot_path = tmp_path / "snapshot"
        store = MetaFileStore(meta_path, snapshot_path)

        # v1.0 of the game
        write_meta(meta_path, "v1.0 content")
        store.capture_default()
        assert store.is_default() is True

        # Game updates to v1.1 — meta file changes
        write_meta(meta_path, "v1.1 content")
        # Without a new snapshot, we don't recognize v1.1 as default
        assert store.is_default() is False
        # User re-captures (UI: "Reset baseline" or first-use flow)
        store.capture_default()
        # Now v1.1 IS the default
        assert store.is_default() is True


# --- MetaFileStore: apply_lobby ---


class TestMetaFileStoreApply:
    def test_apply_creates_pass_and_lines(self, tmp_path: Path, isolated_data_dir: Path):
        meta_path = tmp_path / "startup.meta"
        snapshot_path = tmp_path / "snapshot"
        write_meta(meta_path, SAMPLE_PRISTINE)
        store = MetaFileStore(meta_path, snapshot_path)

        result = store.apply_lobby("mySecret", 2)
        assert result.passphrase == "mySecret"
        assert result.lines == 2
        assert "pass=mySecret" in result.content
        assert "lines=2" in result.content

    def test_apply_captures_default_if_missing(self, tmp_path: Path, isolated_data_dir: Path):
        """First-ever apply should snapshot the current state as the baseline."""
        meta_path = tmp_path / "startup.meta"
        snapshot_path = tmp_path / "snapshot"
        write_meta(meta_path, SAMPLE_PRISTINE)
        store = MetaFileStore(meta_path, snapshot_path)
        assert not store.has_default_snapshot()

        store.apply_lobby("pass", 1)
        assert store.has_default_snapshot()
        assert snapshot_path.read_text(encoding="utf-8") == SAMPLE_PRISTINE

    def test_apply_replaces_existing_lobby(self, tmp_path: Path, isolated_data_dir: Path):
        """Re-applying with a different passphrase must overwrite, not duplicate."""
        meta_path = tmp_path / "startup.meta"
        snapshot_path = tmp_path / "snapshot"
        write_meta(meta_path, SAMPLE_PRISTINE)
        store = MetaFileStore(meta_path, snapshot_path)
        store.apply_lobby("first", 1)
        store.apply_lobby("second", 3)

        meta = read_meta_file(meta_path)
        assert meta.passphrase == "second"
        assert meta.lines == 3
        # Exactly one pass= and one lines= in the file
        assert meta.content.count("pass=") == 1
        assert meta.content.count("lines=") == 1

    def test_apply_preserves_other_content(self, tmp_path: Path, isolated_data_dir: Path):
        """The RAGE engine content around the pass= / lines= must survive."""
        meta_path = tmp_path / "startup.meta"
        snapshot_path = tmp_path / "snapshot"
        write_meta(meta_path, SAMPLE_PRISTINE)
        store = MetaFileStore(meta_path, snapshot_path)
        store.apply_lobby("mySecret", 2)
        meta = read_meta_file(meta_path)
        # The XML prologue and structure are preserved
        assert "<?xml version" in meta.content
        assert "<Startup>" in meta.content
        assert "<dataFiles>" in meta.content

    def test_apply_preserves_snapshot(self, tmp_path: Path, isolated_data_dir: Path):
        """Modifying the live meta must NOT modify the snapshot."""
        meta_path = tmp_path / "startup.meta"
        snapshot_path = tmp_path / "snapshot"
        write_meta(meta_path, SAMPLE_PRISTINE)
        store = MetaFileStore(meta_path, snapshot_path)
        store.capture_default()
        snapshot_before = snapshot_path.read_bytes()

        store.apply_lobby("mySecret", 2)
        snapshot_after = snapshot_path.read_bytes()
        assert snapshot_before == snapshot_after

    def test_apply_to_missing_meta_raises(self, tmp_path: Path, isolated_data_dir: Path):
        meta_path = tmp_path / "does_not_exist.meta"
        snapshot_path = tmp_path / "snapshot"
        store = MetaFileStore(meta_path, snapshot_path)
        with pytest.raises(MetaFileNotFoundError):
            store.apply_lobby("x", 1)


# --- MetaFileStore: restore_default ---


class TestMetaFileStoreRestore:
    def test_restore_returns_to_default(self, tmp_path: Path, isolated_data_dir: Path):
        meta_path = tmp_path / "startup.meta"
        snapshot_path = tmp_path / "snapshot"
        write_meta(meta_path, SAMPLE_PRISTINE)
        store = MetaFileStore(meta_path, snapshot_path)
        store.capture_default()
        store.apply_lobby("mySecret", 2)
        assert not store.is_default()

        store.restore_default()
        assert store.is_default()

    def test_restore_without_snapshot_returns_none(self, tmp_path: Path, isolated_data_dir: Path):
        meta_path = tmp_path / "startup.meta"
        snapshot_path = tmp_path / "snapshot"
        write_meta(meta_path, SAMPLE_PRISTINE)
        store = MetaFileStore(meta_path, snapshot_path)
        result = store.restore_default()
        assert result is None

    def test_restore_preserves_only_lobby_changes(self, tmp_path: Path, isolated_data_dir: Path):
        """Restore removes the private-lobby config but keeps other RAGE content."""
        meta_path = tmp_path / "startup.meta"
        snapshot_path = tmp_path / "snapshot"
        write_meta(meta_path, SAMPLE_PRISTINE)
        store = MetaFileStore(meta_path, snapshot_path)
        store.capture_default()
        store.apply_lobby("mySecret", 2)
        store.restore_default()

        meta = read_meta_file(meta_path)
        assert meta.has_private_lobby() is False
        assert "<?xml version" in meta.content


# --- MetaFileStore: clear_snapshot ---


class TestMetaFileStoreClearSnapshot:
    def test_clear_removes_snapshot_file(self, tmp_path: Path, isolated_data_dir: Path):
        meta_path = tmp_path / "startup.meta"
        snapshot_path = tmp_path / "snapshot"
        write_meta(meta_path, SAMPLE_PRISTINE)
        store = MetaFileStore(meta_path, snapshot_path)
        store.capture_default()
        assert store.has_default_snapshot()
        store.clear_snapshot()
        assert not store.has_default_snapshot()

    def test_clear_when_no_snapshot_is_noop(self, tmp_path: Path, isolated_data_dir: Path):
        meta_path = tmp_path / "startup.meta"
        snapshot_path = tmp_path / "snapshot"
        store = MetaFileStore(meta_path, snapshot_path)
        # No snapshot exists; clear_snapshot must not raise
        store.clear_snapshot()
        assert not store.has_default_snapshot()


# --- Integration with v1 format compatibility ---


class TestV1Compatibility:
    """The original Qt6 tool wrote meta files with pass=/lines= keys at the
    end. Our parser must accept that format on read (so existing v1 state
    is recoverable) and our apply_lobby must produce the same shape."""

    def test_reads_v1_format(self, tmp_path: Path):
        path = tmp_path / "startup.meta"
        write_meta(path, SAMPLE_WITH_LOBBY)
        meta = read_meta_file(path)
        assert meta.has_private_lobby() is True
        assert meta.passphrase == "hunter2"
        assert meta.lines == 2

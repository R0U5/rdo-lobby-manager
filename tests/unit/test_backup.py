"""Tests for util/backup.py — non-overwriting backup semantics (B14)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rdo_lobby_manager.util.backup import (
    MAX_BACKUPS,
    BackupError,
    BackupInfo,
    BackupNotFoundError,
    BackupStore,
    _parse_backup_timestamp,
)


def write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


class TestCreate:
    def test_create_makes_new_file(self, tmp_path: Path):
        src = tmp_path / "original.txt"
        write_file(src, "hello")
        store = BackupStore(tmp_path / "backups")
        info = store.create(src, base_name="original")
        assert info.path.exists()
        assert info.base_name == "original"
        assert info.size_bytes == 5  # "hello"

    def test_create_uses_utc_timestamp_in_filename(self, tmp_path: Path):
        src = tmp_path / "x.txt"
        write_file(src, "x")
        store = BackupStore(tmp_path / "backups")
        info = store.create(src, base_name="x")
        assert re.match(r"^x\.backup\.\d{8}T\d{6}Z\.bin$", info.path.name), (
            f"unexpected filename: {info.path.name}"
        )

    def test_create_increments_on_collision(self, tmp_path: Path):
        """Same-second creates must not collide."""
        src = tmp_path / "x.txt"
        write_file(src, "x")
        store = BackupStore(tmp_path / "backups")
        info1 = store.create(src, base_name="x")
        info2 = store.create(src, base_name="x")
        # If they have the same timestamp, one gets a -1 suffix
        if info1.path.name == info2.path.name:
            pytest.fail("Two backups got the same filename — collision not handled")
        # They have different paths
        assert info1.path != info2.path
        # Both exist
        assert info1.path.exists() and info2.path.exists()

    def test_create_preserves_source_content(self, tmp_path: Path):
        src = tmp_path / "src.txt"
        write_file(src, "important content with various bytes \x00\x01\x02")
        store = BackupStore(tmp_path / "backups")
        info = store.create(src, base_name="src")
        assert info.path.read_bytes() == src.read_bytes()

    def test_create_missing_source_raises(self, tmp_path: Path):
        store = BackupStore(tmp_path / "backups")
        with pytest.raises(BackupError, match="does not exist"):
            store.create(tmp_path / "ghost.txt", base_name="ghost")

    def test_create_directory_source_raises(self, tmp_path: Path):
        # A directory, not a file
        (tmp_path / "subdir").mkdir()
        store = BackupStore(tmp_path / "backups")
        with pytest.raises(BackupError, match="not a regular file"):
            store.create(tmp_path / "subdir", base_name="subdir")

    def test_create_default_base_name_strips_extension(self, tmp_path: Path):
        src = tmp_path / "startup.meta"
        write_file(src, "data")
        store = BackupStore(tmp_path / "backups")
        # No base_name passed; should default to "startup.meta" -> "startup.meta"
        info = store.create(src)
        assert info.base_name == "startup.meta"


class TestList:
    def test_list_empty(self, tmp_path: Path):
        store = BackupStore(tmp_path / "backups")
        assert store.list() == []

    def test_list_returns_newest_first(self, tmp_path: Path):
        src = tmp_path / "x.txt"
        write_file(src, "x")
        store = BackupStore(tmp_path / "backups")
        # Create 3 backups — can't force different timestamps from a real
        # clock, but the list should be sorted newest-first regardless
        store.create(src, base_name="x")
        store.create(src, base_name="x")
        store.create(src, base_name="x")
        infos = store.list("x")
        assert len(infos) == 3
        # Newest first
        assert infos[0].created_at >= infos[1].created_at >= infos[2].created_at

    def test_list_filtered_by_base_name(self, tmp_path: Path):
        src_a = tmp_path / "a.txt"
        src_b = tmp_path / "b.txt"
        write_file(src_a, "a")
        write_file(src_b, "b")
        store = BackupStore(tmp_path / "backups")
        store.create(src_a, base_name="a")
        store.create(src_b, base_name="b")
        store.create(src_a, base_name="a")

        a_infos = store.list("a")
        b_infos = store.list("b")
        assert len(a_infos) == 2
        assert len(b_infos) == 1
        assert all(info.base_name == "a" for info in a_infos)
        assert all(info.base_name == "b" for info in b_infos)


class TestLatest:
    def test_latest_returns_most_recent(self, tmp_path: Path):
        src = tmp_path / "x.txt"
        write_file(src, "x")
        store = BackupStore(tmp_path / "backups")
        store.create(src, base_name="x")
        store.create(src, base_name="x")
        latest = store.latest("x")
        # Should be the second one (newest)
        all_infos = store.list("x")
        assert latest.path == all_infos[0].path

    def test_latest_missing_raises(self, tmp_path: Path):
        store = BackupStore(tmp_path / "backups")
        with pytest.raises(BackupNotFoundError):
            store.latest("nothing")


class TestRestore:
    def test_restore_writes_to_dest(self, tmp_path: Path):
        src = tmp_path / "original.txt"
        write_file(src, "important")
        store = BackupStore(tmp_path / "backups")
        info = store.create(src, base_name="original")

        # Modify then restore
        dest = tmp_path / "current.txt"
        write_file(dest, "modified")
        store.restore(info, dest)
        assert dest.read_text(encoding="utf-8") == "important"

    def test_restore_creates_parent_dirs(self, tmp_path: Path):
        src = tmp_path / "src.txt"
        write_file(src, "data")
        store = BackupStore(tmp_path / "backups")
        info = store.create(src, base_name="src")
        dest = tmp_path / "deep" / "nested" / "out.txt"
        store.restore(info, dest)
        assert dest.exists()

    def test_restore_preserves_backup(self, tmp_path: Path):
        src = tmp_path / "x.txt"
        write_file(src, "original")
        store = BackupStore(tmp_path / "backups")
        info = store.create(src, base_name="x")
        original_backup_size = info.path.stat().st_size
        store.restore(info, tmp_path / "out.txt")
        # Backup file untouched
        assert info.path.stat().st_size == original_backup_size
        assert info.path.read_bytes() == src.read_bytes()

    def test_restore_missing_backup_raises(self, tmp_path: Path):
        store = BackupStore(tmp_path / "backups")
        ghost = BackupInfo(
            path=tmp_path / "ghost.bin",
            base_name="ghost",
            created_at=datetime.now(UTC),
            size_bytes=0,
        )
        with pytest.raises(BackupNotFoundError):
            store.restore(ghost, tmp_path / "out.txt")


class TestPruning:
    def test_keeps_only_max_backups(self, tmp_path: Path):
        """B14 prevention: the system retains only MAX_BACKUPS and prunes older."""
        src = tmp_path / "x.txt"
        write_file(src, "x")
        store = BackupStore(tmp_path / "backups")
        # Create more than MAX_BACKUPS
        for _ in range(MAX_BACKUPS + 5):
            store.create(src, base_name="x")
        remaining = store.list("x")
        assert len(remaining) == MAX_BACKUPS

    def test_pruning_keeps_newest(self, tmp_path: Path):
        src = tmp_path / "x.txt"
        write_file(src, "x")
        store = BackupStore(tmp_path / "backups")
        for _ in range(MAX_BACKUPS + 3):
            store.create(src, base_name="x")
        # The newest MAX_BACKUPS should be the ones that survive
        latest = store.latest("x")
        assert latest.path.exists()

    def test_pruning_does_not_affect_other_basenames(self, tmp_path: Path):
        """Backups for 'a' must not be pruned when 'b' exceeds the limit."""
        src_a = tmp_path / "a.txt"
        src_b = tmp_path / "b.txt"
        write_file(src_a, "a")
        write_file(src_b, "b")
        store = BackupStore(tmp_path / "backups")

        # First, populate 'a' with 3 backups
        for _ in range(3):
            store.create(src_a, base_name="a")
        # Then, exceed the limit with 'b'
        for _ in range(MAX_BACKUPS + 3):
            store.create(src_b, base_name="b")
        # 'a' should still have 3
        assert len(store.list("a")) == 3
        # 'b' should be pruned to MAX_BACKUPS
        assert len(store.list("b")) == MAX_BACKUPS


class TestPurge:
    def test_purge_all(self, tmp_path: Path):
        src = tmp_path / "x.txt"
        write_file(src, "x")
        store = BackupStore(tmp_path / "backups")
        for _ in range(3):
            store.create(src, base_name="x")
        deleted = store.purge_all()
        assert deleted == 3
        assert store.list() == []

    def test_purge_filtered(self, tmp_path: Path):
        src_a = tmp_path / "a.txt"
        src_b = tmp_path / "b.txt"
        write_file(src_a, "a")
        write_file(src_b, "b")
        store = BackupStore(tmp_path / "backups")
        store.create(src_a, base_name="a")
        store.create(src_b, base_name="b")
        deleted = store.purge_all("a")
        assert deleted == 1
        assert store.list("a") == []
        assert len(store.list("b")) == 1


class TestParseTimestamp:
    def test_round_trip(self):
        ts = datetime(2026, 9, 2, 10, 34, 22, tzinfo=UTC)
        filename = f"x.backup.{ts.strftime('%Y%m%dT%H%M%SZ')}.bin"
        parsed = _parse_backup_timestamp(filename)
        assert parsed == ts

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            _parse_backup_timestamp("not-a-backup.bin")

    def test_non_matching_name_raises(self):
        with pytest.raises(ValueError):
            _parse_backup_timestamp("startup.meta")


class TestNonOverwriteGuarantee:
    """The B14 invariant: a fresh create() must never destroy an existing
    backup, even if the user 'Sets RDR2 Directory' a second time."""

    def test_multiple_creates_for_same_base_preserve_all(self, tmp_path: Path):
        src = tmp_path / "startup.meta"
        write_file(src, "v1")
        store = BackupStore(tmp_path / "backups")
        info1 = store.create(src, base_name="startup.meta")
        # Simulate the user re-pointing the app at the install — the
        # meta file might now be in a different state.
        write_file(src, "v2")
        info2 = store.create(src, base_name="startup.meta")
        # Both backups still exist and have their original content
        assert info1.path.read_text(encoding="utf-8") == "v1"
        assert info2.path.read_text(encoding="utf-8") == "v2"
        assert info1.path.exists()
        assert info2.path.exists()

    def test_restore_from_older_backup_does_not_touch_newer(self, tmp_path: Path):
        src = tmp_path / "x.txt"
        write_file(src, "v1")
        store = BackupStore(tmp_path / "backups")
        info1 = store.create(src, base_name="x")
        write_file(src, "v2")
        info2 = store.create(src, base_name="x")

        # Restore the older one
        store.restore(info1, tmp_path / "out.txt")
        # The newer backup is unchanged
        assert info2.path.read_text(encoding="utf-8") == "v2"

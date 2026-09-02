"""Atomic file write — fixes B11 (write-then-read race) and gives us crash-safe I/O.

A file is "atomically written" by:
1. Writing the new content to a temp file in the same directory
2. Fsync'ing the temp file
3. Renaming the temp file over the target (atomic on POSIX, atomic-enough on Windows)

This guarantees that any reader either sees the old content or the new content,
never partial. Combined with directory fsync it survives power loss.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Literal


def _fsync_dir(path: Path) -> None:
    """Best-effort fsync of the directory containing `path`.

    On Windows this isn't supported, so we silently skip.
    """
    if os.name == "nt":
        return
    fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_text(
    target: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    newline: Literal["\n", "\r\n", ""] = "\n",
) -> None:
    """Write `content` to `target` atomically (text mode).

    Args:
        target: destination file path. Parent dir is created if needed.
        content: text to write.
        encoding: text encoding (default utf-8).
        newline: line ending. Use "\n" for POSIX, "\r\n" for Windows, "" for no
            translation (writes literal \n).
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    # Use NamedTemporaryFile in same dir so os.replace is atomic on the same FS.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding=encoding,
        newline=newline,
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        try:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
        except BaseException:
            Path(tmp.name).unlink(missing_ok=True)
            raise
    Path(tmp.name).replace(target)
    _fsync_dir(target)


def atomic_write_bytes(target: Path, content: bytes | Iterable[bytes]) -> None:
    """Write bytes to `target` atomically. Same contract as atomic_write_text."""
    if isinstance(content, bytes):
        data: bytes = content
    elif isinstance(content, Iterable):
        data = b"".join(content)
    else:
        msg = f"Expected bytes or iterable of bytes, got {type(content).__name__}"
        raise TypeError(msg)

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        try:
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        except BaseException:
            Path(tmp.name).unlink(missing_ok=True)
            raise
    Path(tmp.name).replace(target)
    _fsync_dir(target)


@contextlib.contextmanager
def atomic_writer(
    target: Path,
    *,
    mode: Literal["text", "bytes"] = "text",
    encoding: str = "utf-8",
):
    """Context manager: yield a writable file handle that's auto-promoted to target on success.

    Use this when you need streaming writes (lots of data) but still want
    crash-safety. On exception, the temp file is removed and the target is
    untouched.

    Example:
        with atomic_writer("/etc/foo") as f:
            f.write("hello")
            f.write(" world")
        # On clean exit, /etc/foo contains "hello world"
        # On exception, /etc/foo is unchanged.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    suffix = ".tmp"
    binary = mode == "bytes"
    fd, tmp_path = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=suffix,
    )
    try:
        with os.fdopen(fd, "wb" if binary else "w", encoding=None if binary else encoding) as f:
            yield f
            f.flush()
            os.fsync(f.fileno())
        Path(tmp_path).replace(target)
        _fsync_dir(target)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise

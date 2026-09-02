"""Detect whether RDR2 is running before writing to its install directory.

Fixes B15: the original Qt6 tool would happily write to `startup.meta`
while the game was running. On Windows, file locking *might* prevent
the write (depending on how RDR2 opens the file), but on Linux/Proton
the write would succeed and the game's cached config would be wrong.

We check for the RDR2 process by name. On Windows we look for `RDR2.exe`;
on Linux/Proton we look for `RDR2` or the Proton wrapper process. The
check is best-effort: if we can't determine the process list (permissions,
platform differences), we err on the side of caution and return True
("is running") so the UI shows a warning rather than silently writing.
"""

from __future__ import annotations

import sys

from rdo_lobby_manager.util.log import get_logger

_LOG = get_logger(__name__)

# Process names that indicate RDR2 is running. We match case-insensitively
# on the executable name (not the full path).
_RDR2_PROCESS_NAMES: frozenset[str] = frozenset(
    {
        # Windows
        "rdr2.exe",
        "playrdr2.exe",  # Rockstar's pre-launcher
        # Linux/Proton — the game binary is named "RDR2" under Proton,
        # but the actual process might be the Proton wrapper.
        "rdr2",
        # Rockstar Launcher itself (if running, RDR2 might be too)
        "rockstarstarlauncher.exe",
        "launcher.exe",  # Generic but common for Rockstar
    }
)


class RDR2RunningError(Exception):
    """RDR2 appears to be running. Refuse to write to the meta file."""


def _get_process_names() -> list[str]:
    """Return the names of all running processes (lowercased).

    Uses the most appropriate method per platform:
    - Linux/macOS: `psutil` if available, else `/proc` or `ps`
    - Windows: `tasklist` or `psutil`

    Returns an empty list if the process list can't be determined.
    """
    # Try psutil first (cross-platform, most reliable)
    try:
        import psutil  # noqa: PLC0415  -- lazy import: psutil is optional

        return [p.info["name"].lower() for p in psutil.process_iter(["name"]) if p.info.get("name")]
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("psutil failed: %s", exc)

    # Fallback: platform-specific commands
    if sys.platform == "win32":
        return _get_process_names_windows()
    return _get_process_names_posix()


def _get_process_names_windows() -> list[str]:
    """Use `tasklist` on Windows to enumerate processes."""
    import subprocess  # noqa: PLC0415  -- lazy import: only needed when psutil is absent

    try:
        result = subprocess.run(  # noqa: S603 -- trusted system command
            ["tasklist", "/FO", "CSV", "/NH"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _LOG.warning("Could not run tasklist: %s", exc)
        return []
    names: list[str] = []
    for line in result.stdout.splitlines():
        # CSV format: "Name","PID","SessionName","Session#","Mem"
        parts = line.split(",")
        if parts:
            # Strip quotes
            name = parts[0].strip('"').lower()
            if name:
                names.append(name)
    return names


def _get_process_names_posix() -> list[str]:
    """Use `ps` on POSIX systems to enumerate processes."""
    import subprocess  # noqa: PLC0415  -- lazy import: only needed when psutil is absent

    try:
        result = subprocess.run(  # noqa: S603 -- trusted system command
            ["ps", "-A", "-o", "comm="],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _LOG.warning("Could not run ps: %s", exc)
        return []
    return [line.strip().lower() for line in result.stdout.splitlines() if line.strip()]


def is_rdr2_running() -> bool:
    """Return True if RDR2 (or the Rockstar Launcher) appears to be running.

    Best-effort: if the process list can't be determined, returns True
    (cautious — the UI should warn the user rather than silently write).
    """
    names = _get_process_names()
    if not names:
        # Can't determine — be cautious
        _LOG.warning("Could not determine process list; assuming RDR2 might be running")
        return True

    running = any(_matches_rdr2(name) for name in names)
    if running:
        _LOG.info("RDR2 or Rockstar Launcher is running")
    return running


def _matches_rdr2(process_name: str) -> bool:
    """Return True if a process name matches RDR2 or the Rockstar Launcher."""
    return process_name.lower() in _RDR2_PROCESS_NAMES


def assert_rdr2_not_running() -> None:
    """Raise RDR2RunningError if RDR2 appears to be running.

    Convenience function for callers that want the check-and-raise pattern
    rather than the check-and-warn pattern.
    """
    if is_rdr2_running():
        msg = (
            "Red Dead Redemption 2 appears to be running. "
            "Close the game before applying lobby configurations to avoid "
            "corrupting the game's configuration."
        )
        raise RDR2RunningError(msg)

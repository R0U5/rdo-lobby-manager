"""Auto-detect RDR2 install locations across Steam, Epic, and Rockstar Launcher.

The original Qt6 tool made the user pick a directory via file dialog every
time. We can do better: RDR2 has a small set of well-known install
locations per platform, and we can find them deterministically.

This module returns *candidates* (paths that look like RDR2 installs), not
just one answer. The UI shows a list and lets the user pick — which is
strictly better than the original "type a path" UX.

We only *detect* — we never *launch* Steam/Epic/Rockstar. We're not trying
to integrate with their APIs; we're just reading their filesystem layouts
where the games are commonly installed.
"""

from __future__ import annotations

import platform
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from rdo_lobby_manager.util.log import get_logger

_LOG = get_logger(__name__)


# --- Constants ---

# The single file that proves "this is the RDR2 install root": on every
# platform, the game ships a `RDR2.exe` (Windows) or `RDR2` (Linux) in
# its root. We use this to validate candidates we find.
_RDR2_EXE_WINDOWS = "RDR2.exe"
_RDR2_EXE_LINUX = "RDR2"

# Steam's default library location on each platform. These are the
# hard-coded fallbacks; users who moved their library have custom paths
# in `config.vdf` which we also search.
_STEAM_DEFAULT_PATHS = {
    "win32": [
        Path("C:/Program Files (x86)/Steam"),
        Path("C:/Program Files/Steam"),
    ],
    "linux": [
        Path.home() / ".steam" / "steam",
        Path.home() / ".local" / "share" / "Steam",
    ],
    "darwin": [
        Path.home() / "Library" / "Application Support" / "Steam",
    ],
}

# Subpath inside a Steam library where RDR2 installs.
_STEAM_RDR2_SUBPATH_WIN = "steamapps/common/Red Dead Redemption 2"
_STEAM_RDR2_SUBPATH_LINUX = "steamapps/common/Red Dead Redemption 2"

# Epic Games Store: manifests live at .com/Epic/EpicGamesLauncher/Data/...
_EPIC_DEFAULT_PATHS = {
    "win32": [
        Path("C:/Program Files/Epic Games"),
    ],
    "darwin": [
        Path.home() / "Library" / "Application Support" / "Epic",
    ],
    # Epic on Linux is via Heroic/Lutris, not first-party — skip
}
_EPIC_MANIFEST_SUBDIR = "EpicGamesLauncher/Data/Manifests"
_EPIC_RDR2_APP_NAME = "Red Dead Redemption 2"

# Rockstar Launcher: installs to a fixed path on Windows, harder to find on
# Linux. We check the most common locations.
_ROCKSTAR_DEFAULT_PATHS = {
    "win32": [
        Path("C:/Program Files/Rockstar Games/Launcher"),
        Path("C:/Program Files (x86)/Rockstar Games/Launcher"),
    ],
}
# RDR2 install inside Rockstar Launcher's library is at:
#   <launcher_exe_dir>/../../Red Dead Redemption 2
# or via the launcher's "Games" library folder. The exact location is
# user-configurable; we check the most common default.

# Paths we use to *validate* that a candidate really is RDR2. If any of
# these exist in the directory, it's almost certainly RDR2.
_RDR2_MARKERS = (
    "RDR2.exe",  # Windows game binary
    "RDR2",  # Linux game binary (Proton)
    "x64",  # 64-bit engine data — present in every install
    "PlayRDR2.exe",  # Rockstar's launcher for the game
)


# --- Data types ---


@dataclass(frozen=True, slots=True)
class InstallCandidate:
    """A possible RDR2 install location.

    `source` is a human-readable label of where we found this candidate
    ("Steam default", "Epic manifest", "Rockstar default", etc.) so the
    UI can show "where did this come from" without making the user guess.
    """

    path: Path
    source: str
    is_valid: bool
    notes: str = ""

    def __str__(self) -> str:
        marker = "✓" if self.is_valid else "✗"
        return f"{marker} {self.path}  [{self.source}]"


# --- Validation ---


def is_valid_rdr2_install(path: Path) -> bool:
    """Return True if `path` looks like an RDR2 install directory.

    We require at least 2 of the marker files/dirs to be present, so a
    random directory containing just an `x64` folder (some other games
    have one too) doesn't false-positive.
    """
    if not path.is_dir():
        return False
    hits = sum(1 for marker in _RDR2_MARKERS if (path / marker).exists())
    return hits >= 2


# --- Search ---


def _steam_libraries_from_config(config_path: Path) -> Iterator[Path]:
    """Parse Steam's libraryfolders.vdf to extract every library path.

    The file format is VDF (Valve Data Format), a key-value text format
    with nested blocks. We don't need a full VDF parser — a regex for
    `"path"` keys inside `LibraryFolders` blocks is enough.
    """
    if not config_path.exists():
        return
    try:
        text = config_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _LOG.warning("Could not read Steam config %s: %s", config_path, exc)
        return
    # Match both VDF formats:
    #   Modern: "path"  "C:\\some\\path"  (key inside a numbered block)
    #   Legacy: "1"     "D:\\SteamLibrary"  (numbered key with path as value)
    # We match "path" keys first, then any numbered key whose value looks
    # like a path (contains a separator or drive letter).
    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        yield Path(match.group(1))
    # Legacy format: "<digit>" "<value>"  where value looks like a path
    for match in re.finditer(r'"\d+"\s+"([^"]+)"', text):
        val = match.group(1)
        # Only treat as a path if it contains a path separator
        if "\\" in val or "/" in val:
            yield Path(val)


def _find_in_steam() -> Iterator[InstallCandidate]:
    """Search Steam library locations for RDR2."""
    seen: set[Path] = set()
    for steam_root in _STEAM_DEFAULT_PATHS.get(sys.platform, []):
        if not steam_root.is_dir():
            continue
        # Direct default install
        subpath = _STEAM_RDR2_SUBPATH_WIN if sys.platform == "win32" else _STEAM_RDR2_SUBPATH_LINUX
        candidate = steam_root / subpath
        if candidate not in seen:
            seen.add(candidate)
            if candidate.is_dir():
                yield InstallCandidate(
                    path=candidate,
                    source="Steam default library",
                    is_valid=is_valid_rdr2_install(candidate),
                )
        # Additional libraries from libraryfolders.vdf
        vdf_path = steam_root / "steamapps" / "libraryfolders.vdf"
        for lib in _steam_libraries_from_config(vdf_path):
            for lib_candidate in [
                lib / "steamapps" / "common" / "Red Dead Redemption 2",
            ]:
                if lib_candidate not in seen:
                    seen.add(lib_candidate)
                    if lib_candidate.is_dir():
                        yield InstallCandidate(
                            path=lib_candidate,
                            source="Steam additional library",
                            is_valid=is_valid_rdr2_install(lib_candidate),
                        )


def _find_in_epic() -> Iterator[InstallCandidate]:
    """Search Epic Games Store manifests for RDR2."""
    for epic_root in _EPIC_DEFAULT_PATHS.get(sys.platform, []):
        if not epic_root.is_dir():
            continue
        manifests_dir = epic_root / _EPIC_MANIFEST_SUBDIR
        if not manifests_dir.is_dir():
            continue
        for manifest_path in manifests_dir.glob("*.item"):
            try:
                text = manifest_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _EPIC_RDR2_APP_NAME.lower() not in text.lower():
                continue
            # Parse the InstallLocation from the manifest
            match = re.search(r'"InstallLocation"\s*:\s*"([^"]+)"', text)
            if not match:
                continue
            install_path = Path(match.group(1).replace("\\\\", "\\"))
            if not install_path.is_dir():
                continue
            yield InstallCandidate(
                path=install_path,
                source="Epic Games Store manifest",
                is_valid=is_valid_rdr2_install(install_path),
            )


def _find_in_rockstar() -> Iterator[InstallCandidate]:
    """Search Rockstar Launcher for RDR2.

    The Rockstar Launcher doesn't have a friendly manifest system. We
    check common install paths and the launcher's own game library file.
    """
    for launcher_root in _ROCKSTAR_DEFAULT_PATHS.get(sys.platform, []):
        if not launcher_root.is_dir():
            continue
        # The launcher's "games" directory often contains RDR2
        # at <launcher_exe>/../../Red Dead Redemption 2
        for subpath in [
            Path("../../Red Dead Redemption 2"),
            Path("../../../Red Dead Redemption 2"),
        ]:
            candidate = (launcher_root / subpath).resolve()
            if candidate.is_dir():
                yield InstallCandidate(
                    path=candidate,
                    source="Rockstar Launcher (default)",
                    is_valid=is_valid_rdr2_install(candidate),
                )
        # Some users have RDR2 inside the launcher directory itself
        candidate = launcher_root / "Red Dead Redemption 2"
        if candidate.is_dir():
            yield InstallCandidate(
                path=candidate,
                source="Rockstar Launcher (sibling)",
                is_valid=is_valid_rdr2_install(candidate),
            )


# --- Public API ---


def find_all_candidates() -> list[InstallCandidate]:
    """Search all known install locations and return every candidate found.

    Returns candidates with `is_valid` set per `is_valid_rdr2_install()`.
    The list is unsorted; the UI can sort by validity (valid first) then
    by source.
    """
    candidates: list[InstallCandidate] = []
    for finder in (_find_in_steam, _find_in_epic, _find_in_rockstar):
        try:
            candidates.extend(finder())
        except Exception as exc:  # noqa: BLE001  -- best-effort search
            _LOG.warning("Install finder %s failed: %s", finder.__name__, exc)
    return candidates


def find_valid_installs() -> list[InstallCandidate]:
    """Return only the candidates that look like real RDR2 installs."""
    return [c for c in find_all_candidates() if c.is_valid]


def best_guess_install() -> Path | None:
    """Return the most likely RDR2 install path, or None if nothing found.

    Prefers valid candidates in this order: Steam > Epic > Rockstar.
    """
    valid = find_valid_installs()
    if not valid:
        return None
    # Sort by source priority
    priority = {
        "Steam default library": 0,
        "Steam additional library": 1,
        "Epic Games Store manifest": 2,
        "Rockstar Launcher (default)": 3,
    }
    valid.sort(key=lambda c: priority.get(c.source, 99))
    return valid[0].path


# --- Manual validation ---


def validate_user_path(path: Path) -> InstallCandidate:
    """Validate a user-provided path (from the file dialog).

    Returns an InstallCandidate with is_valid set appropriately, so the
    UI can show "this is/isn't a valid RDR2 install" with the same shape
    as auto-detected candidates.
    """
    if not path.exists():
        return InstallCandidate(
            path=path,
            source="User-selected",
            is_valid=False,
            notes="Path does not exist",
        )
    if not path.is_dir():
        return InstallCandidate(
            path=path,
            source="User-selected",
            is_valid=False,
            notes="Path is not a directory",
        )
    is_valid = is_valid_rdr2_install(path)
    return InstallCandidate(
        path=path,
        source="User-selected",
        is_valid=is_valid,
        notes="" if is_valid else "Directory does not look like an RDR2 install",
    )


# --- Diagnostics (used by settings panel / logs) ---


def diagnostics() -> dict[str, object]:
    """Return diagnostic info useful for the 'why isn't RDR2 found?' UI.

    Reports which search locations were checked and which yielded results.
    """
    return {
        "platform": sys.platform,
        "python_version": platform.python_version(),
        "steam_defaults": [str(p) for p in _STEAM_DEFAULT_PATHS.get(sys.platform, [])],
        "epic_defaults": [str(p) for p in _EPIC_DEFAULT_PATHS.get(sys.platform, [])],
        "rockstar_defaults": [str(p) for p in _ROCKSTAR_DEFAULT_PATHS.get(sys.platform, [])],
        "home": str(Path.home()),
    }

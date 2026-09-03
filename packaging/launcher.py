"""Entry point for the packaged RDO Lobby Manager executable.

Double-clicking the .exe should just start the GUI, so this takes no arguments
and calls ``main()`` directly rather than exposing the CLI. Bundled builds
also need their data files resolved out of the PyInstaller extraction
directory, and a writable location for the encrypted key + lobby store that
is not inside that directory.

Two audiences, same entry point:

* ``python -m rdo_lobby_manager``            — dev workflow (skips this file)
* ``RdoLobbyManager.exe [--detect-install]`` — packaged build (this file)

The installer calls ``RdoLobbyManager.exe --detect-install`` from inside the
Inno Setup wizard so the existing ``domain/install_detect`` module can find
the RDR2 path on the user's machine. A bare run starts the GUI.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _bundle_dir() -> Path | None:
    """The PyInstaller extraction directory, when running from a build."""
    return Path(getattr(sys, "_MEIPASS")) if hasattr(sys, "_MEIPASS") else None


def _selftest(bundle: Path | None) -> int:
    """Report what actually made it into the bundle.

    A packaged build that cannot find its required modules still starts and
    shows a confusing import error. This prints the evidence up front so the
    failure is intelligible. Used by the installer's smoke-test path.
    """
    print(f"frozen: {bundle is not None}")
    print(f"_MEIPASS: {bundle}")
    if bundle is not None:
        # CustomTkinter ships themes + fonts as data files; if they did not
        # make it into the bundle the GUI renders as broken Tk.
        ctk_assets = bundle / "customtkinter" / "assets"
        print(f"  customtkinter/assets: {'present' if ctk_assets.is_dir() else 'MISSING'}")

    # Try the import the way the real GUI does it.
    try:
        from rdo_lobby_manager.app import AppController  # noqa: F401
        from rdo_lobby_manager.ui.main_window import MainWindow  # noqa: F401
        print("rdo_lobby_manager imports: ok")
        return 0
    except Exception as exc:  # noqa: BLE001 — selftest must report everything
        print(f"rdo_lobby_manager imports: FAILED ({type(exc).__name__}: {exc})")
        return 1


def _detect_install() -> int:
    """Print the best RDR2 install guess and exit.

    Called by the Inno Setup wizard so the existing Python module does the
    disk walk (Steam libraryfolders.vdf, Rockstar launcher, Epic) instead of
    re-implementing the search in Pascal.

    Output contract (consumed by the Inno Setup custom page):

        line 1  : best-guess install path, or empty string if none
        line 2+ : all candidates, one per line, as ``path\\tsource``
    """
    from rdo_lobby_manager.domain.install_detect import (
        best_guess_install,
        find_all_candidates,
    )
    best = best_guess_install()
    print(str(best) if best is not None else "")
    for c in find_all_candidates():
        # Tab-separated so the Inno Setup side can split on it without
        # needing to re-parse the human-readable marker.
        print(f"{c.path}\t{c.source}")
    return 0


def main() -> int:
    bundle = _bundle_dir()
    if bundle is not None:
        # The app's own config.paths.user_data_dir() already handles
        # Windows %APPDATA%, macOS, and Linux XDG. Nothing to override —
        # the writable data dir is resolved at runtime, not at module
        # import time. This block is the place to add env-driven overrides
        # later if we ever need them; today the bundle directory itself
        # only needs to be on sys.path, which PyInstaller handles.
        pass

    if "--selftest" in sys.argv:
        raise SystemExit(_selftest(bundle))
    if "--detect-install" in sys.argv:
        raise SystemExit(_detect_install())

    # Bare run, or unknown args → start the GUI.
    from rdo_lobby_manager.__main__ import main as package_main
    return package_main()


if __name__ == "__main__":
    sys.exit(main())

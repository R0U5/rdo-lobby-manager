"""Entry point for ``python -m rdo_lobby_manager``.

Wires the controller and the CustomTkinter main window together, then
runs the Tk event loop until the user closes the window.

Why this is in ``__main__.py`` instead of an executable script:
    * ``-m rdo_lobby_manager`` is the documented launch command in the README.
    * Keeping it inside the package means pyinstaller / briefcase can pick it
      up without extra config in Phase 4.
    * Side-effect imports (CustomTkinter, tkinter) stay deferred until the
      user actually runs the GUI.
"""

from __future__ import annotations

import sys


def main() -> int:
    # Lazy imports — keep tkinter out of the import graph until the GUI
    # is actually launched. Makes `rdo_lobby_manager` importable from tests
    # and from non-GUI contexts without paying the tk startup cost.
    from rdo_lobby_manager.app import AppController
    from rdo_lobby_manager.ui.main_window import MainWindow

    controller = AppController()
    window = MainWindow(controller=controller)
    try:
        window.mainloop()
    except KeyboardInterrupt:
        # Allow Ctrl+C in the terminal to exit cleanly if the GUI is
        # somehow launched without a window manager catching the close.
        window._on_close()  # noqa: SLF001  — best-effort shutdown
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
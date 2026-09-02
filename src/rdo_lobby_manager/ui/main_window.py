"""Main application window.

Uses CustomTkinter (per the locked-in design decision: dark theme, split view,
"Go Public" as a menu item). This module is the shell; individual panels
live in their own modules under `ui/`.
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from rdo_lobby_manager.app import AppController
from rdo_lobby_manager.ui.lobby_editor import LobbyEditorPanel
from rdo_lobby_manager.ui.lobby_list import LobbyListPanel
from rdo_lobby_manager.ui.status_bar import StatusBar


class MainWindow(ctk.CTk):
    """Root application window.

    Layout (split view, per design decision):
        Menu Bar: File | Lobby | Help
        ┌──────────────┬───────────────────────────┐
        │  Lobby List  │   Lobby Editor             │
        │  (left)      │   (right)                  │
        ├──────────────┴───────────────────────────┤
        │  Status Bar (color-coded indicators)    │
        └──────────────────────────────────────────┘

    The editor is an inspector — it's hidden by default and only shown
    when the user clicks Edit. The window itself resizes: starting at
    ``settings.window_width`` (list-only baseline), it grows by
    ``_EDITOR_WIDTH`` when the editor is revealed and shrinks back when
    the editor is closed.
    """

    # Editor pane's natural width — added to the baseline on show,
    # subtracted on hide. 520 px comfortably fits the form fields.
    _EDITOR_WIDTH = 520

    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self.controller = controller

        self.title("RDO Lobby Manager")
        self.geometry(
            f"{controller.settings.window_width}x{controller.settings.window_height}"
        )
        self.minsize(800, 500)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self._build_menu()

        self.grid_columnconfigure(0, weight=1, minsize=280)
        # Column 1 (editor) starts weight=0 / minsize=0 because the
        # editor is hidden on first build. _show_editor() restores its
        # weight so the editor pane gets 3/4 of the available width.
        self.grid_columnconfigure(1, weight=0, minsize=0)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        self.list_panel = LobbyListPanel(
            self,
            controller=self.controller,
            on_select=self._on_lobby_selected,
            on_create=self._on_create_lobby,
            on_delete=self._on_delete_lobby,
            on_edit=self._on_edit_lobby,
        )
        self.list_panel.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=(10, 5))

        self.editor_panel = LobbyEditorPanel(
            self,
            controller=self.controller,
            on_apply=self._on_apply_lobby,
            on_update=self._on_update_lobby,
            on_close=self._on_close_editor,
        )
        # Editor starts hidden — it's an inspector, not always-on chrome.
        # _show_editor() puts it back in the grid; _hide_editor() takes it
        # out entirely with grid_forget() so column 1 collapses and the
        # window resizes narrower.
        self._editor_visible = False
        # Don't grid() the editor at all on first build. _show_editor()
        # will do it when the user clicks Edit.

        self.status_bar = StatusBar(self, controller=self.controller)
        self.status_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))

        self._refresh_all()

    def _build_menu(self) -> None:
        """Build the native menu bar with File / Lobby / Help menus."""
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Set RDR2 Directory...", command=self._on_set_rdr2_directory)
        file_menu.add_command(label="Auto-detect RDR2 Install", command=self._on_auto_detect)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)

        lobby_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Lobby", menu=lobby_menu)
        lobby_menu.add_command(label="New Lobby", command=self._on_create_lobby)
        lobby_menu.add_command(label="Apply Selected", command=self._on_apply_lobby)
        lobby_menu.add_separator()
        # "Go Public" — per design decision, lives here as a menu item
        lobby_menu.add_command(label="Go Public (Restore Default)", command=self._on_go_public)
        lobby_menu.add_separator()
        lobby_menu.add_command(label="Clear Backup Snapshot", command=self._on_clear_backup)

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self._on_about)

    def _on_set_rdr2_directory(self) -> None:
        from tkinter import filedialog

        path = filedialog.askdirectory(title="Select RDR2 Root Directory", mustexist=True)
        if not path:
            return
        ok, msg = self.controller.set_rdr2_path(path)
        self.status_bar.show_success(msg) if ok else self.status_bar.show_error(msg)
        self._refresh_all()

    def _on_auto_detect(self) -> None:
        path = self.controller.auto_detect_path()
        if path:
            self.status_bar.show_success(f"Auto-detected RDR2 install at {path}")
        else:
            self.status_bar.show_warning(
                "Could not auto-detect an RDR2 install. Use File > Set RDR2 Directory."
            )
        self._refresh_all()

    def _on_create_lobby(self) -> None:
        from rdo_lobby_manager.ui.dialogs import NewLobbyDialog

        dialog = NewLobbyDialog(self, controller=self.controller)
        self.wait_window(dialog)
        self._refresh_all()

    def _on_lobby_selected(self, name: str) -> None:
        # Selection alone doesn't open the editor — the user must click
        # Edit. Selecting a different lobby while the editor is open
        # updates its contents in-place (already shown).
        if not name:
            self.editor_panel.clear()
            return
        if self._editor_visible:
            try:
                lobby = self.controller.get_lobby(name)
                self.editor_panel.load_lobby(lobby)
            except Exception as exc:  # noqa: BLE001
                self.status_bar.show_error(f"Could not load lobby: {exc}")
        # Otherwise selection is just a marker; nothing visible changes.

    def _on_edit_lobby(self, name: str) -> None:
        if not name:
            self.status_bar.show_warning(
                "Select a lobby first, then click Edit."
            )
            return
        try:
            lobby = self.controller.get_lobby(name)
        except Exception as exc:  # noqa: BLE001
            self.status_bar.show_error(f"Could not load lobby: {exc}")
            return
        self.editor_panel.load_lobby(lobby)
        self._show_editor()
        self.status_bar.show_info(f"Editing lobby {name!r}")

    def _on_close_editor(self) -> None:
        self._hide_editor()
        self.status_bar.show_info("Editor closed.")

    def _show_editor(self) -> None:
        if self._editor_visible:
            return
        # Restore the right-column weight and re-add the editor to the grid.
        self.grid_columnconfigure(1, weight=3)
        self.editor_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=(10, 5))
        # Grow the window by the editor's natural width. Tk doesn't
        # auto-fit a window to its content, so we resize explicitly.
        # The editor pane takes roughly _EDITOR_WIDTH pixels at its
        # comfortable size; the list side stays where the user put it.
        self._resize_window_for_editor(shown=True)
        self._editor_visible = True

    def _hide_editor(self) -> None:
        if not self._editor_visible:
            return
        # grid_forget() (not grid_remove) drops the editor from the
        # geometry manager entirely so column 1 collapses back to its
        # minsize — the right pane takes zero space when hidden.
        self.editor_panel.grid_forget()
        self.grid_columnconfigure(1, weight=0, minsize=0)
        # Shrink the window back to the list-only width.
        self._resize_window_for_editor(shown=False)
        self.editor_panel.clear()
        self._editor_visible = False

    def _resize_window_for_editor(self, *, shown: bool) -> None:
        """Adjust the window width to accommodate the editor (or not).

        The stored window_width is the *list-only* baseline. When the
        editor is shown we add a fixed _EDITOR_WIDTH; when hidden we
        strip it back off. We never shrink below the minsize.
        """
        baseline = self.controller.settings.window_width
        target = baseline + (self._EDITOR_WIDTH if shown else 0)
        # Respect the existing minsize.
        min_w = self.minsize()[0] or 800
        target = max(target, min_w)
        height = self.winfo_height() or self.controller.settings.window_height
        self.geometry(f"{target}x{height}")

    def _on_apply_lobby(self) -> None:
        lobby = self.editor_panel.get_lobby_from_form()
        if lobby is None:
            self.status_bar.show_error("Fix form errors before applying.")
            return
        ok, msg = self.controller.apply_lobby(lobby)
        if ok:
            self.status_bar.show_success(msg)
        else:
            self.status_bar.show_error(msg)
        self._refresh_all()

    def _on_update_lobby(self) -> None:
        lobby = self.editor_panel.get_lobby_from_form()
        if lobby is None:
            self.status_bar.show_error("Fix form errors before updating.")
            return
        ok, msg = self.controller.update_lobby(lobby.name, lobby.passphrase, lobby.notes)
        if ok:
            self.status_bar.show_success(msg)
        else:
            self.status_bar.show_error(msg)
        self._refresh_all()

    def _on_delete_lobby(self, name: str) -> None:
        from tkinter import messagebox

        if not messagebox.askyesno(
            "Delete Lobby",
            f"Delete lobby {name!r}? You can undo from the trash.",
            parent=self,
        ):
            return
        ok, msg, _ = self.controller.delete_lobby(name)
        self.status_bar.show_warning(msg) if ok else self.status_bar.show_error(msg)
        # If the editor was showing the just-deleted lobby, hide it
        # so the user isn't staring at a stale form.
        if self._editor_visible:
            self._hide_editor()
        self._refresh_all()

    def _on_go_public(self) -> None:
        from tkinter import messagebox

        if not messagebox.askyesno(
            "Go Public",
            "Restore the RDR2 meta file to its default (public lobby) state?",
            parent=self,
        ):
            return
        ok, msg = self.controller.go_public()
        self.status_bar.show_success(msg) if ok else self.status_bar.show_error(msg)
        self._refresh_all()

    def _on_clear_backup(self) -> None:
        from tkinter import messagebox

        if not messagebox.askyesno(
            "Clear Backup",
            "Clear the stored backup snapshot? You won't be able to restore "
            "the original game state after this.",
            parent=self,
        ):
            return
        ok, msg = self.controller.clear_backup()
        self.status_bar.show_success(msg) if ok else self.status_bar.show_error(msg)
        self._refresh_all()

    def _on_about(self) -> None:
        from tkinter import messagebox

        messagebox.showinfo(
            "About",
            "RDO Lobby Manager v2.0.0\n\n"
            "Manage Red Dead Redemption 2 private lobby configurations.\n"
            "All data is stored locally and encrypted at rest.",
            parent=self,
        )

    def _refresh_all(self) -> None:
        self.list_panel.refresh()
        self.status_bar.refresh()

    def _on_close(self) -> None:
        try:
            w = self.winfo_width()
            h = self.winfo_height()
            if w > 100 and h > 100:
                self.controller.settings.window_width = w
                self.controller.settings.window_height = h
        except Exception:  # noqa: BLE001
            pass
        self.controller.save_settings()
        self.destroy()

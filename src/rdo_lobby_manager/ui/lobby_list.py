"""Lobby list panel — left half of the main window.

Shows the saved lobby names, lets the user select one, and exposes
"New" and "Delete" buttons. All lobby loading / mutation lives in the
controller; this widget is a thin view.
"""

from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from rdo_lobby_manager.app import AppController


class LobbyListPanel(ctk.CTkFrame):
    """Scrollable list of saved lobbies + create/delete buttons.

    The panel never reads or writes lobby data itself. Every action is
    delegated to the controller, which keeps the widget testable in
    isolation (the constructor only needs a controller-shaped object).

    Callbacks (passed by the parent window):
        on_select(name):   fires when the user picks a lobby
        on_create():       fires when the New button is clicked
        on_delete(name):   fires when Delete is clicked on a selection
    """

    def __init__(
        self,
        master: ctk.CTk,
        *,
        controller: AppController,
        on_select: Callable[[str], None],
        on_create: Callable[[], None],
        on_delete: Callable[[str], None],
    ) -> None:
        super().__init__(master)
        self._controller = controller
        self._on_select = on_select
        self._on_create = on_create
        self._on_delete = on_delete

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkLabel(
            self,
            text="Saved Lobbies",
            font=ctk.CTkFont(weight="bold"),
        )
        header.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")

        self._listbox = ctk.CTkScrollableFrame(self, label_text="")
        self._listbox.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        self._listbox.grid_columnconfigure(0, weight=1)

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.grid(row=2, column=0, padx=10, pady=(5, 10), sticky="ew")
        button_row.grid_columnconfigure((0, 1), weight=1)

        self._new_button = ctk.CTkButton(
            button_row,
            text="New…",
            command=self._handle_new,
        )
        self._new_button.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        self._delete_button = ctk.CTkButton(
            button_row,
            text="Delete",
            command=self._handle_delete,
            state="disabled",
        )
        self._delete_button.grid(row=0, column=1, padx=(5, 0), sticky="ew")

        self._selected_name: str = ""
        self._rows: dict[str, ctk.CTkButton] = {}

    # --- Public API ---

    def refresh(self) -> None:
        """Reload the list from the controller and re-render.

        Preserves the previous selection if it still exists.
        """
        try:
            names = self._controller.list_lobby_names()
        except Exception as exc:  # noqa: BLE001
            # If storage is broken we still want the UI to be usable.
            names = []
            self._show_inline_error(f"Could not load lobbies: {exc}")

        previous_selection = self._selected_name
        for row in self._rows.values():
            row.destroy()
        self._rows.clear()

        for name in sorted(names, key=str.casefold):
            button = ctk.CTkButton(
                self._listbox,
                text=name,
                anchor="w",
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray75", "gray25"),
                command=lambda n=name: self._handle_select(n),
            )
            button.grid(row=len(self._rows), column=0, padx=4, pady=2, sticky="ew")
            self._rows[name] = button

        if previous_selection and previous_selection in self._rows:
            self._selected_name = previous_selection
            self._highlight_selection()
        else:
            self._selected_name = ""
            self._delete_button.configure(state="disabled")

    def selected_name(self) -> str:
        """Return the currently-selected lobby name, or empty string."""
        return self._selected_name

    # --- Internals ---

    def _handle_select(self, name: str) -> None:
        self._selected_name = name
        self._highlight_selection()
        self._delete_button.configure(state="normal")
        self._on_select(name)

    def _handle_new(self) -> None:
        self._on_create()

    def _handle_delete(self) -> None:
        if not self._selected_name:
            return
        self._on_delete(self._selected_name)

    def _highlight_selection(self) -> None:
        for name, button in self._rows.items():
            if name == self._selected_name:
                button.configure(fg_color=("gray70", "gray30"))
            else:
                button.configure(fg_color="transparent")

    def _show_inline_error(self, msg: str) -> None:
        # We don't have a label slot, so destroy-then-add a label row.
        # Cheap, only fires on error, so visual jank is acceptable.
        for child in self.grid_slaves(row=0):
            child.destroy()
        ctk.CTkLabel(
            self,
            text=msg,
            text_color=("red", "#ff6b6b"),
            wraplength=240,
        ).grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")

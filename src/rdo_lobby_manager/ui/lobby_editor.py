"""Lobby editor panel — right half of the main window.

Renders the fields for one saved lobby (name, passphrase, notes) and
exposes Apply / Update buttons. All state changes go through the
controller. The editor never reads or writes files directly.
"""

from __future__ import annotations

from collections.abc import Callable
from tkinter import StringVar

import customtkinter as ctk

from rdo_lobby_manager.app import AppController
from rdo_lobby_manager.domain.lobby import Lobby


class LobbyEditorPanel(ctk.CTkFrame):
    """Form for editing or applying one saved lobby.

    The panel is "stateless" between calls to `load_lobby`. Until
    `load_lobby` is called (or `clear` is called) the form is empty
    and Apply/Update are disabled.

    The panel is *not* shown by default. The parent window calls
    ``show()`` when the user clicks Edit and ``hide()`` when the
    panel's close button is pressed or when selection is cleared.
    """

    def __init__(
        self,
        master: ctk.CTk,
        *,
        controller: AppController,
        on_apply: Callable[[], None],
        on_update: Callable[[], None],
        on_close: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self._controller = controller
        self._on_apply = on_apply
        self._on_update = on_update
        self._on_close = on_close

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Header row: title + close button
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Lobby Editor",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        self._close_button = ctk.CTkButton(
            header,
            text="✕",
            width=28,
            command=self._on_close,
        )
        self._close_button.grid(row=0, column=1, sticky="e")

        # --- Form fields ---

        form = ctk.CTkFrame(self)
        form.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        form.grid_columnconfigure(1, weight=1)

        # Name (read-only — names are immutable identities)
        ctk.CTkLabel(form, text="Name:").grid(
            row=0, column=0, padx=10, pady=5, sticky="w"
        )
        self._name_var = StringVar(value="")
        self._name_entry = ctk.CTkEntry(
            form,
            textvariable=self._name_var,
            state="disabled",
        )
        self._name_entry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")

        # Passphrase
        ctk.CTkLabel(form, text="Passphrase:").grid(
            row=1, column=0, padx=10, pady=5, sticky="w"
        )
        self._pass_var = StringVar(value="")
        self._pass_entry = ctk.CTkEntry(
            form,
            textvariable=self._pass_var,
            show="•",
            placeholder_text="Lobby passphrase (1–256 chars)",
        )
        self._pass_entry.grid(row=1, column=1, padx=10, pady=5, sticky="ew")

        # Show/hide passphrase toggle
        self._show_pass = ctk.BooleanVar(value=False)
        self._show_checkbox = ctk.CTkCheckBox(
            form,
            text="Show passphrase",
            variable=self._show_pass,
            command=self._toggle_pass_visibility,
        )
        self._show_checkbox.grid(row=2, column=1, padx=10, pady=(0, 5), sticky="w")

        # Notes
        ctk.CTkLabel(form, text="Notes:").grid(
            row=3, column=0, padx=10, pady=(10, 5), sticky="nw"
        )
        self._notes_text = ctk.CTkTextbox(form, height=120)
        self._notes_text.grid(
            row=3, column=1, padx=10, pady=(10, 10), sticky="nsew"
        )
        form.grid_rowconfigure(3, weight=1)

        # --- Button row ---

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.grid(row=2, column=0, padx=10, pady=(5, 10), sticky="sew")
        button_row.grid_columnconfigure((0, 1), weight=1)

        self._update_button = ctk.CTkButton(
            button_row,
            text="Update Saved",
            command=self._on_update,
            state="disabled",
        )
        self._update_button.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        self._apply_button = ctk.CTkButton(
            button_row,
            text="Apply to RDR2",
            command=self._on_apply,
            state="disabled",
        )
        self._apply_button.grid(row=0, column=1, padx=(5, 0), sticky="ew")

        self._loaded_name: str = ""

    # --- Public API ---

    def load_lobby(self, lobby: Lobby) -> None:
        """Populate the form from a Lobby and enable Apply/Update."""
        self._loaded_name = lobby.name
        self._name_var.set(lobby.name)
        self._pass_var.set(lobby.passphrase)
        self._notes_text.delete("1.0", "end")
        self._notes_text.insert("1.0", lobby.notes)
        self._apply_button.configure(state="normal")
        self._update_button.configure(state="normal")

    def clear(self) -> None:
        """Empty the form and disable Apply/Update."""
        self._loaded_name = ""
        self._name_var.set("")
        self._pass_var.set("")
        self._notes_text.delete("1.0", "end")
        self._apply_button.configure(state="disabled")
        self._update_button.configure(state="disabled")

    def get_lobby_from_form(self) -> Lobby | None:
        """Return a Lobby built from the current form state.

        Returns None if the form is empty or invalid. Validation is
        delegated to the Lobby dataclass — same as everywhere else.
        """
        name = self._loaded_name
        if not name:
            return None
        passphrase = self._pass_var.get().strip()
        notes = self._notes_text.get("1.0", "end-1c")
        try:
            return Lobby(name=name, passphrase=passphrase, notes=notes)
        except Exception:  # noqa: BLE001
            # Lobby validation will raise with a clear message; we
            # surface it via the status bar from the caller.
            return None

    # --- Internals ---

    def _toggle_pass_visibility(self) -> None:
        self._pass_entry.configure(show="" if self._show_pass.get() else "•")

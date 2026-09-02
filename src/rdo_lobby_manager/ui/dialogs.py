"""Modal dialogs used by the main window.

Currently only the "New Lobby" dialog — a focused input form that
validates the name and passphrase inline before accepting. The
controller is queried for validation, the dialog itself only collects
form state.
"""

from __future__ import annotations

import customtkinter as ctk

from rdo_lobby_manager.app import AppController
from rdo_lobby_manager.domain.lobby import (
    InvalidLobbyNameError,
    InvalidPassphraseError,
    Lobby,
)


class NewLobbyDialog(ctk.CTkToplevel):
    """Modal dialog for creating a new saved lobby.

    Usage:
        dialog = NewLobbyDialog(parent, controller=controller)
        parent.wait_window(dialog)
        # After this, if dialog.result is set, the lobby was created.

    The dialog enforces:
        • Non-empty name and passphrase (Lobby.__post_init__ will reject anyway)
        • Name not already used (controller.create_lobby will reject, surfaced inline)
        • Modal: blocks parent until closed
    """

    def __init__(
        self,
        master: ctk.CTk,
        *,
        controller: AppController,
    ) -> None:
        super().__init__(master)
        self._controller = controller
        self.result: Lobby | None = None

        self.title("New Lobby")
        self.geometry("420x260")
        self.minsize(380, 240)
        self.resizable(False, False)
        self.grab_set()  # modal
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            self,
            text="Create a new saved lobby",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=0, column=0, padx=15, pady=(15, 5), sticky="w")

        ctk.CTkLabel(self, text="Name:").grid(
            row=1, column=0, padx=15, pady=(10, 0), sticky="w"
        )
        self._name_var = ctk.StringVar(value="")
        ctk.CTkEntry(
            self,
            textvariable=self._name_var,
            placeholder_text="Lobby name (letters, digits, _.-())",
        ).grid(row=2, column=0, padx=15, pady=(0, 5), sticky="ew")

        ctk.CTkLabel(self, text="Passphrase:").grid(
            row=3, column=0, padx=15, pady=(10, 0), sticky="nw"
        )
        self._pass_entry = ctk.CTkEntry(
            self,
            placeholder_text="Lobby passphrase (1–256 chars)",
            show="•",
        )
        self._pass_entry.grid(
            row=4, column=0, padx=15, pady=(0, 5), sticky="new"
        )
        # Make the entry expand to fill the row when window is resized
        self.grid_rowconfigure(4, weight=1)

        self._error_label = ctk.CTkLabel(
            self,
            text="",
            text_color=("#a40000", "#ff6b6b"),
            wraplength=380,
            justify="left",
        )
        self._error_label.grid(row=5, column=0, padx=15, pady=(5, 0), sticky="w")

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.grid(row=6, column=0, padx=15, pady=(10, 15), sticky="ew")
        button_row.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            button_row,
            text="Cancel",
            command=self._on_cancel,
        ).grid(row=0, column=0, padx=(0, 5), sticky="ew")

        ctk.CTkButton(
            button_row,
            text="Create",
            command=self._on_create,
        ).grid(row=0, column=1, padx=(5, 0), sticky="ew")

        # Focus the name field so Enter/Tab navigation works.
        self.after(50, self._focus_name)

    # --- Internals ---

    def _focus_name(self) -> None:
        # The first entry child is the Name entry; focus it.
        for child in self.winfo_children():
            if isinstance(child, ctk.CTkEntry):
                child.focus_set()
                return

    def _on_create(self) -> None:
        name = self._name_var.get().strip()
        passphrase = self._pass_entry.get()
        notes = ""  # dialog doesn't collect notes; user can edit after.

        # Build a Lobby to surface validation errors before persisting.
        try:
            lobby = Lobby(name=name, passphrase=passphrase, notes=notes)
        except InvalidLobbyNameError as exc:
            self._show_error(f"Invalid name: {exc}")
            return
        except InvalidPassphraseError as exc:
            self._show_error(f"Invalid passphrase: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            self._show_error(f"Could not create lobby: {exc}")
            return

        ok, msg = self._controller.create_lobby(
            name=lobby.name,
            passphrase=lobby.passphrase,
            notes=lobby.notes,
        )
        if not ok:
            self._show_error(msg)
            return

        self.result = lobby
        self.grab_release()
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.grab_release()
        self.destroy()

    def _show_error(self, msg: str) -> None:
        self._error_label.configure(text=msg)

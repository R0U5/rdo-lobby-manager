"""Status bar — bottom row of the main window.

Shows the current operational status (RDR2 install, lobby count,
meta-file state) plus a one-line status message that the controller
updates after every action.
"""

from __future__ import annotations

import customtkinter as ctk

from rdo_lobby_manager.app import AppController


class StatusBar(ctk.CTkFrame):
    """Color-coded status indicators + transient message line.

    Indicators (left to right):
        • RDR2 install path configured (yes/no, green/gray)
        • Saved lobby count
        • Current meta file state (private lobby / default)

    Message line: last action result. Methods `show_*` set it; it
    doesn't auto-clear because persistent feedback is more useful
    than auto-clearing feedback for an offline tool like this.
    """

    def __init__(
        self,
        master: ctk.CTk,
        *,
        controller: AppController,
    ) -> None:
        super().__init__(master)
        self._controller = controller

        self.grid_columnconfigure(0, weight=1)

        indicator_row = ctk.CTkFrame(self, fg_color="transparent")
        indicator_row.grid(row=0, column=0, padx=10, pady=(5, 0), sticky="ew")
        indicator_row.grid_columnconfigure((0, 1, 2), weight=1)

        self._install_label = ctk.CTkLabel(
            indicator_row, text="RDR2: ?", anchor="w"
        )
        self._install_label.grid(row=0, column=0, padx=5, sticky="w")

        self._lobby_count_label = ctk.CTkLabel(
            indicator_row, text="Lobbies: 0", anchor="w"
        )
        self._lobby_count_label.grid(row=0, column=1, padx=5, sticky="w")

        self._meta_label = ctk.CTkLabel(
            indicator_row, text="Meta: ?", anchor="w"
        )
        self._meta_label.grid(row=0, column=2, padx=5, sticky="w")

        self._message_label = ctk.CTkLabel(
            self,
            text="Ready.",
            anchor="w",
            text_color=("gray40", "gray60"),
            wraplength=900,
        )
        self._message_label.grid(row=1, column=0, padx=10, pady=(2, 5), sticky="ew")

    # --- Public API ---

    def refresh(self) -> None:
        """Re-pull the controller's status dict and update indicators."""
        status = self._controller.get_status()

        # RDR2 install
        if status["rdr2_configured"]:
            path = status["rdr2_path"]
            display = path if len(path) <= 60 else f"…{path[-57:]}"
            self._install_label.configure(
                text=f"RDR2: {display}",
                text_color=("#1f7a1f", "#7fe57f"),
            )
        else:
            self._install_label.configure(
                text="RDR2: not configured",
                text_color=("gray50", "gray60"),
            )

        # Lobby count
        count = status["lobby_count"]
        self._lobby_count_label.configure(
            text=f"Lobbies: {count}",
            text_color=("gray10", "gray90"),
        )

        # Meta file state
        if status["rdr2_configured"]:
            if status["meta_has_lobby"]:
                self._meta_label.configure(
                    text="Meta: private lobby active",
                    text_color=("#8a4b00", "#ffb84d"),
                )
            elif status["meta_is_default"]:
                self._meta_label.configure(
                    text="Meta: public (default)",
                    text_color=("#1f7a1f", "#7fe57f"),
                )
            else:
                self._meta_label.configure(
                    text="Meta: unknown state",
                    text_color=("gray50", "gray60"),
                )
        else:
            self._meta_label.configure(
                text="Meta: —",
                text_color=("gray50", "gray60"),
            )

    # --- Message helpers ---

    def show_info(self, msg: str) -> None:
        self._message_label.configure(text=msg, text_color=("gray10", "gray90"))

    def show_success(self, msg: str) -> None:
        self._message_label.configure(
            text=msg, text_color=("#1f7a1f", "#7fe57f")
        )

    def show_warning(self, msg: str) -> None:
        self._message_label.configure(
            text=msg, text_color=("#8a4b00", "#ffb84d")
        )

    def show_error(self, msg: str) -> None:
        self._message_label.configure(
            text=msg, text_color=("#a40000", "#ff6b6b")
        )

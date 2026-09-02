# RDO Lobby Manager

Manage Red Dead Redemption 2 **private-lobby** configurations by editing the
game's `x64/data/startup.meta` file. CustomTkinter UI, encrypted passphrase
storage, atomic writes, and atomic backups.

This is **v2** — a complete Python rewrite of the original C++/Qt6 tool, with
all known bugs from the decompiled original eliminated by construction.

---

## Features

- **Per-lobby encrypted storage.** Passphrases are Fernet-encrypted at rest
  with a key derived from your OS user. No plaintext on disk.
- **Atomic writes.** Config files and meta-file patches are written to a temp
  file and renamed into place. A crash mid-write can never corrupt state.
- **Safe backups.** The original `startup.meta` is snapshotted before the
  first lobby is applied; restore via the **Lobby → Go Public (Restore Default)**
  menu item.
- **Crash-resilient delete.** Deleted lobbies go to a trash directory so an
  accidental delete can be undone.
- **Validated domain.** Lobby names are normalized against a strict character
  set; passphrases are length-bounded to what RAGE actually accepts.
- **264 tests.** Domain logic, storage, crypto, migrations, and the app
  controller are all unit-tested.

## What it is **not**

- Not a multiplayer mod. It edits a config file that the *existing* RDO
  matchmaking reads at launch. RDO itself is the network — this tool just
  points your game at the lobby you want.
- Not a public-release tool. Target user is "person who owns RDR2 on PC and
  wants to join a specific friend's private lobby without typing the password
  into the game's broken on-screen keyboard."

## Requirements

- Python 3.12+
- Windows (RDR2's `startup.meta` is a Windows-specific layout)
- A legitimate RDR2 PC install

## Install

```sh
git clone https://github.com/R0U5/rdo-lobby-manager.git
cd rdo-lobby-manager
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .
```

## Run

```sh
python -m rdo_lobby_manager
```

On first launch:

1. **File → Set RDR2 Directory...** (or **Auto-detect RDR2 Install**).
2. **Lobby → New Lobby...** to create your first saved lobby.
3. Select the lobby in the list, then **Apply to RDR2**.
4. Launch RDR2 — it'll join the private lobby.

To go back to public matchmaking: **Lobby → Go Public (Restore Default)**.

## Development

```sh
pip install -e ".[dev]"
pytest                    # 264 tests
ruff check src/           # lint
ruff format src/          # format
```

## Architecture

```
src/rdo_lobby_manager/
├── app.py              # Application controller — glue between domain/storage/UI
├── config/             # Paths, crypto (Fernet)
├── domain/             # Lobby, model, meta-file parser, install detection
├── storage/            # Lobby store, migrations, error types
├── util/               # Atomic write, backup, logging, process check
└── ui/                 # CustomTkinter panels (main window, list, editor, status, dialogs)
```

- **Domain layer** has zero filesystem or UI imports. Pure Python, easy to test.
- **Storage layer** wraps the domain in atomic-file semantics.
- **App controller** is a thin orchestrator that the UI talks to.
- **UI layer** never reads/writes files directly.

## Bug history

The original Qt6 tool had 23 documented bugs (B1–B23): overwriting backups,
plaintext passphrases, partial-write corruption on Ctrl+C, CRLF/LF mismatches,
Windows-reserved filenames accepted, etc. **All 23 are eliminated by
construction in v2.** The bug inventory lives in the decompilation notes
captured during the v2 design phase; see `docs/` (forthcoming).

## License

MIT.
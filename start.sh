#!/usr/bin/env sh
# One-command start for macOS and Linux. Sets itself up on first run.
#
# Windows users have Install.bat + Start RDO Lobby Manager.bat. RDR2 itself
# is Windows-only, so this script is here for symmetry and for future use
# (e.g. running the lobby store / domain logic headless on a server).
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
    echo
    echo "  Setting up for the first time..."
    echo
    PY=$(command -v python3 || command -v python || true)
    if [ -z "$PY" ]; then
        echo "  Python 3.12+ is not installed. Install it, then run this again:"
        echo "    macOS:  brew install python@3.12"
        echo "    Ubuntu: sudo apt install python3.12 python3.12-venv"
        exit 1
    fi
    "$PY" -m venv .venv
    .venv/bin/python -m pip install --upgrade pip --quiet
    .venv/bin/python -m pip install -e . --quiet
fi

exec .venv/bin/rdo-lobby-manager "$@"

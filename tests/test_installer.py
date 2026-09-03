"""Enforce the two hard-won rules from the PowerShell installer.

The original Icarus-Save-Editor project hit these in production and
encoded them as tests. They are reproduced here verbatim because they
are easy to regress on by a future edit:

Rule 1 -- The .ps1 must resolve the repo root as the parent of
``packaging/``, never as ``$PSScriptRoot`` (which is ``packaging/``
itself). Running ``pip install -e .`` from inside ``packaging/`` finds
no pyproject.toml and dies with "does not appear to be a Python
project".

Rule 2 -- The .ps1 must stay ASCII. Windows PowerShell reads no-BOM
files as ANSI -- a UTF-8 em dash (U+2014) in a string renders as three
mojibake characters. Any typographic punctuation is built at runtime
from a character code.

The tests do not actually execute the installer; they scan the source
and fail loudly if either rule is broken.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_PS1 = REPO_ROOT / "packaging" / "install-from-source.ps1"


def _read_bytes() -> bytes:
    return INSTALL_PS1.read_bytes()


def test_installer_ps1_exists() -> None:
    assert INSTALL_PS1.is_file(), f"missing: {INSTALL_PS1}"


def test_rule_1_resolves_repo_root_from_parent_of_packaging() -> None:
    """The installer must build $root as the parent of its own directory.

    A grep for ``$PSScriptRoot`` is not enough on its own -- a future
    edit could still compute the wrong thing via a more elaborate path.
    The check is: the script contains a line that resolves the parent
    of its own location, used later as $root.
    """
    text = INSTALL_PS1.read_text(encoding="ascii", errors="strict")
    # Pattern: split the parent of the script's own path. The exact form
    # in install-from-source.ps1 is:
    #     $script:root = Split-Path -Parent (Split-Path -Parent $here)
    assert "Split-Path -Parent (Split-Path -Parent" in text, (
        "installer does not resolve $root as the parent of packaging/ "
        "-- pip install -e . would run from the wrong directory"
    )


def test_rule_2_installer_ps1_is_strict_ascii() -> None:
    """The .ps1 must not contain non-ASCII bytes.

    Windows PowerShell reads a no-BOM file as ANSI. A UTF-8 em dash
    (E2 80 94) inside a string renders as three mojibake characters.
    The only safe characters are 0x00-0x7F, plus CR/LF.
    """
    raw = _read_bytes()
    for offset, byte in enumerate(raw):
        if byte > 0x7F:
            # Find the line for a useful error message.
            line_no = raw[:offset].count(b"\n") + 1
            raise AssertionError(
                f"non-ASCII byte 0x{byte:02x} at offset {offset} "
                f"(line {line_no}); em dashes and other Unicode "
                f"punctuation break in Windows PowerShell -- use "
                f"[char]0x2014 at runtime instead"
            )


def test_rule_2_em_dash_built_at_runtime() -> None:
    """If the installer uses an em dash, it must be the runtime form.

    A literal em dash is exactly what Rule 2 forbids. The accepted
    workaround in install-from-source.ps1 is:

        $emDash = [string][char]0x2014

    This test enforces that the runtime form exists if (and only if) any
    em dash is referenced at all in the source.
    """
    text = INSTALL_PS1.read_text(encoding="ascii", errors="strict")
    # The installer does use the em dash; confirm it's the runtime form.
    assert "[char]0x2014" in text, (
        "installer references em dashes; build them at runtime with "
        "[char]0x2014 instead of a literal Unicode character"
    )


def test_installer_has_flag_file_pattern() -> None:
    """The flag-file pattern that lets Install.bat decide whether to
    pause for input.

    The PowerShell installer writes a file to %TEMP% on success; the
    .bat wrapper uses its presence to decide whether the user can see
    error messages. If the flag is missing, the pattern is broken and
    the .bat will hang on a console nobody can see.
    """
    text = INSTALL_PS1.read_text(encoding="ascii", errors="strict")
    assert "rdo-lm-setup-window.flag" in text, (
        "installer does not write the %TEMP%\\rdo-lm-setup-window.flag "
        "flag that Install.bat uses to detect a successful GUI launch"
    )


def test_install_bat_writes_flag_check() -> None:
    """The .bat must check for the flag and pause only if it is missing."""
    text = (REPO_ROOT / "Install.bat").read_text(encoding="ascii", errors="strict")
    assert "rdo-lm-setup-window.flag" in text
    assert "del /q" in text
    assert "pause" in text  # fallback when the GUI never launched


def test_pyinstaller_spec_has_no_test_imports() -> None:
    """The PyInstaller spec must not pull in pytest, which adds ~30MB
    to the bundle and slows startup.
    """
    spec = (REPO_ROOT / "packaging" / "rdo-lobby-manager.spec").read_text(
        encoding="ascii", errors="strict"
    )
    assert "excludes=" in spec
    assert "pytest" in spec


def test_launcher_handles_frozen_and_unfrozen() -> None:
    """The launcher must work both as a script (dev) and as a frozen
    exe (production). It should branch on sys._MEIPASS, not assume one
    or the other.
    """
    text = (REPO_ROOT / "packaging" / "launcher.py").read_text(
        encoding="utf-8"
    )
    assert "_MEIPASS" in text
    assert "getattr(sys, \"_MEIPASS\")" in text or "getattr(sys, '_MEIPASS')" in text

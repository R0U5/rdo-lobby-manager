# PyInstaller spec for rdo-lobby-manager.
#
# Builds a single RdoLobbyManager.exe that runs with no Python on the
# target machine. CustomTkinter ships JSON themes + TrueType fonts as data
# files that PyInstaller's static analysis never sees, so they must be listed
# explicitly in `datas` or the bundled GUI renders as broken Tk.
#
# Build order:
#
#     pyinstaller packaging/rdo-lobby-manager.spec --noconfirm --clean
#     iscc packaging/rdo-lobby-manager.iss /DMyAppVersion=x.y.z
#
# CI does both in .github/workflows/build-windows.yml.

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# CustomTkinter's runtime resolution scans these from the package directory.
# PyInstaller's static analysis ignores non-Python files, so we add them.
ctk_datas = collect_data_files("customtkinter", includes=["assets/**"])

# cryptography ships Rust-built OpenSSL bindings; PyInstaller usually finds
# them via binary analysis, but listing explicitly avoids surprises when
# building on a machine where the Rust toolchain is in a non-standard path.
crypto_binaries = collect_data_files("cryptography", includes=["**/*.so", "**/*.pyd", "**/*.dll"])

datas = ctk_datas

# CustomTkinter picks its asset paths at import time; cryptography loads
# its native bindings at import time. PyInstaller's static analysis may
# miss either, so enumerate their submodules.
hiddenimports = (
    collect_submodules("rdo_lobby_manager")
    + collect_submodules("customtkinter")
    + [
        "cryptography.hazmat.bindings._rust",
        "cryptography.hazmat.bindings.openssl.binding",
    ]
)

a = Analysis(
    ["launcher.py"],
    pathex=["../src"],
    binaries=crypto_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "tkinter.test"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="RdoLobbyManager",
    debug=False,
    strip=False,
    upx=False,
    # Keep the console: the Inno Setup wizard runs the exe with
    # --detect-install and parses stdout, and a silent failure on a
    # hobby tool is worse than a visible one for the audience this is
    # for. The GUI itself does not write to the console.
    console=True,
    icon=None,
)

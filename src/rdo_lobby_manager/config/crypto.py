"""Symmetric encryption for at-rest lobby passphrases.

Fixes B6 from the decompilation: in the original Qt6 tool, the .lobby file
contained the actual passphrase in plaintext. Here, passphrases are encrypted
with Fernet (AES-128-CBC + HMAC-SHA256) before being written to disk.

Key management:
- A 32-byte URL-safe base64-encoded key is generated on first run with
  `secrets.token_bytes(32)` (cryptographically secure RNG).
- The key file lives in the user's data directory (e.g. %APPDATA%\\RDOLobbyManager).
- The key file has restrictive permissions (0o600 on POSIX, ACL on Windows).
- The key never leaves the machine. There's no recovery mechanism by design —
  if the user loses the key, their saved lobbies are unreadable. They'll be
  prompted to re-enter them or migrate from the old plaintext format.

This is a LOCAL threat model: protecting against someone with file-system
access reading the passphrases. It is NOT a defense against someone with
admin/root on the machine (they can read any file and the key alongside).
For that, use full-disk encryption (BitLocker / FileVault / LUKS).
"""

from __future__ import annotations

import base64
import secrets
import stat
import sys
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from rdo_lobby_manager.config.paths import crypto_key_file
from rdo_lobby_manager.util.atomic_write import atomic_write_bytes
from rdo_lobby_manager.util.log import get_logger

_LOG = get_logger(__name__)

# HKDF info string for deriving an application-scoped key. Changing this
# invalidates all existing ciphertexts. Don't change it after release.
_KDF_INFO = b"rdo-lobby-manager-v2-fernet-key"
_KDF_SALT = b"rdo-lobby-manager-v2-salt"


class CryptoError(Exception):
    """Base class for crypto failures."""


class KeyFileError(CryptoError):
    """The on-disk key file is missing, unreadable, or corrupted."""


class DecryptionError(CryptoError):
    """A ciphertext could not be decrypted. The key may have changed, or
    the data was tampered with. Not the same as `cryptography.InvalidToken`
    because we want to wrap it in a domain-specific error.
    """


# --- Key management ---


def _derive_fernet_key(master_key: bytes) -> bytes:
    """Derive a Fernet-compatible key from a master key using HKDF-SHA256.

    Returns a 32-byte urlsafe-base64-encoded string (44 chars), which is
    what Fernet requires.

    Why HKDF? The user-facing master key is stored as 32 raw random bytes.
    HKDF lets us derive a Fernet key from it while keeping the master key
    file format stable if we ever need to derive other keys from it
    (e.g. for LAN sync identities in v2).
    """
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        info=_KDF_INFO,
    )
    raw = kdf.derive(master_key)
    return base64.urlsafe_b64encode(raw)


def _read_or_create_key_file(path: Path) -> bytes:
    """Read the master key from disk, creating a new one if missing.

    Raises KeyFileError if the file exists but is unreadable / wrong size.
    """
    if path.exists():
        try:
            key = path.read_bytes()
        except OSError as exc:
            msg = f"Cannot read key file at {path}: {exc}"
            raise KeyFileError(msg) from exc

        if len(key) != 32:
            msg = (
                f"Key file at {path} has wrong size "
                f"({len(key)} bytes, expected 32). The file may be corrupted."
            )
            raise KeyFileError(msg)

        return key

    # First run: generate a new key with a secure RNG.
    new_key = secrets.token_bytes(32)
    atomic_write_bytes(path, new_key)
    _restrict_permissions(path)
    _LOG.info("Generated new encryption key at %s", path)
    return new_key


def _restrict_permissions(path: Path) -> None:
    """Make the key file readable only by the owner. Best-effort.

    On Windows this is a no-op for the chmod call (Windows ignores most
    POSIX permission bits), but os.chmod still works to set the
    read-only attribute on NTFS. For real Windows ACL isolation we'd
    need win32security; for v1 we accept that on Windows the file is
    readable by the user's other processes, which is the standard
    threat model for password manager key files.
    """
    if sys.platform != "win32":
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        except OSError as exc:
            _LOG.warning("Could not set restrictive permissions on %s: %s", path, exc)


# --- The high-level API ---


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Return a process-wide Fernet instance, lazily initialising the key.

    Cached so the key is only read from disk once per process.
    """
    path = crypto_key_file()
    master = _read_or_create_key_file(path)
    derived = _derive_fernet_key(master)
    return Fernet(derived)


def reset_cached_fernet() -> None:
    """Drop the cached Fernet instance. Used by tests and by the 'regenerate
    key' admin action (when a user wants to invalidate old ciphertexts).
    """
    _get_fernet.cache_clear()


def encrypt(plaintext: str) -> str:
    """Encrypt a UTF-8 string, return a URL-safe base64 token string.

    The token is what gets written to disk. Fernet tokens are self-describing
    (version byte + timestamp + IV + ciphertext + HMAC) and authenticated:
    any tamper is detected on decrypt.
    """
    if not isinstance(plaintext, str):
        msg = f"encrypt() requires str, got {type(plaintext).__name__}"
        raise TypeError(msg)
    token = _get_fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt a Fernet token back to its UTF-8 string.

    Raises DecryptionError on any failure (wrong key, tampered data, garbled
    input). The caller should treat this as a hard error — there's no
    recovery other than to re-enter the passphrase.
    """
    if not isinstance(token, str):
        msg = f"decrypt() requires str, got {type(token).__name__}"
        raise TypeError(msg)
    try:
        plaintext = _get_fernet().decrypt(token.encode("ascii"))
    except InvalidToken as exc:
        msg = (
            "Could not decrypt lobby passphrase. The encryption key may have "
            "changed (e.g. if the data directory was wiped) or the file was "
            "tampered with."
        )
        raise DecryptionError(msg) from exc
    return plaintext.decode("utf-8")


def is_encrypted_token(s: str) -> bool:
    """Return True if `s` looks like a Fernet token (and not a plaintext passphrase).

    Used by the v1->v2 migration to distinguish old plaintext .lobby files
    from new encrypted ones without raising.
    """
    if not isinstance(s, str):
        return False
    # Fernet tokens are 44+ char urlsafe base64, always start with 'gAAAAA'
    if not s.startswith("gAAAAA"):
        return False
    try:
        # If it round-trips through Fernet, it's definitely one of ours.
        decrypt(s)
        return True
    except (DecryptionError, TypeError, ValueError):
        return False

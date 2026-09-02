"""Tests for config/crypto.py — verify encryption, decryption, key management."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from rdo_lobby_manager.config.crypto import (
    DecryptionError,
    KeyFileError,
    decrypt,
    encrypt,
    is_encrypted_token,
    reset_cached_fernet,
)


@pytest.fixture(autouse=True)
def _reset_fernet_cache():
    """Reset the Fernet cache before and after each test.

    Crypto tests use a fresh key file per test (via isolated_data_dir) and
    a cached Fernet from a previous test would be stale.
    """
    reset_cached_fernet()
    yield
    reset_cached_fernet()


class TestEncryptDecrypt:
    def test_round_trip(self, isolated_data_dir: Path):
        ct = encrypt("hello world")
        assert ct != "hello world"  # actually encrypted
        assert decrypt(ct) == "hello world"

    def test_encrypt_handles_unicode(self, isolated_data_dir: Path):
        original = "pässwörd🔑私密"
        ct = encrypt(original)
        assert decrypt(ct) == original

    def test_encrypt_handles_long_string(self, isolated_data_dir: Path):
        # 10KB passphrase
        original = "x" * 10_000
        assert decrypt(encrypt(original)) == original

    def test_encrypt_handles_empty(self, isolated_data_dir: Path):
        # Empty string encryption is allowed (though our Lobby rejects it)
        ct = encrypt("")
        assert decrypt(ct) == ""

    def test_ciphertext_differs_each_call(self, isolated_data_dir: Path):
        """Fernet includes a random IV, so the same plaintext encrypts to
        different ciphertexts each time."""
        a = encrypt("same")
        b = encrypt("same")
        assert a != b
        # But both decrypt to the same value
        assert decrypt(a) == decrypt(b) == "same"

    def test_rejects_non_string_plaintext(self, isolated_data_dir: Path):
        with pytest.raises(TypeError, match="requires str"):
            encrypt(b"bytes")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="requires str"):
            encrypt(123)  # type: ignore[arg-type]

    def test_rejects_non_string_token(self, isolated_data_dir: Path):
        with pytest.raises(TypeError, match="requires str"):
            decrypt(b"bytes")  # type: ignore[arg-type]


class TestTamperDetection:
    def test_modified_ciphertext_fails(self, isolated_data_dir: Path):
        """Flip a bit in the ciphertext; Fernet's HMAC catches it."""
        ct = encrypt("important")
        # Tamper: change a character in the middle of the token
        replacement = "B" if ct[10] == "A" else "A"
        tampered = ct[:10] + replacement + ct[11:]
        with pytest.raises(DecryptionError):
            decrypt(tampered)

    def test_truncated_ciphertext_fails(self, isolated_data_dir: Path):
        ct = encrypt("important")
        with pytest.raises(DecryptionError):
            decrypt(ct[: len(ct) // 2])

    def test_garbage_input_fails(self, isolated_data_dir: Path):
        with pytest.raises(DecryptionError):
            decrypt("not a real fernet token at all")


class TestKeyManagement:
    def test_creates_key_file_on_first_use(self, isolated_data_dir: Path):
        from rdo_lobby_manager.config.paths import crypto_key_file

        key_path = crypto_key_file()
        assert not key_path.exists()
        encrypt("first call")
        assert key_path.exists()
        assert key_path.stat().st_size == 32  # 32 raw bytes

    def test_reuses_existing_key(self, isolated_data_dir: Path):
        """Two encrypt() calls use the same key, so cross-call decrypt works."""
        ct1 = encrypt("a")
        reset_cached_fernet()  # force reload
        ct2 = encrypt("b")
        assert decrypt(ct1) == "a"
        assert decrypt(ct2) == "b"

    def test_different_keys_cant_decrypt(self, isolated_data_dir: Path):
        """If the key file changes, old ciphertexts become unreadable.

        This is the expected behavior: key rotation invalidates old data,
        forcing the user to re-enter. We document this; we don't try to
        silently recover.
        """
        from rdo_lobby_manager.config.paths import crypto_key_file

        key_path = crypto_key_file()
        ct = encrypt("old secret")

        # Replace the key with a different one
        import secrets

        new_key = secrets.token_bytes(32)
        key_path.write_bytes(new_key)
        reset_cached_fernet()

        with pytest.raises(DecryptionError):
            decrypt(ct)

    def test_corrupted_key_file_raises(self, isolated_data_dir: Path):
        from rdo_lobby_manager.config.paths import crypto_key_file

        key_path = crypto_key_file()
        key_path.write_bytes(b"too short")
        reset_cached_fernet()

        with pytest.raises(KeyFileError, match="wrong size"):
            encrypt("anything")

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions only")
    def test_key_file_permissions_restricted(self, isolated_data_dir: Path):
        """On POSIX, the key file should be 0o600 after creation."""
        from rdo_lobby_manager.config.paths import crypto_key_file

        encrypt("trigger key creation")
        mode = crypto_key_file().stat().st_mode
        # Mask out file-type bits and check the permission bits
        perms = stat.S_IMODE(mode)
        assert perms == stat.S_IRUSR | stat.S_IWUSR  # 0o600


class TestIsEncryptedToken:
    def test_recognises_real_token(self, isolated_data_dir: Path):
        ct = encrypt("anything")
        assert is_encrypted_token(ct) is True

    def test_rejects_plaintext(self, isolated_data_dir: Path):
        """A plaintext passphrase is not a Fernet token."""
        assert is_encrypted_token("hunter2") is False
        assert is_encrypted_token("MyPlaintextPass") is False
        assert is_encrypted_token("") is False

    def test_rejects_garbage(self, isolated_data_dir: Path):
        assert is_encrypted_token("gAAAAABlobberish") is False
        assert is_encrypted_token("not a token") is False

    def test_rejects_non_string(self, isolated_data_dir: Path):
        assert is_encrypted_token(None) is False  # type: ignore[arg-type]
        assert is_encrypted_token(b"bytes") is False  # type: ignore[arg-type]

    def test_distinguishes_legacy_v1_passphrase(self, isolated_data_dir: Path):
        """A v1 .lobby file would have `pass=actualcodehere`. We need to
        NOT mis-identify that as an encrypted token."""
        assert is_encrypted_token("actualcodehere") is False
        assert is_encrypted_token("hunter2") is False
        assert is_encrypted_token("abc123") is False


class TestSecurityProperties:
    def test_ciphertext_does_not_contain_plaintext(self, isolated_data_dir: Path):
        """The plaintext must not appear in the ciphertext."""
        plaintext = "thisIsMySecretPassphrase123"
        ct = encrypt(plaintext)
        assert plaintext not in ct

    def test_different_fernet_keys_produce_different_ciphertexts(self, isolated_data_dir: Path):
        """Sanity check: rotating the on-disk key changes the ciphertext."""
        from rdo_lobby_manager.config.paths import crypto_key_file

        ct1 = encrypt("same plaintext")

        # Replace the key file with a different random one
        import secrets

        new_key = secrets.token_bytes(32)
        crypto_key_file().write_bytes(new_key)
        reset_cached_fernet()

        ct2 = encrypt("same plaintext")
        assert ct1 != ct2

"""AES-256-GCM sealing: one opaque blob per value (nonce + ciphertext)."""

import base64
import secrets
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_LEN = 32
NONCE_LEN = 12


class EncryptionError(Exception):
    pass


class Cipher:
    """Sealing keyed by a 32-byte key. A sealed value is ONE blob, so it
    fits a single column and can never be half-persisted."""

    def __init__(self, key: bytes) -> None:
        """Raises EncryptionError on a key of the wrong length."""
        if len(key) != KEY_LEN:
            raise EncryptionError(f"key is {len(key)} bytes, want {KEY_LEN}")
        self._aead = AESGCM(key)

    def seal(self, plaintext: bytes) -> bytes:
        nonce = secrets.token_bytes(NONCE_LEN)
        return nonce + self._aead.encrypt(nonce, plaintext, None)

    def unseal(self, sealed: bytes) -> bytes:
        """Raises ValueError/InvalidTag when the blob will not open."""
        if len(sealed) < NONCE_LEN:
            raise ValueError("sealed value is too short to hold a nonce")
        return self._aead.decrypt(sealed[:NONCE_LEN], sealed[NONCE_LEN:], None)


class PlainCipher(Cipher):
    """Passthrough for encryption off: content stored as readable plain
    text; the database opens in any sqlite browser."""

    def __init__(self) -> None:
        super().__init__(b"\x00" * KEY_LEN)

    def seal(self, plaintext: bytes) -> bytes:
        return plaintext

    def unseal(self, sealed: bytes) -> bytes:
        return sealed


def wrap_key(key: bytes, wrapping_key: bytes) -> dict[str, str]:
    """`key` sealed under `wrapping_key`, as the keystore stores it
    (base64 fields)."""
    nonce = secrets.token_bytes(NONCE_LEN)
    wrapped = AESGCM(wrapping_key).encrypt(nonce, key, None)
    return {
        "wrapped_dek": base64.b64encode(wrapped).decode(),
        "nonce": base64.b64encode(nonce).decode(),
    }


def unwrap_key(slot: dict[str, Any], wrapping_key: bytes) -> bytes:
    """The wrapped key back out of a keystore slot. Raises the aead's own
    errors (InvalidTag/ValueError/KeyError) for the caller to curate."""
    wrapped = base64.b64decode(slot["wrapped_dek"])
    nonce = base64.b64decode(slot["nonce"])
    return AESGCM(wrapping_key).decrypt(nonce, wrapped, None)

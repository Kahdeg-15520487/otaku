"""PLANE 2 — the KEYS cipher: api keys encrypted inside providers.toml.

A sealed value is `sealed:` + base64 under a 32-byte sealing key that
never sits beside the config: the OS keychain, or the given key file
where no keychain tool exists (an existing key, wherever it is, is
always reused). Wholly separate from the data plane (`crypto.data`):
encryption off leaves api keys sealed all the same, and neither plane
can read the other's key material.
"""

import base64
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from otaku2.encryption._primitives import keychain, keyfile
from otaku2.encryption._primitives.aead import KEY_LEN, NONCE_LEN, EncryptionError

_PREFIX = "sealed:"
_ACCOUNT = "config"  # the keychain account; the data plane's KEK uses "kek"


class SealedError(Exception):
    pass


def is_sealed(value: str) -> bool:
    """Whether a config value is a sealed token rather than plain text."""
    return value.startswith(_PREFIX)


def seal(value: str, *, key_file: Path, service: str) -> str:
    """`value` as a sealed token, minting the sealing key on first use
    (keychain under `service` when available, else `key_file`). A value
    that is already sealed comes back unchanged. Raises SealedError when
    the key can be neither found nor created."""
    if is_sealed(value):
        return value
    key = _load_key(key_file=key_file, service=service, create=True)
    if key is None:
        raise SealedError("no sealing key and no way to create one")
    nonce = secrets.token_bytes(NONCE_LEN)
    blob = nonce + AESGCM(key).encrypt(nonce, value.encode(), None)
    return _PREFIX + base64.b64encode(blob).decode()


def unseal(value: str, *, key_file: Path, service: str) -> str:
    """The plain text behind a sealed token (plain text passes through).
    Raises SealedError when the key is gone or the token will not open."""
    if not is_sealed(value):
        return value
    key = _load_key(key_file=key_file, service=service, create=False)
    if key is None:
        raise SealedError("the sealing key is in neither the OS keychain nor the key file")
    try:
        blob = base64.b64decode(value[len(_PREFIX) :], validate=True)
        if len(blob) < NONCE_LEN:
            raise ValueError("token too short to hold a nonce")
        return AESGCM(key).decrypt(blob[:NONCE_LEN], blob[NONCE_LEN:], None).decode()
    except Exception as e:
        raise SealedError("the sealed value does not decrypt with the sealing key") from e


def _load_key(*, key_file: Path, service: str, create: bool) -> bytes | None:
    """The sealing key: the on-disk file when it exists, else the OS
    keychain — minted there on first `create` when a keychain tool is
    available, in the file otherwise. None when absent and not creating,
    or when there is nowhere to create it."""
    if key_file.exists():
        try:
            return keyfile.read(key_file, KEY_LEN)
        except EncryptionError as e:
            raise SealedError(str(e)) from e
    if keychain.available():
        try:
            found = keychain.get(service, _ACCOUNT)
        except EncryptionError as e:
            raise SealedError(str(e)) from e
        if found is not None or not create:
            return found
        minted = secrets.token_bytes(KEY_LEN)
        try:
            keychain.put(service, _ACCOUNT, minted)
        except EncryptionError as e:
            raise SealedError(str(e)) from e
        return minted
    if not create:
        return None
    return keyfile.create(key_file, KEY_LEN)

"""A key in a file: born 0600 via exclusive create, never a moment (or a
crash residue) at umask permissions."""

import os
import secrets
from pathlib import Path

from otaku.encryption._primitives.aead import EncryptionError


def read(path: Path, length: int) -> bytes:
    """The key bytes. Raises EncryptionError on a file of the wrong length."""
    key = path.read_bytes()
    if len(key) != length:
        raise EncryptionError(f"{path}: expected {length} bytes, found {len(key)}")
    return key


def create(path: Path, length: int) -> bytes:
    """Mint `length` random bytes into a fresh 0600 file (its dir made
    0700) and return them. Raises FileExistsError when the file already
    exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    key = secrets.token_bytes(length)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


def read_or_create(path: Path, length: int) -> bytes:
    if path.exists():
        return read(path, length)
    return create(path, length)

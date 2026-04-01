"""Field-level encryption for sensitive session data.

Uses Fernet symmetric encryption derived from the application SECRET_KEY.
Provides file-level encryption at rest and password-based export encryption.
"""

import base64
import hashlib
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.constants import PBKDF2_SALT_LENGTH

logger = logging.getLogger(__name__)

#: Field name substrings that indicate sensitive data.
SENSITIVE_KEYS = ("password", "secret", "token", "credential", "api_key")


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a Fernet-compatible key (32 bytes, url-safe base64) from *secret*."""
    raw = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(raw)


def encrypt_field(data: str, secret: str) -> str:
    """Encrypt *data* and return a Fernet token string."""
    f = Fernet(_derive_fernet_key(secret))
    return f.encrypt(data.encode("utf-8")).decode("ascii")


def decrypt_field(encrypted_data: str, secret: str) -> str:
    """Decrypt a Fernet token back to the original string."""
    f = Fernet(_derive_fernet_key(secret))
    return f.decrypt(encrypted_data.encode("ascii")).decode("utf-8")


def is_sensitive_key(key: str) -> bool:
    """Return *True* if *key* looks like it holds sensitive data."""
    lower = key.lower()
    return any(s in lower for s in SENSITIVE_KEYS)


def encrypt_sensitive_fields(data: dict, secret: str) -> dict:
    """Return a shallow copy of *data* with sensitive string values encrypted.

    Non-string values and non-sensitive keys are left unchanged.
    Already-encrypted values (Fernet tokens) are skipped.
    """
    out: dict = {}
    for k, v in data.items():
        if is_sensitive_key(k) and isinstance(v, str) and v:
            # Skip if already encrypted (Fernet token starts with 'gAAAAA')
            if v.startswith("gAAAAA"):
                out[k] = v
            else:
                out[k] = encrypt_field(v, secret)
        elif isinstance(v, dict):
            out[k] = encrypt_sensitive_fields(v, secret)
        else:
            out[k] = v
    return out


def decrypt_sensitive_fields(data: dict, secret: str) -> dict:
    """Return a shallow copy of *data* with sensitive string values decrypted."""
    out: dict = {}
    for k, v in data.items():
        if is_sensitive_key(k) and isinstance(v, str) and v:
            try:
                out[k] = decrypt_field(v, secret)
            except (InvalidToken, Exception):
                logger.warning("Failed to decrypt field '%s', returning raw value", k)
                out[k] = v  # Return as-is if decryption fails
        elif isinstance(v, dict):
            out[k] = decrypt_sensitive_fields(v, secret)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# File-level encryption at rest
# ---------------------------------------------------------------------------


def _get_default_secret() -> str:
    """Return the app SECRET_KEY for file encryption."""
    from app.core.config import get_settings

    return get_settings().SECRET_KEY


def encrypt_file(file_path: Path, key: str | None = None) -> None:
    """Encrypt a file in-place using Fernet."""
    secret = key or _get_default_secret()
    f = Fernet(_derive_fernet_key(secret))
    data = Path(file_path).read_bytes()
    Path(file_path).write_bytes(f.encrypt(data))


def decrypt_file(file_path: Path, key: str | None = None) -> bytes:
    """Decrypt a file and return plaintext bytes."""
    secret = key or _get_default_secret()
    f = Fernet(_derive_fernet_key(secret))
    return f.decrypt(Path(file_path).read_bytes())


# ---------------------------------------------------------------------------
# Password-based encryption for exports
# ---------------------------------------------------------------------------


def _derive_key_from_password(password: str, salt: bytes) -> bytes:
    """Derive a Fernet key from a password using PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def encrypt_data_with_password(data: bytes, password: str) -> bytes:
    """Encrypt *data* with a password-derived key.

    Returns ``salt (16 bytes) || ciphertext``.
    """
    salt = os.urandom(PBKDF2_SALT_LENGTH)
    f = Fernet(_derive_key_from_password(password, salt))
    return salt + f.encrypt(data)


def decrypt_data_with_password(blob: bytes, password: str) -> bytes:
    """Decrypt a blob produced by :func:`encrypt_data_with_password`."""
    salt, ciphertext = blob[:PBKDF2_SALT_LENGTH], blob[PBKDF2_SALT_LENGTH:]
    f = Fernet(_derive_key_from_password(password, salt))
    return f.decrypt(ciphertext)


# ---------------------------------------------------------------------------
# SQLAlchemy TypeDecorator for transparent column-level encryption
# ---------------------------------------------------------------------------

_FERNET_TOKEN_PREFIX = "gAAAAA"


class EncryptedString(TypeDecorator):
    """SQLAlchemy TypeDecorator that transparently encrypts/decrypts string
    column values using the same Fernet backend as ``encrypt_byok_key``.

    Store as TEXT in the database; present as plaintext in Python.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str) and value.startswith(_FERNET_TOKEN_PREFIX):
            return value  # already encrypted, leave it
        try:
            from app.core.security import encrypt_byok_key
            return encrypt_byok_key(value)
        except Exception:
            return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            from app.core.security import decrypt_byok_key
            return decrypt_byok_key(value)
        except Exception:
            return value  # fallback: return raw (may be unencrypted legacy value)

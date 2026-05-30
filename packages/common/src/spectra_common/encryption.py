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

from spectra_common.constants import PBKDF2_SALT_LENGTH

logger = logging.getLogger(__name__)

#: Field name substrings that indicate sensitive data.
SENSITIVE_KEYS = ("password", "secret", "token", "credential", "api_key")


def _derive_fernet_key_legacy(secret: str) -> bytes:
    """Legacy SHA-256 derivation — used only for reading old data."""
    raw = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(raw)


def _derive_fernet_key_modern(secret: str) -> bytes:
    """PBKDF2-based derivation for new data."""
    salt = b"spectra-fernet-field-encryption-v1"
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=600_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a Fernet-compatible key (32 bytes, url-safe base64) from *secret*.

    Uses modern PBKDF2 derivation for all new encryptions.
    """
    return _derive_fernet_key_modern(secret)


def encrypt_field(data: str, secret: str) -> str:
    """Encrypt *data* and return a Fernet token string."""
    f = Fernet(_derive_fernet_key(secret))
    return f.encrypt(data.encode("utf-8")).decode("ascii")


def decrypt_field(encrypted_data: str, secret: str) -> str:
    """Decrypt a Fernet token back to the original string.

    Tries modern key first, falls back to legacy for pre-migration data.
    """
    try:
        f = Fernet(_derive_fernet_key_modern(secret))
        return f.decrypt(encrypted_data.encode("ascii")).decode("utf-8")
    except (InvalidToken, Exception):
        f = Fernet(_derive_fernet_key_legacy(secret))
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
    """Return a shallow copy of *data* with sensitive string values decrypted.

    Tries modern key first, falls back to legacy for pre-migration data.
    """
    out: dict = {}
    for k, v in data.items():
        if is_sensitive_key(k) and isinstance(v, str) and v:
            try:
                out[k] = decrypt_field(v, secret)
            except (InvalidToken, Exception):
                logger.error("Failed to decrypt field '%s' — returning None to avoid leaking ciphertext", k)
                out[k] = None
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
    from spectra_common.config import get_settings

    return get_settings().SECRET_KEY.get_secret_value()


def encrypt_file(file_path: Path, key: str | None = None) -> None:
    """Encrypt a file in-place using Fernet."""
    secret = key or _get_default_secret()
    f = Fernet(_derive_fernet_key(secret))
    data = Path(file_path).read_bytes()
    Path(file_path).write_bytes(f.encrypt(data))


def decrypt_file(file_path: Path, key: str | None = None) -> bytes:
    """Decrypt a file and return plaintext bytes.

    Tries modern key first, falls back to legacy for pre-migration data.
    """
    secret = key or _get_default_secret()
    data = Path(file_path).read_bytes()
    try:
        f = Fernet(_derive_fernet_key_modern(secret))
        return f.decrypt(data)
    except (InvalidToken, Exception):
        f = Fernet(_derive_fernet_key_legacy(secret))
        return f.decrypt(data)


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
# ENCRYPTION_KEY-based helpers (MFA secrets, BYOK keys) — separate from JWT signing
# ---------------------------------------------------------------------------

_FERNET_TOKEN_PREFIX = "gAAAAA"


def _get_encryption_key() -> bytes:
    """Return a Fernet key derived from ``settings.ENCRYPTION_KEY``."""
    from spectra_common.config import settings

    key = settings.ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY is required for MFA and data encryption. "
            "Set it in your environment or .env file."
        )
    derived = hashlib.sha256(key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(derived)


def _get_fernet() -> Fernet:
    """Fernet instance derived from ``ENCRYPTION_KEY``."""
    return Fernet(_get_encryption_key())


def encrypt_mfa_secret(secret: str) -> str:
    """Encrypt a TOTP secret for database storage."""
    return _get_fernet().encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_mfa_secret(encrypted: str) -> str:
    """Decrypt a stored TOTP secret."""
    try:
        return _get_fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise ValueError("Failed to decrypt MFA secret")


def encrypt_byok_key(key: str) -> str:
    """Encrypt a BYOK API key for storage."""
    return _get_fernet().encrypt(key.encode("utf-8")).decode("utf-8")


def decrypt_byok_key(encrypted: str) -> str:
    """Decrypt a stored BYOK API key."""
    try:
        return _get_fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise ValueError("Failed to decrypt BYOK key")


# ---------------------------------------------------------------------------
# Asymmetric JWT signing keypair (EdDSA / Ed25519)
# ---------------------------------------------------------------------------


def generate_jwt_keypair() -> tuple[str, str]:
    """Generate a fresh Ed25519 keypair for EdDSA JWT signing.

    Returns ``(private_pem, public_pem)`` as PEM strings: the private key in
    unencrypted PKCS#8 and the public key in SubjectPublicKeyInfo. PyJWT signs
    with the private key (``EdDSA``) and verifies with the public key.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem

"""SQLAlchemy column types for transparent field-level encryption.

The crypto backend lives in ``spectra_common.encryption`` (foundation layer);
this module only adapts it to a SQLAlchemy ``TypeDecorator`` for ORM columns.
"""

from __future__ import annotations

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from spectra_common.encryption import (
    _FERNET_TOKEN_PREFIX,
    decrypt_byok_key,
    encrypt_byok_key,
)


class EncryptedString(TypeDecorator):
    """Transparently encrypts/decrypts string column values with Fernet.

    Stored as TEXT in the database; presented as plaintext in Python.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str) and value.startswith(_FERNET_TOKEN_PREFIX):
            return value  # already encrypted, leave it
        return encrypt_byok_key(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return decrypt_byok_key(value)

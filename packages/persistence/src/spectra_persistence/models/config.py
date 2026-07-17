"""
System Configuration Model.

Stores dynamic system settings like LLM provider, API keys, etc.
When ``is_secret`` is True the ``value`` property transparently
encrypts on write and decrypts on read using the app SECRET_KEY.
"""

import logging

from cryptography.fernet import InvalidToken
from sqlalchemy import String, Text, event
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from spectra_persistence.orm.base import Base

logger = logging.getLogger(__name__)

_FERNET_TOKEN_PREFIX = "gAAAAA"


class SystemConfig(Base):
    """
    System configuration settings.
    Designed to be a singleton row (key-value pairs or single row).
    Here we use a key-value approach for flexibility.
    """

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    _value: Mapped[str | None] = mapped_column("value", Text, nullable=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_secret: Mapped[bool] = mapped_column(default=False)

    @hybrid_property
    def value(self) -> str | None:
        """Return the plaintext value, decrypting automatically for secrets."""
        if self._value is None:
            return None
        if self.is_secret:
            try:
                from spectra_common.encryption import _get_default_secret, decrypt_field

                return decrypt_field(self._value, _get_default_secret())
            except (InvalidToken, ValueError, UnicodeDecodeError, TypeError):
                return self._value  # legacy plaintext or ciphertext before key rotation
            except Exception:
                logger.exception(
                    "Unexpected error decrypting secret config key=%r",
                    getattr(self, "key", "?"),
                )
                raise
        return self._value

    @value.inplace.setter
    def _value_setter(self, value: str | None) -> None:
        """Store the value, encrypting automatically for secrets."""
        if value is None:
            self._value = None
            return
        if getattr(self, "is_secret", False) and not value.startswith(_FERNET_TOKEN_PREFIX):
            try:
                from spectra_common.encryption import _get_default_secret, encrypt_field

                self._value = encrypt_field(value, _get_default_secret())
                return
            except (UnicodeEncodeError, ValueError, TypeError) as exc:
                logger.warning(
                    "Failed to encrypt secret config key=%r: %s",
                    getattr(self, "key", "?"),
                    exc,
                )
                raise ValueError(f"Could not encrypt secret value for key {self.key!r}") from exc
        self._value = value

    @value.inplace.expression
    @classmethod
    def _value_expression(cls):
        return cls._value

    def __repr__(self) -> str:
        return f"<SystemConfig key={self.key!r}>"


@event.listens_for(SystemConfig, "before_insert")
@event.listens_for(SystemConfig, "before_update")
def _auto_encrypt_secret_value(mapper, connection, target):
    """Safety net: ensure secret values are always encrypted before DB write."""
    if target.is_secret and target._value and not target._value.startswith(_FERNET_TOKEN_PREFIX):
        try:
            from spectra_common.encryption import _get_default_secret, encrypt_field

            target._value = encrypt_field(target._value, _get_default_secret())
        except (UnicodeEncodeError, ValueError, TypeError) as exc:
            logger.warning(
                "Failed to auto-encrypt secret config '%s': %s",
                getattr(target, "key", "?"),
                exc,
            )
            raise ValueError(
                f"Could not encrypt secret value for key {getattr(target, 'key', '?')!r}"
            ) from exc
        except Exception:
            logger.exception(
                "Unexpected failure auto-encrypting secret config '%s'",
                getattr(target, "key", "?"),
            )
            raise

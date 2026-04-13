"""
System Configuration Model.

Stores dynamic system settings like LLM provider, API keys, etc.
When ``is_secret`` is True the ``value`` property transparently
encrypts on write and decrypts on read using the app SECRET_KEY.
"""

import logging

from sqlalchemy import String, Text, event
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

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
                from app.core.encryption import _get_default_secret, decrypt_field

                return decrypt_field(self._value, _get_default_secret())
            except Exception:
                return self._value  # legacy unencrypted or decryption unavailable
        return self._value

    @value.inplace.setter
    def _value_setter(self, val: str | None) -> None:
        """Store the value, encrypting automatically for secrets."""
        if val is None:
            self._value = None
            return
        if getattr(self, "is_secret", False) and not val.startswith(_FERNET_TOKEN_PREFIX):
            try:
                from app.core.encryption import _get_default_secret, encrypt_field

                self._value = encrypt_field(val, _get_default_secret())
                return
            except Exception:
                pass
        self._value = val

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
            from app.core.encryption import _get_default_secret, encrypt_field

            target._value = encrypt_field(target._value, _get_default_secret())
        except Exception:
            logger.warning("Failed to auto-encrypt secret config '%s'", getattr(target, "key", "?"))

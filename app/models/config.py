"""
System Configuration Model.

Stores dynamic system settings like LLM provider, API keys, etc.
"""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SystemConfig(Base):
    """
    System configuration settings.
    Designed to be a singleton row (key-value pairs or single row).
    Here we use a key-value approach for flexibility.
    """

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(String(255), nullable=True)
    is_secret: Mapped[bool] = mapped_column(default=False)

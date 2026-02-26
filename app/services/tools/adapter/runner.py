"""
Runner configuration for tool execution.

Provides access to application settings for determining
execution context (local vs Docker container).
"""

from app.core.config import settings

__all__ = ["settings"]

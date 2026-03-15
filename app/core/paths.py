"""Helpers for runtime data paths rooted under configured storage."""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings


def data_root() -> Path:
    """Return the configured runtime data root directory."""
    return Path(get_settings().DATA_ROOT)


def data_path(*parts: str) -> Path:
    """Build a path under the configured runtime data root."""
    return data_root().joinpath(*parts)
"""Helpers for runtime data paths rooted under configured storage."""

from __future__ import annotations

from pathlib import Path


def data_root() -> Path:
    """Return the runtime data root directory (fixed internal path)."""
    return Path("/app/data")


def data_path(*parts: str) -> Path:
    """Build a path under the runtime data root."""
    return data_root().joinpath(*parts)

"""Helpers for deterministic PostgreSQL advisory lock IDs."""

from __future__ import annotations

import hashlib

_MAX_SIGNED_BIGINT = (1 << 63) - 1


def stable_lock_id(name: str) -> int:
    """Return a deterministic positive bigint-safe advisory lock ID."""
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False) & _MAX_SIGNED_BIGINT

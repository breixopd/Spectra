"""Distributed mission state store backed by PostgreSQL SystemCache."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select

from app.core.database import async_session_maker
from app.models.infrastructure import SystemCache

logger = logging.getLogger("spectra.mission.state_store")

# Key patterns
_KEY_PREFIX = "mission_state:"
_DEFAULT_TTL_MINUTES = 120  # Auto-cleanup abandoned missions after 2 hours


class MissionStateStore:
    """Persist active mission state to PostgreSQL for horizontal scaling."""

    def __init__(self, ttl_minutes: int = _DEFAULT_TTL_MINUTES):
        self.ttl_minutes = ttl_minutes

    def _key(self, mission_id: str) -> str:
        return f"{_KEY_PREFIX}{mission_id}"

    async def register(self, mission_id: str, state: dict[str, Any]) -> None:
        """Register a new active mission in the store."""
        key = self._key(mission_id)
        expires = datetime.now(UTC) + timedelta(minutes=self.ttl_minutes)
        async with async_session_maker() as session:
            existing = await session.get(SystemCache, key)
            if existing:
                existing.value = state
                existing.expires_at = expires
            else:
                entry = SystemCache(
                    key=key,
                    value=state,
                    expires_at=expires,
                    created_at=datetime.now(UTC),
                )
                session.add(entry)
            await session.commit()
        logger.debug("Registered mission state %s", mission_id)

    async def heartbeat(self, mission_id: str) -> None:
        """Extend TTL for an active mission to prevent auto-cleanup."""
        key = self._key(mission_id)
        expires = datetime.now(UTC) + timedelta(minutes=self.ttl_minutes)
        async with async_session_maker() as session:
            entry = await session.get(SystemCache, key)
            if entry:
                entry.expires_at = expires
                await session.commit()
                logger.debug("Heartbeat for mission %s", mission_id)

    async def get_state(self, mission_id: str) -> dict[str, Any] | None:
        """Get mission state by ID, or None if not found / expired."""
        key = self._key(mission_id)
        async with async_session_maker() as session:
            entry = await session.get(SystemCache, key)
            if entry is None:
                return None
            if entry.expires_at and entry.expires_at < datetime.now(UTC):
                await session.delete(entry)
                await session.commit()
                return None
            return entry.value  # type: ignore[return-value]

    async def update_state(self, mission_id: str, state: dict[str, Any]) -> None:
        """Update stored mission state (partial or full replace)."""
        key = self._key(mission_id)
        async with async_session_maker() as session:
            entry = await session.get(SystemCache, key)
            if entry:
                entry.value = state
                entry.expires_at = datetime.now(UTC) + timedelta(minutes=self.ttl_minutes)
                await session.commit()

    async def get_active(self) -> list[dict[str, Any]]:
        """Return all active (non-expired) mission states."""
        now = datetime.now(UTC)
        async with async_session_maker() as session:
            result = await session.execute(
                select(SystemCache).where(
                    SystemCache.key.like(f"{_KEY_PREFIX}%"),
                    (SystemCache.expires_at.is_(None)) | (SystemCache.expires_at >= now),
                )
            )
            entries = result.scalars().all()
            return [e.value for e in entries]  # type: ignore[misc]

    async def unregister(self, mission_id: str) -> None:
        """Remove mission state from the store."""
        key = self._key(mission_id)
        async with async_session_maker() as session:
            entry = await session.get(SystemCache, key)
            if entry:
                await session.delete(entry)
                await session.commit()
        logger.debug("Unregistered mission state %s", mission_id)

    async def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count of removed entries."""
        now = datetime.now(UTC)
        async with async_session_maker() as session:
            result = await session.execute(
                delete(SystemCache).where(
                    SystemCache.key.like(f"{_KEY_PREFIX}%"),
                    SystemCache.expires_at < now,
                )
            )
            await session.commit()
            count = result.rowcount  # type: ignore[union-attr]
        if count:
            logger.info("Cleaned up %d expired mission state(s)", count)
        return count

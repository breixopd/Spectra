"""Database-backed key-value cache with namespace support and TTL."""

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import async_session_maker
from app.models.infrastructure import CacheEntry

logger = logging.getLogger("spectra.services.cache")


class CacheService:
    """Database-backed key-value cache with TTL support.

    Uses ``namespace:key`` composite keys stored in the ``cache_entries`` table.
    All methods silently return ``None`` / empty when the DB is unavailable.
    """

    @staticmethod
    def _full_key(namespace: str, key: str) -> str:
        return f"{namespace}:{key}"

    @staticmethod
    async def get(namespace: str, key: str) -> str | None:
        """Get cached value. Returns None if expired or missing."""
        try:
            full_key = CacheService._full_key(namespace, key)
            async with async_session_maker() as session:
                now = datetime.now(UTC)
                stmt = select(CacheEntry.value).where(
                    CacheEntry.key == full_key,
                    (CacheEntry.expires_at.is_(None)) | (CacheEntry.expires_at > now),
                )
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
        except Exception as e:
            logger.debug("Cache get failed (%s:%s): %s", namespace, key, e)
            return None

    @staticmethod
    async def set(namespace: str, key: str, value: str, ttl_hours: int = 24) -> None:
        """Set cached value with TTL."""
        try:
            full_key = CacheService._full_key(namespace, key)
            now = datetime.now(UTC)
            expires_at = now + timedelta(hours=ttl_hours)

            async with async_session_maker() as session:
                dialect = session.bind.dialect.name if session.bind else "postgresql"
                if dialect == "postgresql":
                    stmt = (
                        pg_insert(CacheEntry)
                        .values(
                            key=full_key,
                            value=value,
                            expires_at=expires_at,
                            created_at=now,
                        )
                        .on_conflict_do_update(
                            index_elements=["key"],
                            set_={
                                "value": value,
                                "expires_at": expires_at,
                                "created_at": now,
                            },
                        )
                    )
                    await session.execute(stmt)
                else:
                    existing = await session.get(CacheEntry, full_key)
                    if existing:
                        existing.value = value
                        existing.expires_at = expires_at
                        existing.created_at = now
                    else:
                        session.add(
                            CacheEntry(
                                key=full_key,
                                value=value,
                                expires_at=expires_at,
                                created_at=now,
                            )
                        )
                await session.commit()
        except Exception as e:
            logger.debug("Cache set failed (%s:%s): %s", namespace, key, e)

    @staticmethod
    async def delete(namespace: str, key: str) -> None:
        """Delete cached entry."""
        try:
            full_key = CacheService._full_key(namespace, key)
            async with async_session_maker() as session:
                stmt = delete(CacheEntry).where(CacheEntry.key == full_key)
                await session.execute(stmt)
                await session.commit()
        except Exception as e:
            logger.debug("Cache delete failed (%s:%s): %s", namespace, key, e)

    @staticmethod
    async def list_keys(namespace: str) -> list[str]:
        """List all non-expired keys in a namespace."""
        try:
            prefix = f"{namespace}:"
            async with async_session_maker() as session:
                now = datetime.now(UTC)
                stmt = select(CacheEntry.key).where(
                    CacheEntry.key.like(f"{prefix}%"),
                    (CacheEntry.expires_at.is_(None)) | (CacheEntry.expires_at > now),
                )
                result = await session.execute(stmt)
                return [row.removeprefix(prefix) for row in result.scalars().all()]
        except Exception as e:
            logger.debug("Cache list_keys failed (%s): %s", namespace, e)
            return []

    @staticmethod
    async def import_from_file(
        namespace: str,
        key: str,
        path: Path,
        ttl_hours: int = 24,
    ) -> bool:
        """One-time import: read a filesystem cache file into DB.

        Returns True if the file existed and was imported.
        """
        try:
            if not path.exists():
                return False
            data = path.read_text()
            await CacheService.set(namespace, key, data, ttl_hours=ttl_hours)
            logger.info("Imported %s:%s from %s", namespace, key, path)
            return True
        except Exception as e:
            logger.debug("Cache import failed (%s:%s): %s", namespace, key, e)
            return False

    @staticmethod
    async def get_json(namespace: str, key: str) -> dict | list | None:
        """Convenience: get and JSON-parse in one step."""
        raw = await CacheService.get(namespace, key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    async def set_json(
        namespace: str,
        key: str,
        value: dict | list,
        ttl_hours: int = 24,
    ) -> None:
        """Convenience: JSON-serialize and set in one step."""
        await CacheService.set(namespace, key, json.dumps(value), ttl_hours=ttl_hours)

    @staticmethod
    async def scan_prefix(namespace: str, key_prefix: str) -> list[str]:
        """Return all non-expired *values* whose key starts with ``namespace:key_prefix``."""
        try:
            full_prefix = f"{namespace}:{key_prefix}"
            async with async_session_maker() as session:
                now = datetime.now(UTC)
                stmt = select(CacheEntry.value).where(
                    CacheEntry.key.like(f"{full_prefix}%"),
                    (CacheEntry.expires_at.is_(None)) | (CacheEntry.expires_at > now),
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except Exception as e:
            logger.debug("Cache scan_prefix failed (%s:%s): %s", namespace, key_prefix, e)
            return []

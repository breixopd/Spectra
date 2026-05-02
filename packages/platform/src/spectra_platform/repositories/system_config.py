"""SystemConfig Repository for managing key-value system configuration."""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from spectra_platform.models.config import SystemConfig
from spectra_platform.repositories.base import BaseRepository


class SystemConfigRepository(BaseRepository[SystemConfig]):
    """Repository for SystemConfig entity operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(SystemConfig, session)

    async def get_by_key(self, key: str) -> SystemConfig | None:
        """Look up a configuration entry by key."""
        return await self.find_one_by(key=key)

    async def get_all_non_secret(self) -> Sequence[SystemConfig]:
        """Get all non-secret configuration entries."""
        return await self.find_many_by(is_secret=False, limit=1000)

    async def upsert(self, key: str, value: str, is_secret: bool = False) -> SystemConfig:
        """Create or update a config entry by key."""
        existing = await self.get_by_key(key)
        if existing:
            updated = await self.update(existing.id, value=value, is_secret=is_secret)
            if updated is None:
                raise RuntimeError(f"Failed to update config key: {key}")
            return updated
        return await self.create(key=key, value=value, is_secret=is_secret)

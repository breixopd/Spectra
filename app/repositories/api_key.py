"""ApiKey Repository for managing user API keys."""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plan import ApiKey
from app.repositories.base import BaseRepository


class ApiKeyRepository(BaseRepository[ApiKey]):
    """Repository for ApiKey entity operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ApiKey, session)

    async def get_by_user_id(self, user_id: str, skip: int = 0, limit: int = 100) -> Sequence[ApiKey]:
        """Get all API keys belonging to a user."""
        return await self.find_many_by(user_id=user_id, skip=skip, limit=limit)

    async def get_by_prefix(self, key_prefix: str) -> ApiKey | None:
        """Look up an API key by its visible prefix."""
        return await self.find_one_by(key_prefix=key_prefix)

    async def get_active_by_user(self, user_id: str, skip: int = 0, limit: int = 100) -> Sequence[ApiKey]:
        """Get active API keys for a user."""
        return await self.find_many_by(user_id=user_id, is_active=True, skip=skip, limit=limit)

    async def deactivate(self, key_id: str) -> ApiKey | None:
        """Deactivate an API key."""
        return await self.update(key_id, is_active=False)

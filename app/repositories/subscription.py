"""Subscription Repository for managing user subscriptions."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plan import Subscription
from app.repositories.base import BaseRepository


class SubscriptionRepository(BaseRepository[Subscription]):
    """Repository for Subscription entity operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Subscription, session)

    async def get_by_user_id(self, user_id: str) -> Subscription | None:
        """Get a user's active subscription."""
        return await self.find_one_by(user_id=user_id)

    async def get_active_by_user(self, user_id: str) -> Subscription | None:
        """Get the active subscription for a user."""
        return await self.find_one_by(user_id=user_id, status="active")

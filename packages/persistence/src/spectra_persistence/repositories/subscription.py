"""Subscription Repository for managing user subscriptions."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_persistence.models.plan import Subscription
from spectra_persistence.repositories.base import BaseRepository

ENTITLEMENT_ACTIVE_SUBSCRIPTION_STATUSES = ("active", "trialing")


class SubscriptionRepository(BaseRepository[Subscription]):
    """Repository for Subscription entity operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Subscription, session)

    async def get_by_user_id(self, user_id: str) -> Subscription | None:
        """Get a user's active subscription."""
        return await self.find_one_by(user_id=user_id)

    async def get_active_by_user(self, user_id: str) -> Subscription | None:
        """Get the entitlement-active subscription for a user."""
        stmt = (
            select(self.model)
            .where(
                self.model.user_id == user_id,
                self.model.status.in_(ENTITLEMENT_ACTIVE_SUBSCRIPTION_STATUSES),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

"""Plan Repository for managing subscription plans."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plan import Plan
from app.repositories.base import BaseRepository


class PlanRepository(BaseRepository[Plan]):
    """Repository for Plan entity operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Plan, session)

    async def get_by_name(self, name: str) -> Plan | None:
        """Find a plan by its unique name."""
        return await self.find_one_by(name=name)

    async def get_active_plans(self, skip: int = 0, limit: int = 100) -> Sequence[Plan]:
        """Get all active plans ordered by sort_order."""
        stmt = (
            select(self.model)
            .where(self.model.is_active.is_(True))
            .order_by(self.model.sort_order)
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_default_plan(self) -> Plan | None:
        """Get the default plan (is_default=True)."""
        return await self.find_one_by(is_default=True)

    async def get_self_service_registration_plan(self) -> Plan | None:
        """Get the active default plan explicitly eligible for self-registration."""
        stmt = (
            select(self.model)
            .where(
                self.model.is_active.is_(True),
                self.model.is_default.is_(True),
                self.model.allow_self_service_registration.is_(True),
            )
            .order_by(self.model.sort_order, self.model.created_at)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

"""
Target Repository for managing scan targets.
"""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.target import Target, TargetStatus
from app.repositories.base import BaseRepository


class TargetRepository(BaseRepository[Target]):
    """Repository for Target entity operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(Target, session)

    async def find_by_address(self, address: str) -> Target | None:
        """Find target by its address (IP, domain, CIDR)."""
        return await self.find_one_by(address=address)

    async def get_by_address(self, address: str) -> Target | None:
        """Find target by address (alias for find_by_address)."""
        return await self.find_by_address(address)

    async def find_by_status(
        self,
        status: TargetStatus,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Target]:
        """Find all targets with a specific status."""
        return await self.find_many_by(status=status, skip=skip, limit=limit)

    async def get_pending_targets(self, limit: int = 10) -> Sequence[Target]:
        """Get targets awaiting scanning."""
        return await self.find_by_status(TargetStatus.PENDING, limit=limit)

    async def update_status(
        self,
        target_id: str,
        status: TargetStatus,
    ) -> Target | None:
        """Update the status of a target."""
        return await self.update(target_id, status=status)

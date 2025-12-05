"""
Mission Repository for managing mission history.

Provides data access operations for mission CRUD and status queries.
"""

from typing import Optional, Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mission import Mission, MissionStatus
from app.repositories.base import BaseRepository


class MissionRepository(BaseRepository[Mission]):
    """
    Repository for Mission entity operations.

    Provides specialized queries for mission management including
    status filtering and target-based lookups.
    """

    def __init__(self, session: AsyncSession) -> None:
        """
        Initialize the mission repository.

        Args:
            session: Async database session.
        """
        super().__init__(Mission, session)

    async def get_by_target(self, target: str) -> Sequence[Mission]:
        """
        Find missions by target address.

        Args:
            target: Target IP, domain, or URL to search for.

        Returns:
            List of missions matching the target.
        """
        return await self.find_many_by(target=target)

    async def get_active_missions(self) -> Sequence[Mission]:
        """
        Find missions that are currently running.

        Returns:
            List of missions with active status (running, scanning, analyzing, etc.).
        """
        active_statuses = [
            MissionStatus.RUNNING.value,
            MissionStatus.CREATED.value,
            MissionStatus.SCANNING.value,
            MissionStatus.ANALYZING.value,
            MissionStatus.EXPLOITING.value,
        ]

        stmt = select(self.model).where(self.model.status.in_(active_statuses)).order_by(self.model.created_at.desc())

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_status(
        self,
        status: str | MissionStatus,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Mission]:
        """
        Find missions by status.

        Args:
            status: Mission status to filter by.
            skip: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            List of missions matching the status.
        """
        status_value = status.value if isinstance(status, MissionStatus) else status
        return await self.find_many_by(status=status_value, skip=skip, limit=limit)

    async def get_recent(self, limit: int = 10) -> Sequence[Mission]:
        """
        Get most recent missions.

        Args:
            limit: Maximum number of missions to return.

        Returns:
            List of recent missions ordered by creation time desc.
        """
        stmt = select(self.model).order_by(self.model.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_status(
        self,
        mission_id: str,
        status: str | MissionStatus,
    ) -> Optional[Mission]:
        """
        Update the status of a mission.

        Args:
            mission_id: UUID of the mission.
            status: New status value.

        Returns:
            The updated mission or None if not found.
        """
        status_value = status.value if isinstance(status, MissionStatus) else status
        return await self.update(mission_id, status=status_value)

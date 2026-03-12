"""
Mission Repository for managing mission history.

Provides data access operations for mission CRUD and status queries.
"""

import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mission import Mission, MissionStatus
from app.repositories.base import BaseRepository

logger = logging.getLogger("spectra.repositories.mission")


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

    async def get_by_target(self, target: str, user_id: str | None = None) -> Sequence[Mission]:
        """
        Find missions by target address.

        Args:
            target: Target IP, domain, or URL to search for.
            user_id: Optional user ID to filter by (None = no filter, for admin access).

        Returns:
            List of missions matching the target.
        """
        kwargs: dict = {"target": target}
        if user_id:
            kwargs["user_id"] = user_id
        return await self.find_many_by(**kwargs)

    async def get_active_missions(self, user_id: str | None = None) -> Sequence[Mission]:
        """
        Find missions that are currently running.

        Args:
            user_id: Optional user ID to filter by (None = no filter, for admin access).

        Returns:
            List of missions with active status (running, scanning, analyzing, etc.).
        """
        logger.debug("Fetching active missions user_id=%s", user_id)
        active_statuses = [
            MissionStatus.RUNNING.value,
            MissionStatus.CREATED.value,
            MissionStatus.SCANNING.value,
            MissionStatus.ANALYZING.value,
            MissionStatus.EXPLOITING.value,
        ]

        stmt = select(self.model).where(self.model.status.in_(active_statuses)).order_by(self.model.created_at.desc())
        if user_id:
            stmt = stmt.where(self.model.user_id == user_id)

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_status(
        self,
        status: str | MissionStatus,
        skip: int = 0,
        limit: int = 100,
        user_id: str | None = None,
    ) -> Sequence[Mission]:
        """
        Find missions by status.

        Args:
            status: Mission status to filter by.
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            user_id: Optional user ID to filter by (None = no filter, for admin access).

        Returns:
            List of missions matching the status.
        """
        status_value = status.value if isinstance(status, MissionStatus) else status
        kwargs: dict = {"status": status_value}
        if user_id:
            kwargs["user_id"] = user_id
        return await self.find_many_by(skip=skip, limit=limit, **kwargs)

    async def get_recent(self, limit: int = 10, user_id: str | None = None) -> Sequence[Mission]:
        """
        Get most recent missions.

        Args:
            limit: Maximum number of missions to return.
            user_id: Optional user ID to filter by (None = no filter, for admin access).

        Returns:
            List of recent missions ordered by creation time desc.
        """
        stmt = select(self.model).order_by(self.model.created_at.desc()).limit(limit)
        if user_id:
            stmt = stmt.where(self.model.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_status(
        self,
        mission_id: str,
        status: str | MissionStatus,
    ) -> Mission | None:
        """
        Update the status of a mission.

        Args:
            mission_id: UUID of the mission.
            status: New status value.

        Returns:
            The updated mission or None if not found.
        """
        status_value = status.value if isinstance(status, MissionStatus) else status
        logger.debug("Updating mission status id=%s status=%s", mission_id, status_value)
        return await self.update(mission_id, status=status_value)

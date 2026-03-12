"""
Finding Repository for managing vulnerability findings.
"""

import logging
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import Finding, FindingStatus, Severity
from app.repositories.base import BaseRepository

logger = logging.getLogger("spectra.repositories.finding")


class FindingRepository(BaseRepository[Finding]):
    """Repository for Finding entity operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(Finding, session)

    async def find_by_target(
        self,
        target_id: str,
        skip: int = 0,
        limit: int = 100,
        user_id: str | None = None,
    ) -> Sequence[Finding]:
        """Get all findings for a specific target."""
        logger.debug("Finding findings for target=%s skip=%d limit=%d", target_id, skip, limit)
        kwargs: dict = {"target_id": target_id}
        if user_id:
            kwargs["user_id"] = user_id
        return await self.find_many_by(skip=skip, limit=limit, **kwargs)

    async def find_by_severity(
        self,
        severity: Severity,
        skip: int = 0,
        limit: int = 100,
        user_id: str | None = None,
    ) -> Sequence[Finding]:
        """Get all findings with a specific severity."""
        logger.debug("Finding findings by severity=%s", severity)
        kwargs: dict = {"severity": severity}
        if user_id:
            kwargs["user_id"] = user_id
        return await self.find_many_by(skip=skip, limit=limit, **kwargs)

    async def find_by_cve(self, cve_id: str, user_id: str | None = None) -> Sequence[Finding]:
        """Get all findings matching a CVE ID."""
        logger.debug("Finding findings by cve_id=%s", cve_id)
        stmt = select(self.model).where(self.model.cve_id == cve_id)
        if user_id:
            stmt = stmt.where(self.model.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_severity_counts(self, target_id: str | None = None, user_id: str | None = None) -> dict:
        logger.debug("Getting severity counts target=%s", target_id)
        """
        Get count of findings by severity.

        Returns:
            Dict like {"critical": 3, "high": 12, "medium": 8, ...}
        """
        stmt = select(
            self.model.severity,
            func.count(self.model.id).label("count"),  # pylint: disable=not-callable
        ).group_by(self.model.severity)

        if target_id:
            stmt = stmt.where(self.model.target_id == target_id)
        if user_id:
            stmt = stmt.where(self.model.user_id == user_id)

        result = await self.session.execute(stmt)
        return {row.severity.value: row.count for row in result.all()}

    async def update_status(
        self,
        finding_id: str,
        status: FindingStatus,
    ) -> Finding | None:
        """Update the verification status of a finding."""
        logger.debug("Updating finding=%s status=%s", finding_id, status)
        return await self.update(finding_id, status=status)

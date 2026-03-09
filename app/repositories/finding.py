"""
Finding Repository for managing vulnerability findings.
"""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import Finding, FindingStatus, Severity
from app.repositories.base import BaseRepository


class FindingRepository(BaseRepository[Finding]):
    """Repository for Finding entity operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(Finding, session)

    async def find_by_target(
        self,
        target_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Finding]:
        """Get all findings for a specific target."""
        return await self.find_many_by(target_id=target_id, skip=skip, limit=limit)

    async def find_by_severity(
        self,
        severity: Severity,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Finding]:
        """Get all findings with a specific severity."""
        return await self.find_many_by(severity=severity, skip=skip, limit=limit)

    async def find_by_cve(self, cve_id: str) -> Sequence[Finding]:
        """Get all findings matching a CVE ID."""
        stmt = select(self.model).where(self.model.cve_id == cve_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_severity_counts(self, target_id: str | None = None) -> dict:
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

        result = await self.session.execute(stmt)
        return {row.severity.value: row.count for row in result.all()}

    async def update_status(
        self,
        finding_id: str,
        status: FindingStatus,
    ) -> Finding | None:
        """Update the verification status of a finding."""
        return await self.update(finding_id, status=status)

"""Audit Log repository."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.repositories.base import BaseRepository


class AuditLogRepository(BaseRepository[AuditLog]):
    def __init__(self, session: AsyncSession):
        super().__init__(AuditLog, session)

    async def list_events(
        self,
        skip: int = 0,
        limit: int = 50,
        event_type: str | None = None,
    ) -> Sequence[AuditLog]:
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
        if event_type:
            stmt = stmt.where(AuditLog.event_type == event_type)
        stmt = stmt.offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

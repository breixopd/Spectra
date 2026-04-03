"""Audit Log repository."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
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
        user_id: str | None = None,
        ip_address: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> Sequence[AuditLog]:
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if event_type:
            stmt = stmt.where(AuditLog.event_type == event_type)
        if ip_address:
            stmt = stmt.where(AuditLog.ip_address == ip_address)
        if date_from:
            stmt = stmt.where(AuditLog.created_at >= date_from)
        if date_to:
            stmt = stmt.where(AuditLog.created_at <= date_to)
        stmt = stmt.offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_latest_hash(self) -> str | None:
        """Return the integrity_hash of the most recent hash-chained entry."""
        result = await self.session.execute(
            select(AuditLog.integrity_hash)
            .where(AuditLog.integrity_hash.is_not(None))
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def count_events(
        self,
        event_type: str | None = None,
        user_id: str | None = None,
        ip_address: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(AuditLog)
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if event_type:
            stmt = stmt.where(AuditLog.event_type == event_type)
        if ip_address:
            stmt = stmt.where(AuditLog.ip_address == ip_address)
        if date_from:
            stmt = stmt.where(AuditLog.created_at >= date_from)
        if date_to:
            stmt = stmt.where(AuditLog.created_at <= date_to)
        result = await self.session.execute(stmt)
        return result.scalar_one()

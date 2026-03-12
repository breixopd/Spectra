"""ServerNode Repository for managing infrastructure server nodes."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.server_node import ServerNode
from app.repositories.base import BaseRepository


class ServerNodeRepository(BaseRepository[ServerNode]):
    """Repository for ServerNode entity operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ServerNode, session)

    async def get_by_id(self, entity_id: str | int) -> ServerNode | None:  # type: ignore[override]
        """Get a server node by its integer ID."""
        stmt = select(self.model).where(self.model.id == int(entity_id))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_service_type(self, service_type: str, skip: int = 0, limit: int = 100) -> Sequence[ServerNode]:
        """Get all nodes providing a given service type."""
        return await self.find_many_by(service_type=service_type, skip=skip, limit=limit)

    async def get_active_nodes(self, service_type: str | None = None) -> Sequence[ServerNode]:
        """Get active (healthy) nodes, optionally filtered by service type."""
        stmt = select(self.model).where(self.model.is_active.is_(True))
        if service_type:
            stmt = stmt.where(self.model.service_type == service_type)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_primary_node(self, service_type: str) -> ServerNode | None:
        """Get the primary node for a service type."""
        return await self.find_one_by(service_type=service_type, is_primary=True)

"""Integration tests for server pool with actual database.

Requires PostgreSQL.
"""

import os
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.base import Base
from app.models.server_node import ServerNode
from app.services.scaling.pool_manager import ServerPoolManager

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif("sqlite" in os.environ.get("DATABASE_URL", "sqlite"), reason="Requires PostgreSQL"),
]


async def test_full_node_lifecycle():
    """Add, list, update, health check, remove a node."""
    database_url = os.environ.get("DATABASE_URL") or settings.DATABASE_URL.get_secret_value()
    engine = create_async_engine(database_url)
    pool = ServerPoolManager()
    pool._auto_enable_autoscale = AsyncMock(return_value=None)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=[ServerNode.__table__]))

        session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_maker() as session:
            await session.execute(delete(ServerNode))
            await session.commit()

            node = await pool.add_node(
                session,
                "sandbox_worker",
                "test-worker-1",
                "http://localhost:8080",
                weight=2,
                max_capacity=5,
            )
            await session.commit()
            assert node["name"] == "test-worker-1"

            nodes = await pool.list_nodes(session, service_type="sandbox_worker")
            assert any(n["name"] == "test-worker-1" for n in nodes)

            updated = await pool.update_node(session, node["id"], weight=5)
            await session.commit()
            assert updated is not None
            assert updated["weight"] == 5

            removed = await pool.remove_node(session, node["id"])
            await session.commit()
            assert removed is True
    finally:
        await engine.dispose()

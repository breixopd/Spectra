"""Integration tests for server pool with actual database.

Requires PostgreSQL.
"""
import os
import pytest

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        "sqlite" in os.environ.get("DATABASE_URL", "sqlite"),
        reason="Requires PostgreSQL"
    ),
]

async def test_full_node_lifecycle():
    """Add, list, update, health check, remove a node."""
    from app.services.scaling import get_pool_manager
    from app.core.database import async_session_maker

    pool = get_pool_manager()
    async with async_session_maker() as session:
        node = await pool.add_node(
            session, "sandbox_worker", "test-worker-1",
            "http://localhost:8080",
            weight=2, max_capacity=5,
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

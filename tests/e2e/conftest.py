import asyncio
import os
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from app.services.mission.manager import MissionManager


def _plain_dsn() -> str:
    return os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture(scope="session", autouse=True)
def ensure_e2e_admin_user() -> None:
    """Ensure live e2e tests have deterministic admin credentials."""
    dsn = _plain_dsn()
    if not dsn:
        return

    async def _upsert_admin() -> None:
        import asyncpg

        from app.auth.security import get_password_hash

        username = os.environ.get("APP_USERNAME", os.environ.get("TEST_USERNAME", "admin"))
        password = os.environ.get("APP_PASSWORD", os.environ.get("TEST_PASSWORD", "Admin123!"))
        email = os.environ.get("APP_ADMIN_EMAIL", "admin@test.local")
        password_hash = get_password_hash(password)

        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(
                """
                INSERT INTO users (
                    id, username, email, hashed_password, role,
                    is_active, is_superuser, email_verified,
                    login_fail_count, locked_until, last_activity, created_at, updated_at
                )
                VALUES (
                    gen_random_uuid(), $1, $2, $3, 'admin',
                    true, true, true,
                    0, NULL, NOW(), NOW(), NOW()
                )
                ON CONFLICT (username) DO UPDATE SET
                    email = EXCLUDED.email,
                    hashed_password = EXCLUDED.hashed_password,
                    role = 'admin',
                    is_active = true,
                    is_superuser = true,
                    email_verified = true,
                    login_fail_count = 0,
                    locked_until = NULL,
                    last_activity = NOW(),
                    updated_at = NOW()
                """,
                username,
                email,
                password_hash,
            )
        finally:
            await conn.close()

    asyncio.run(_upsert_admin())


@pytest_asyncio.fixture(autouse=True)
async def dispose_e2e_database_pool():
    """Avoid asyncpg connections leaking across pytest-asyncio event loops."""
    yield

    from app.core.database import engine

    await engine.dispose()


async def wait_for_mission_status(
    mission_manager: "MissionManager",
    mission_id: str,
    target_statuses: list[str],
    timeout: float = 10.0,
    interval: float = 0.5,
) -> str:
    """Wait for mission to reach one of the target statuses."""
    start_time = asyncio.get_running_loop().time()
    while (asyncio.get_running_loop().time() - start_time) < timeout:
        mission = await mission_manager.get_mission(mission_id)
        if mission and mission.status in target_statuses:
            return mission.status
        await asyncio.sleep(interval)

    mission = await mission_manager.get_mission(mission_id)
    current_status = mission.status if mission else "unknown"
    raise TimeoutError(f"Mission {mission_id} did not reach {target_statuses} in {timeout}s. Current: {current_status}")


async def get_mission_logs(mission_manager: "MissionManager", mission_id: str) -> list[str]:
    """Get logs for a mission."""
    mission = await mission_manager.get_mission(mission_id)
    if not mission:
        return []
    return mission.logs

import os
import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.infrastructure import InfrastructureBase, JobQueue, SystemCache, SystemStatus


@pytest_asyncio.fixture
async def infra_engine():
    database_url = os.environ.get("DATABASE_URL") or settings.DATABASE_URL.get_secret_value()
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: InfrastructureBase.metadata.create_all(
                sync_conn,
                tables=[SystemCache.__table__, JobQueue.__table__, SystemStatus.__table__],
            )
        )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(infra_engine):
    maker = async_sessionmaker(infra_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        await session.execute(delete(JobQueue))
        await session.execute(delete(SystemCache))
        await session.execute(delete(SystemStatus))
        await session.commit()
        yield session


@pytest.mark.asyncio
async def test_jsonb_type_round_trip(db_session):
    cache_item = SystemCache(key=f"test_key_{uuid.uuid4().hex[:8]}", value={"some": "data"})
    db_session.add(cache_item)
    await db_session.commit()

    retrieved = await db_session.scalar(select(SystemCache).where(SystemCache.key == cache_item.key))
    assert retrieved is not None
    assert retrieved.value == {"some": "data"}


@pytest.mark.asyncio
async def test_jsonb_type_none_values(db_session):
    job_id = f"job_null_{uuid.uuid4().hex[:8]}"
    job = JobQueue(id=job_id, queue_name="test_q", function="my_func", result=None)
    db_session.add(job)
    await db_session.commit()

    retrieved = await db_session.get(JobQueue, job_id)
    assert retrieved is not None
    assert retrieved.result is None


@pytest.mark.asyncio
async def test_job_queue_model(db_session):
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    job = JobQueue(
        id=job_id,
        queue_name="test_q",
        function="my_func",
        args=[1, 2],
        kwargs={"test": "val"},
        status="queued",
    )
    db_session.add(job)
    await db_session.commit()

    retrieved = await db_session.get(JobQueue, job_id)
    assert retrieved is not None
    assert retrieved.function == "my_func"
    assert retrieved.args == [1, 2]
    assert retrieved.kwargs == {"test": "val"}
    assert retrieved.status == "queued"


@pytest.mark.asyncio
async def test_system_status_model(db_session):
    key = f"test_status_{uuid.uuid4().hex[:8]}"
    status = SystemStatus(key=key, value={"is_ready": True})
    db_session.add(status)
    await db_session.commit()

    retrieved = await db_session.get(SystemStatus, key)
    assert retrieved is not None
    assert retrieved.value == {"is_ready": True}
    assert isinstance(retrieved.updated_at, datetime)

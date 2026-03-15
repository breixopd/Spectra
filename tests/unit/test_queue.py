import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.queue
from app.core.config import settings
from app.core.queue import Job, PostgresJobQueue
from app.models.infrastructure import InfrastructureBase, JobQueue


@pytest_asyncio.fixture
async def queue_engine():
    engine = create_async_engine(settings.DATABASE_URL.get_secret_value())
    async with engine.begin() as conn:
        await conn.run_sync(InfrastructureBase.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_maker(queue_engine):
    maker = async_sessionmaker(queue_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        await session.execute(delete(JobQueue))
        await session.commit()
    return maker


@pytest.fixture
def mock_session_maker(db_session_maker, monkeypatch):
    monkeypatch.setattr(app.core.queue, "async_session_maker", db_session_maker)
    return db_session_maker


@pytest.mark.asyncio
async def test_postgres_job_queue_enqueue(db_session_maker, mock_session_maker):
    queue = PostgresJobQueue("test_q")
    job_id = await queue.enqueue_job("test_func", 1, 2, _timeout=10, kwarg1="val1")

    assert job_id is not None

    async with db_session_maker() as session:
        job_record = await session.get(JobQueue, job_id)

    assert job_record is not None
    assert job_record.queue_name == "test_q"
    assert job_record.function == "test_func"
    assert job_record.args == [1, 2]
    assert job_record.kwargs == {"kwarg1": "val1"}
    assert job_record.status == "queued"
    assert job_record.timeout == 10


@pytest.mark.asyncio
async def test_job_status_and_result(db_session_maker, mock_session_maker):
    job_id = str(uuid.uuid4())
    async with db_session_maker() as session:
        session.add(
            JobQueue(
                id=job_id,
                queue_name="q",
                function="f",
                status="completed",
                result={"ok": True},
            )
        )
        await session.commit()

    job = Job(job_id)
    assert await job.status() == "completed"
    assert await job.result() == {"ok": True}

    info = await job.info()
    assert info is not None
    assert info.function == "f"

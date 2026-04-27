import asyncio
import os
import time
import uuid
from contextlib import suppress
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.infrastructure.queue
from app.core.config import settings
from app.infrastructure.queue import Job, PostgresJobQueue
from app.models.infrastructure import InfrastructureBase, JobQueue


def _queue_database_url() -> str:
    if os.path.exists("/.dockerenv"):
        return os.environ.get("DATABASE_URL") or settings.DATABASE_URL.get_secret_value()

    env_path = Path(__file__).resolve().parents[2] / ".env.test"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()

    return settings.DATABASE_URL.get_secret_value()


@pytest_asyncio.fixture
async def queue_engine():
    database_url = _queue_database_url()
    if not database_url.startswith("postgresql"):
        pytest.skip(
            "Queue integration tests require a PostgreSQL test DB; "
            "use ./tests/run_load_tests.sh performance or set DATABASE_URL to the test Postgres instance."
        )

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
            await conn.run_sync(
                lambda sync_conn: InfrastructureBase.metadata.create_all(
                    sync_conn,
                    tables=[JobQueue.__table__],
                )
            )
    except (InterfaceError, OperationalError, OSError, TimeoutError):
        await engine.dispose()
        pytest.skip(
            "Queue integration tests require a reachable PostgreSQL test DB; "
            "use ./tests/run_load_tests.sh performance or start the stack first."
        )
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
    monkeypatch.setattr(app.infrastructure.queue, "async_session_maker", db_session_maker)
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


async def _completed_jobs_for_queue(db_session_maker, queue_name: str) -> int:
    async with db_session_maker() as session:
        result = await session.execute(
            select(JobQueue.id).where(
                JobQueue.queue_name == queue_name,
                JobQueue.status == "completed",
            )
        )
        return len(result.scalars().all())


@pytest.mark.asyncio
@pytest.mark.performance
async def test_postgres_job_queue_throughput(db_session_maker, mock_session_maker):
    job_count = int(os.getenv("QUEUE_THROUGHPUT_JOB_COUNT", "25"))
    max_drain_seconds = float(os.getenv("QUEUE_THROUGHPUT_MAX_DRAIN_SECONDS", "5.0"))
    queue_name = f"perf_{uuid.uuid4().hex[:10]}"

    async def lightweight_job(job_number: int) -> dict[str, int]:
        await asyncio.sleep(0)
        return {"job_number": job_number}

    worker_task = asyncio.create_task(
        app.infrastructure.queue.worker_loop([lightweight_job], queue_name=queue_name, poll_delay=0.01)
    )

    try:
        queue = PostgresJobQueue(queue_name)

        for job_number in range(job_count):
            await queue.enqueue_job("lightweight_job", job_number)

        started = time.perf_counter()

        while await _completed_jobs_for_queue(db_session_maker, queue_name) < job_count:
            await asyncio.sleep(0.02)
            if (time.perf_counter() - started) > (max_drain_seconds + 2.0):
                raise AssertionError(f"Queue did not drain within {max_drain_seconds + 2.0:.1f}s")

        drain_time = time.perf_counter() - started
        assert drain_time <= max_drain_seconds

        async with db_session_maker() as session:
            result = await session.execute(select(JobQueue).where(JobQueue.queue_name == queue_name))
            jobs = result.scalars().all()

        assert len(jobs) == job_count
        assert all(job.status == "completed" for job in jobs)
    finally:
        worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await worker_task

        async with db_session_maker() as session:
            await session.execute(delete(JobQueue).where(JobQueue.queue_name == queue_name))
            await session.commit()

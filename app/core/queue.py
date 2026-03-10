import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from app.core.database import async_session_maker
from app.models.infrastructure import JobQueue

logger = logging.getLogger("spectra.core.queue")


class PostgresJobQueue:
    """
    A lightweight PostgreSQL-backed job queue.
    Replaces ARQ for executing long-running tasks like tool execution.
    Uses SELECT ... FOR UPDATE SKIP LOCKED to ensure atomic job checking.
    """

    def __init__(self, queue_name: str = "default"):
        if not re.match(r'^[a-z][a-z0-9_]{0,62}$', queue_name):
            raise ValueError(f"Invalid queue_name: {queue_name!r}. Must match [a-z][a-z0-9_]{{0,62}}.")
        self.queue_name = queue_name

    async def enqueue_job(self, function_name: str, *args, _timeout: int | None = None, _priority: int | None = None, **kwargs) -> str:
        """Enqueue a new job and return its ID."""
        from app.core.config import get_settings

        job_id = str(uuid.uuid4())
        _settings = get_settings()

        async with async_session_maker() as session:
            job = JobQueue(
                id=job_id,
                queue_name=self.queue_name,
                function=function_name,
                args=list(args),
                kwargs=kwargs,
                status="queued",
                timeout=_timeout,
                priority=_priority if _priority is not None else _settings.SANDBOX_DEFAULT_PRIORITY,
            )
            session.add(job)
            await session.commit()

            # Notify workers that a new job is available
            try:
                # Raw connection needed for LISTEN/NOTIFY
                conn = await session.connection()
                raw_conn = await conn.get_raw_connection()
                # Use driver_connection for asyncpg
                if hasattr(raw_conn, "driver_connection"):
                    await raw_conn.driver_connection.execute(f"NOTIFY spectra_jobs, '{self.queue_name}'")
            except Exception as e:
                logger.warning("NOTIFY failed: %s", e)

        logger.info("Enqueued job %s (%s)", job_id, function_name)
        return job_id


class Job:
    """Job handle for checking status or waiting for completion."""
    def __init__(self, job_id: str, pool: PostgresJobQueue | None = None):
        self.job_id = job_id
        self.pool = pool

    async def status(self) -> str:
        """Get the current status of the job."""
        async with async_session_maker() as session:
            result = await session.execute(select(JobQueue.status).where(JobQueue.id == self.job_id))
            status = result.scalar_one_or_none()
            return status or "not_found"

    async def result(self, timeout: int | None = None) -> Any:
        """Get the result of the job, polling until complete or timeout."""
        import time

        start = time.monotonic()
        poll_interval = 0.5

        while True:
            async with async_session_maker() as session:
                result = await session.execute(select(JobQueue).where(JobQueue.id == self.job_id))
                job = result.scalar_one_or_none()

                if not job:
                    return None
                if job.status == "completed":
                    return job.result
                if job.status == "failed":
                    raise Exception(job.error or "Job failed")

            if timeout is not None and (time.monotonic() - start) >= timeout:
                raise TimeoutError(f"Job {self.job_id} timed out after {timeout}s")

            await asyncio.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.5, 5.0)

    async def info(self) -> Any:
        """Get full info of the job."""
        async with async_session_maker() as session:
            result = await session.execute(select(JobQueue).where(JobQueue.id == self.job_id))
            job = result.scalar_one_or_none()
            if not job:
                return None

            # Create a dict that matches JobDef
            class JobDef:
                def __init__(self, job):
                    self.function = job.function
                    self.args = job.args
                    self.kwargs = job.kwargs
                    self.enqueue_time = job.enqueued_at

            return JobDef(job)


class WorkerState:
    """Mock the worker state injected into functions."""
    def __init__(self, functions: list):
        self.functions = {f.__name__: f for f in functions}

async def worker_loop(functions: list, queue_name: str = "default", poll_delay: float = 1.0):
    """
    Main background loop that repeatedly polls for queued jobs and executes them.
    Should be run in a separate container/process.
    """
    logger.info("Starting PostgresJobQueue worker for queue '%s'", queue_name)
    worker_state = WorkerState(functions)
    current_job_id: str | None = None

    while True:
        try:
            # 1. Fetch next job (SKIP LOCKED prevents concurrent workers from taking the same job)
            async with async_session_maker() as session:
                query = (
                    select(JobQueue)
                    .where(JobQueue.status == "queued", JobQueue.queue_name == queue_name)
                    .order_by(JobQueue.priority.asc(), JobQueue.enqueued_at.asc())
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )

                result = await session.execute(query)
                job = result.scalar_one_or_none()

                if not job:
                    # No job found, sleep and try again
                    await asyncio.sleep(poll_delay)
                    continue

                # 2. Mark as in_progress
                job.status = "in_progress"
                job.started_at = datetime.now(UTC)
                await session.commit()

            current_job_id = job.id
            logger.info("Executing job %s: %s", job.id, job.function)

            # 3. Execute function
            try:
                func = worker_state.functions.get(job.function)
                if not func:
                    raise ValueError(f"Function {job.function} not registered")

                if asyncio.iscoroutinefunction(func):
                    res = await func(*job.args, **job.kwargs)
                else:
                    res = func(*job.args, **job.kwargs)

                # 4. Success -> Completed
                async with async_session_maker() as session:
                    stmt = update(JobQueue).where(JobQueue.id == job.id).values(
                        status="completed",
                        result=res,
                        completed_at=datetime.now(UTC)
                    )
                    await session.execute(stmt)
                    await session.commit()
                logger.info("Job %s completed successfully", job.id)

            except Exception as e:
                # 5. Failure -> Failed
                logger.error("Job %s failed: %s", job.id, e)
                async with async_session_maker() as session:
                    stmt = update(JobQueue).where(JobQueue.id == job.id).values(
                        status="failed",
                        error=str(e),
                        completed_at=datetime.now(UTC)
                    )
                    await session.execute(stmt)
                    await session.commit()
            finally:
                current_job_id = None

        except asyncio.CancelledError:
            logger.info("Worker loop cancelled.")
            if current_job_id:
                try:
                    async with async_session_maker() as session:
                        stmt = update(JobQueue).where(JobQueue.id == current_job_id).values(
                            status="failed",
                            error="Worker shutdown",
                            completed_at=datetime.now(UTC)
                        )
                        await session.execute(stmt)
                        await session.commit()
                    logger.info("Marked abandoned job %s as failed", current_job_id)
                except Exception as e:
                    logger.warning("Failed to mark abandoned job as failed: %s", e)
            break
        except Exception as e:
            logger.error("Error in worker loop: %s", e)
            await asyncio.sleep(poll_delay)

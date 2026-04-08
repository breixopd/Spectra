import asyncio
import contextlib
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from app.core.database import async_session_maker
from app.models.infrastructure import JobQueue

logger = logging.getLogger(__name__)


class PostgresJobQueue:
    """
    A lightweight PostgreSQL-backed job queue.
    Replaces ARQ for executing long-running tasks like tool execution.
    Uses SELECT ... FOR UPDATE SKIP LOCKED to ensure atomic job checking.
    """

    def __init__(self, queue_name: str = "default"):
        if not re.match(r"^[a-z][a-z0-9_]{0,62}$", queue_name):
            raise ValueError(f"Invalid queue_name: {queue_name!r}. Must match [a-z][a-z0-9_]{{0,62}}.")
        self.queue_name = queue_name

    async def enqueue_job(
        self, function_name: str, *args, _timeout: int | None = None, _priority: int | None = None, **kwargs
    ) -> str:
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
            except (OSError, RuntimeError) as e:
                logger.warning("NOTIFY failed: %s", e)

        logger.info("Enqueued job %s (%s)", job_id, function_name)
        return job_id

    async def recover_stale_jobs(self, max_age_minutes: int = 30) -> int:
        """Recover jobs stuck in 'in_progress' state.

        Marks jobs that have been in_progress longer than *max_age_minutes* as
        failed so they don't block the queue forever.

        Returns the number of recovered jobs.
        """
        cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
        async with async_session_maker() as session:
            stmt = (
                update(JobQueue)
                .where(
                    JobQueue.status == "in_progress",
                    JobQueue.started_at < cutoff,
                    JobQueue.queue_name == self.queue_name,
                )
                .values(
                    status="failed",
                    error=f"Stale job recovered after {max_age_minutes} minutes",
                    completed_at=datetime.now(UTC),
                )
            )
            result = await session.execute(stmt)
            await session.commit()
            count = result.rowcount  # type: ignore[union-attr]

        if count:
            logger.warning("Recovered %d stale job(s) older than %d minutes", count, max_age_minutes)
        return count

    async def handle_job_failure(self, job_id: str, error: str) -> None:
        """Handle a failed job — retry or move to dead letter."""
        async with async_session_maker() as session:
            job = await session.get(JobQueue, job_id)
            if not job:
                return
            job.retry_count += 1
            if job.retry_count >= job.max_retries:
                job.status = "dead_letter"
                job.completed_at = datetime.now(UTC)
                logger.warning(
                    "Job %s moved to dead letter after %d retries: %s",
                    job_id,
                    job.retry_count,
                    error,
                )
            else:
                job.status = "pending"
                logger.info(
                    "Job %s queued for retry %d/%d",
                    job_id,
                    job.retry_count,
                    job.max_retries,
                )
            job.error = error
            await session.commit()

    async def list_dead_letter_jobs(self, limit: int = 50) -> list:
        """List jobs in dead letter state for admin review."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(JobQueue)
                .where(
                    JobQueue.status == "dead_letter",
                    JobQueue.queue_name == self.queue_name,
                )
                .order_by(JobQueue.completed_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())


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

    def __init__(self, functions: list) -> None:
        self.functions = {f.__name__: f for f in functions}


async def worker_loop(functions: list, queue_name: str = "default", poll_delay: float = 1.0) -> None:
    """
    Main background loop that repeatedly polls for queued jobs and executes them.
    Listens for NOTIFY events on the ``spectra_jobs`` channel to wake up
    immediately when a job is enqueued, with a fallback poll every *poll_delay* seconds.
    Should be run in a separate container/process.
    """
    logger.info("Starting PostgresJobQueue worker for queue '%s'", queue_name)
    worker_state = WorkerState(functions)
    current_job_id: str | None = None

    # Set up LISTEN for instant wake-up
    notify_event: asyncio.Event = asyncio.Event()
    _pg_listener_conn = None

    async def _start_listener():
        nonlocal _pg_listener_conn
        try:
            import asyncpg

            from app.core.config import settings as _cfg

            dsn = _cfg.DATABASE_URL.get_secret_value().replace("postgresql+asyncpg://", "postgresql://")
            _pg_listener_conn = await asyncpg.connect(dsn)
            await _pg_listener_conn.add_listener("spectra_jobs", lambda *_args: notify_event.set())
            logger.info("Worker LISTEN on spectra_jobs channel active")
        except Exception as exc:
            logger.warning("LISTEN setup failed, falling back to polling: %s", exc)

    await _start_listener()

    try:
        while True:
            try:
                # Wait for a NOTIFY or fall back after poll_delay
                notify_event.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(notify_event.wait(), timeout=poll_delay)

                # 1. Fetch next job (SKIP LOCKED prevents concurrent workers from taking the same job)
                async with async_session_maker() as session:
                    query = (
                        select(JobQueue)
                        .where(JobQueue.status.in_(["queued", "pending"]), JobQueue.queue_name == queue_name)
                        .order_by(JobQueue.priority.asc(), JobQueue.enqueued_at.asc())
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )

                    result = await session.execute(query)
                    job = result.scalar_one_or_none()

                    if not job:
                        # No job found — the next iteration will wait on notify_event
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

                    job_timeout = job.timeout or 1800  # Default 30 min
                    if asyncio.iscoroutinefunction(func):
                        res = await asyncio.wait_for(func(*job.args, **job.kwargs), timeout=job_timeout)
                    else:
                        res = func(*job.args, **job.kwargs)

                    # 4. Success -> Completed
                    async with async_session_maker() as session:
                        stmt = (
                            update(JobQueue)
                            .where(JobQueue.id == job.id)
                            .values(status="completed", result=res, completed_at=datetime.now(UTC))
                        )
                        await session.execute(stmt)
                        await session.commit()
                    logger.info("Job %s completed successfully", job.id)

                except TimeoutError:
                    logger.error("Job %s timed out after %ds", job.id, job.timeout or 1800)
                    queue = PostgresJobQueue(queue_name)
                    await queue.handle_job_failure(job.id, f"Job timed out after {job.timeout or 1800}s")

                except Exception as exc:
                    # 5. Failure -> Retry or Dead Letter
                    logger.exception("Job %s failed: %s", job.id, type(exc).__name__)
                    queue = PostgresJobQueue(queue_name)
                    await queue.handle_job_failure(job.id, str(exc))
                finally:
                    current_job_id = None

            except asyncio.CancelledError:
                logger.info("Worker loop cancelled.")
                if current_job_id:
                    try:
                        async with async_session_maker() as session:
                            stmt = (
                                update(JobQueue)
                                .where(JobQueue.id == current_job_id)
                                .values(status="failed", error="Worker shutdown", completed_at=datetime.now(UTC))
                            )
                            await session.execute(stmt)
                            await session.commit()
                        logger.info("Marked abandoned job %s as failed", current_job_id)
                    except (OSError, RuntimeError) as e:
                        logger.warning("Failed to mark abandoned job as failed: %s", e)
                break
            except Exception as exc:
                logger.exception("Error in worker loop: %s", type(exc).__name__)
                await asyncio.sleep(poll_delay)
    finally:
        if _pg_listener_conn is not None:
            with contextlib.suppress(Exception):
                await _pg_listener_conn.close()


async def queue_metrics(queue_name: str = "default") -> dict:
    """Return queue depth, in-progress count, and wait stats for scaling decisions."""
    from sqlalchemy import text

    async with async_session_maker() as session:
        result = await session.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE status IN ('queued', 'pending')) AS depth,
                    COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress,
                    COUNT(*) FILTER (WHERE status IN ('completed', 'failed')) AS completed,
                    EXTRACT(EPOCH FROM AVG(CASE
                        WHEN status = 'in_progress' THEN NOW() - enqueued_at
                    END)) AS avg_wait_seconds,
                    EXTRACT(EPOCH FROM MAX(CASE
                        WHEN status IN ('queued', 'pending') THEN NOW() - enqueued_at
                    END)) AS oldest_job_age_seconds
                FROM job_queue
                WHERE queue_name = :queue_name
            """),
            {"queue_name": queue_name},
        )
        row = result.first()
        return {
            "queue_name": queue_name,
            "depth": row.depth or 0,
            "in_progress": row.in_progress or 0,
            "completed": row.completed or 0,
            "avg_wait_seconds": round(float(row.avg_wait_seconds or 0), 2),
            "oldest_job_age_seconds": round(float(row.oldest_job_age_seconds or 0), 2),
        }

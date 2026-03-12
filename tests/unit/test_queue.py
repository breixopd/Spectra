import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.core.queue
from app.core.queue import Job, PostgresJobQueue
from app.models.infrastructure import InfrastructureBase, JobQueue


@pytest.fixture
def sqlite_engine():
    engine = create_engine("sqlite:///:memory:")
    InfrastructureBase.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(sqlite_engine):
    Session = sessionmaker(bind=sqlite_engine)
    session = Session()
    yield session
    session.close()


class MockSessionManager:
    def __init__(self, db_session):
        self.db_session = db_session

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def commit(self):
        self.db_session.commit()

    async def connection(self):
        class MockConnection:
            async def get_raw_connection(self):
                class MockRawConn:
                    pass

                return MockRawConn()

        return MockConnection()

    def add(self, obj):
        self.db_session.add(obj)

    async def execute(self, stmt):
        # Synchronously execute on db_session
        result = self.db_session.execute(stmt)

        # Mock result for async
        class MockResult:
            def __init__(self, res):
                self.res = res

            def scalar_one_or_none(self):
                # Attempt to get single scalar or full row based on what was requested
                row = self.res.first()
                if row is None:
                    return None
                if len(row) == 1:
                    return row[0]
                return row[0]  # Return the ORM object if it's the whole row

        return MockResult(result)


@pytest.fixture
def mock_session_maker(db_session, monkeypatch):
    def maker():
        return MockSessionManager(db_session)

    monkeypatch.setattr(app.core.queue, "async_session_maker", maker)
    return maker


@pytest.mark.asyncio
async def test_postgres_job_queue_enqueue(db_session, mock_session_maker):
    queue = PostgresJobQueue("test_q")
    job_id = await queue.enqueue_job("test_func", 1, 2, _timeout=10, kwarg1="val1")

    assert job_id is not None

    # Verify job is in DB
    job_record = db_session.query(JobQueue).filter_by(id=job_id).first()
    assert job_record is not None
    assert job_record.queue_name == "test_q"
    assert job_record.function == "test_func"
    assert job_record.args == [1, 2]
    assert job_record.kwargs == {"kwarg1": "val1"}
    assert job_record.status == "queued"
    assert job_record.timeout == 10


@pytest.mark.asyncio
async def test_job_status_and_result(db_session, mock_session_maker):
    # Add job directly
    job_id = "test_status_job"
    db_session.add(JobQueue(id=job_id, queue_name="q", function="f", status="completed", result={"ok": True}))
    db_session.commit()

    job = Job(job_id)
    assert await job.status() == "completed"
    assert await job.result() == {"ok": True}

    info = await job.info()
    assert info is not None
    assert info.function == "f"

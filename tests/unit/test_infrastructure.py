import json
from datetime import datetime
import pytest
from sqlalchemy import create_engine, Column, Integer
from sqlalchemy.orm import sessionmaker

from app.models.infrastructure import InfrastructureBase, JSONBType, SystemCache, JobQueue, SystemStatus

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

def test_jsonb_type_sqlite(db_session):
    # Test JSONBType behaves as expected with SQLite
    cache_item = SystemCache(key="test_key", value={"some": "data"})
    db_session.add(cache_item)
    db_session.commit()

    retrieved = db_session.query(SystemCache).filter_by(key="test_key").first()
    assert retrieved is not None
    assert retrieved.value == {"some": "data"}

def test_jsonb_type_none_values(db_session):
    # Test JSONBType handles None correctly where column allows null
    # JobQueue.result is nullable, SystemCache.value is not
    job = JobQueue(
        id="job_null",
        queue_name="test_q",
        function="my_func",
        result=None
    )
    db_session.add(job)
    db_session.commit()

    retrieved = db_session.query(JobQueue).filter_by(id="job_null").first()
    assert retrieved.result is None

def test_job_queue_model(db_session):
    job = JobQueue(
        id="job_1",
        queue_name="test_q",
        function="my_func",
        args=[1, 2],
        kwargs={"test": "val"},
        status="queued"
    )
    db_session.add(job)
    db_session.commit()

    retrieved = db_session.query(JobQueue).filter_by(id="job_1").first()
    assert retrieved.function == "my_func"
    assert retrieved.args == [1, 2]
    assert retrieved.kwargs == {"test": "val"}
    assert retrieved.status == "queued"

def test_system_status_model(db_session):
    status = SystemStatus(
        key="test_status",
        value={"is_ready": True}
    )
    db_session.add(status)
    db_session.commit()

    retrieved = db_session.query(SystemStatus).filter_by(key="test_status").first()
    assert retrieved.value == {"is_ready": True}
    assert isinstance(retrieved.updated_at, datetime)

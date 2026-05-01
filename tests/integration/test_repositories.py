"""
Unit tests for BaseRepository.
"""

import pytest
import pytest_asyncio
from sqlalchemy import String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from spectra_platform.repositories.base import BaseRepository

# --- Test Setup ---


class MockBase(DeclarativeBase):
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)


class MockModel(MockBase):
    __tablename__ = "test_model"


class MockRepository(BaseRepository[MockModel]):  # type: ignore[type-var]
    pass


@pytest_asyncio.fixture
async def db_session():
    """Create an in-memory SQLite session for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(MockBase.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session


# --- Tests ---


@pytest.mark.asyncio
async def test_create_and_get(db_session):
    repo = MockRepository(MockModel, db_session)

    # Create
    item = await repo.create(id="1", name="Test Item")
    assert item.id == "1"
    assert item.name == "Test Item"

    # Get by ID
    fetched = await repo.get_by_id("1")
    assert fetched is not None
    assert fetched.name == "Test Item"


@pytest.mark.asyncio
async def test_find_one_by(db_session):
    repo = MockRepository(MockModel, db_session)
    await repo.create(id="1", name="Unique Name")

    found = await repo.find_one_by(name="Unique Name")
    assert found is not None
    assert found.id == "1"


@pytest.mark.asyncio
async def test_delete(db_session):
    repo = MockRepository(MockModel, db_session)
    await repo.create(id="1", name="To Delete")

    deleted = await repo.delete("1")
    assert deleted is True

    fetched = await repo.get_by_id("1")
    assert fetched is None

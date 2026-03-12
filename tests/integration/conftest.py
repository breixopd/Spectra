"""Shared fixtures for integration tests.

Provides an async HTTP client backed by the real FastAPI app (via ASGI
transport) and authentication helpers so tests can exercise the API without
a running server.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token
from tests.conftest import make_mock_user


@pytest_asyncio.fixture
async def client():
    """Provide an async test client wired to the FastAPI application."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def test_user():
    """Return a mock admin user for dependency overrides."""
    return make_mock_user(username="integrationuser", email="int@spectra.dev")


@pytest.fixture
def auth_headers(test_user) -> dict[str, str]:
    """Return Authorization headers containing a valid JWT for *test_user*."""
    token = create_access_token(data={"sub": test_user.username})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def _override_auth(test_user):
    """Override FastAPI auth dependency to return *test_user* without DB lookup.

    This is an autouse-friendly fixture that patches get_current_user so
    integration tests hitting protected endpoints don't need a real database
    user row.
    """
    from app.api.dependencies import get_current_active_user, get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_current_active_user] = lambda: test_user
    yield
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_active_user, None)


@pytest.fixture
def mock_db_session():
    """Provide a standalone mock AsyncSession for integration tests that
    need to assert DB interactions without a real database."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    return session

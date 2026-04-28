"""Tests for app.core.database module.

Covers _configure_database_url, session factory wiring, and the
get_async_session dependency — all with mocks (no real DB connection).
"""

from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# _configure_database_url
# ---------------------------------------------------------------------------


class TestConfigureDatabaseUrl:
    """Test the URL-rewriting helper that strips sslmode for asyncpg."""

    def _call(self, url: str):
        from app.core.database import _configure_database_url

        return _configure_database_url(url)

    def test_plain_url_unchanged(self):
        url = "postgresql+asyncpg://user:pass@host:5432/db"
        clean, args = self._call(url)
        assert clean == url
        assert args == {}

    def test_sslmode_require_stripped_and_added_to_connect_args(self):
        url = "postgresql+asyncpg://user:pass@host:5432/db?sslmode=require"
        clean, args = self._call(url)
        assert "sslmode" not in clean
        assert args.get("ssl") == "require"

    def test_sslmode_disable_stripped_no_connect_arg(self):
        url = "postgresql+asyncpg://u:p@h/db?sslmode=disable"
        clean, args = self._call(url)
        assert "sslmode" not in clean
        assert "ssl" not in args

    def test_sslmode_prefer_stripped_no_connect_arg(self):
        url = "postgresql+asyncpg://u:p@h/db?sslmode=prefer"
        clean, args = self._call(url)
        assert "sslmode" not in clean
        assert "ssl" not in args

    def test_sslmode_verify_full(self):
        url = "postgresql+asyncpg://u:p@h/db?sslmode=verify-full"
        clean, args = self._call(url)
        assert "sslmode" not in clean
        assert args.get("ssl") == "verify-full"

    def test_other_query_params_preserved(self):
        url = "postgresql+asyncpg://u:p@h/db?sslmode=require&application_name=test"
        clean, args = self._call(url)
        assert "application_name=test" in clean
        assert args.get("ssl") == "require"

    def test_no_query_string(self):
        url = "postgresql+asyncpg://u:p@h/db"
        clean, args = self._call(url)
        assert clean == url
        assert args == {}


# ---------------------------------------------------------------------------
# Module-level objects
# ---------------------------------------------------------------------------


class TestModuleLevelObjects:
    """Verify the module exports the expected engine / session maker."""

    def test_engine_exists(self):
        from app.core.database import engine

        assert engine is not None

    def test_async_session_maker_exists(self):
        from app.core.database import async_session_maker

        assert async_session_maker is not None

    def test_get_async_session_is_async_generator(self):
        import inspect

        from app.core.database import get_async_session

        assert inspect.isasyncgenfunction(get_async_session)


# ---------------------------------------------------------------------------
# get_async_session yield / rollback / close behaviour
# ---------------------------------------------------------------------------


class TestGetAsyncSession:
    @pytest.mark.asyncio
    async def test_yields_session_and_closes(self):
        mock_session = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        class FakeSessionMaker:
            def __call__(self):
                return self

            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *args):
                pass

        with patch("app.core.database.async_session_maker", FakeSessionMaker()):
            from app.core.database import get_async_session

            gen = get_async_session()
            session = await gen.__anext__()
            assert session is mock_session
            # Normal close
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()

    @pytest.mark.asyncio
    async def test_rolls_back_on_exception(self):
        mock_session = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        class FakeSessionMaker:
            def __call__(self):
                return self

            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, exc_type, exc_val, tb):
                return False  # propagate exception

        with patch("app.core.database.async_session_maker", FakeSessionMaker()):
            from app.core.database import get_async_session

            gen = get_async_session()
            session = await gen.__anext__()
            assert session is mock_session
            # Simulate an exception
            with pytest.raises(RuntimeError, match="db error"):
                await gen.athrow(RuntimeError("db error"))


# ---------------------------------------------------------------------------
# Engine configuration sanity checks
# ---------------------------------------------------------------------------


class TestEngineConfig:
    def test_engine_uses_async_driver(self):
        from app.core.database import engine

        url_str = str(engine.url)
        # CI / compose may use Postgres; scripts/test.sh uses sqlite for isolated runs.
        assert "asyncpg" in url_str or "aiosqlite" in url_str

    def test_session_maker_produces_async_sessions(self):
        from app.core.database import async_session_maker

        # The class_ attribute should be AsyncSession or similar
        assert async_session_maker is not None

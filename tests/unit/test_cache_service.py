"""Unit tests for CacheService (app/services/cache.py) — namespace-based static cache."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_session_ctx(session: AsyncMock):
    """Build an async context manager that yields *session*."""

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *a):
            pass

    return _Ctx()


class TestCacheServiceSetGet:
    @pytest.mark.asyncio
    async def test_set_get_round_trip(self):
        from app.services.cache import CacheService

        session = AsyncMock()
        # get() executes a SELECT; simulate returning the value
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "hello"
        session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.services.cache.async_session_maker",
            return_value=_make_session_ctx(session),
        ):
            result = await CacheService.get("ns", "k1")

        assert result == "hello"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self):
        from app.services.cache import CacheService

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.services.cache.async_session_maker",
            return_value=_make_session_ctx(session),
        ):
            result = await CacheService.get("ns", "nonexistent")

        assert result is None


class TestCacheServiceExpiry:
    @pytest.mark.asyncio
    async def test_expired_entry_filtered_by_query(self):
        """get() WHERE clause filters expired entries — DB returns None."""
        from app.services.cache import CacheService

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.services.cache.async_session_maker",
            return_value=_make_session_ctx(session),
        ):
            result = await CacheService.get("ns", "expired_key")

        assert result is None


class TestCacheServiceDelete:
    @pytest.mark.asyncio
    async def test_delete_executes_and_commits(self):
        from app.services.cache import CacheService

        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()

        with patch(
            "app.services.cache.async_session_maker",
            return_value=_make_session_ctx(session),
        ):
            await CacheService.delete("ns", "k1")

        session.execute.assert_awaited_once()
        session.commit.assert_awaited_once()


class TestCacheServiceListKeys:
    @pytest.mark.asyncio
    async def test_list_keys_returns_stripped_keys(self):
        from app.services.cache import CacheService

        session = AsyncMock()
        scalars = MagicMock()
        scalars.all.return_value = ["myns:alpha", "myns:beta"]
        mock_result = MagicMock()
        mock_result.scalars.return_value = scalars
        session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.services.cache.async_session_maker",
            return_value=_make_session_ctx(session),
        ):
            keys = await CacheService.list_keys("myns")

        assert keys == ["alpha", "beta"]

    @pytest.mark.asyncio
    async def test_list_keys_empty_namespace(self):
        from app.services.cache import CacheService

        session = AsyncMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = scalars
        session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.services.cache.async_session_maker",
            return_value=_make_session_ctx(session),
        ):
            keys = await CacheService.list_keys("empty")

        assert keys == []


class TestCacheServiceNamespaceIsolation:
    @pytest.mark.asyncio
    async def test_full_key_includes_namespace(self):
        from app.services.cache import CacheService

        assert CacheService._full_key("tools", "nmap") == "tools:nmap"
        assert CacheService._full_key("rag", "doc1") == "rag:doc1"
        # Different namespaces produce different keys
        assert CacheService._full_key("a", "k") != CacheService._full_key("b", "k")

    @pytest.mark.asyncio
    async def test_db_error_returns_none_for_get(self):
        from app.services.cache import CacheService

        with patch(
            "app.services.cache.async_session_maker",
            side_effect=RuntimeError("db down"),
        ):
            result = await CacheService.get("ns", "k")

        assert result is None

    @pytest.mark.asyncio
    async def test_db_error_returns_empty_for_list_keys(self):
        from app.services.cache import CacheService

        with patch(
            "app.services.cache.async_session_maker",
            side_effect=RuntimeError("db down"),
        ):
            keys = await CacheService.list_keys("ns")

        assert keys == []
